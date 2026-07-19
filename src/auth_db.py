import json
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import Depends
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import DatabaseStrategy
from fastapi_users.db import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase
from fastapi_users.password import PasswordHelper
from fastapi_users_db_sqlalchemy.access_token import (
    SQLAlchemyAccessTokenDatabase,
    SQLAlchemyBaseAccessTokenTableUUID,
)
from sqlalchemy import Boolean, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, synonym

APP_DATA_DIR = Path(os.environ.get("APP_DATA_DIR", "/app/data"))
AUTH_DB_PATH = APP_DATA_DIR / "auth.db"
AUTH_SECRET = os.environ.get("SESSION_SECRET", "change-me-please")
# The reverse proxy (Traefik) terminates TLS in front of this app, but the
# container's own port is also reachable directly over plain HTTP - default
# to non-Secure cookies so login still works there, matching the previous
# session-cookie behavior. Set COOKIE_SECURE=true if only ever served over HTTPS.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
SESSION_LIFETIME_SECONDS = 14 * 24 * 60 * 60

engine = create_async_engine(f"sqlite+aiosqlite:///{AUTH_DB_PATH}")
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    # fastapi-users models identity as "email"; this app has no real email
    # addresses, just usernames, so alias it for readability in our own code.
    username = synonym("email")
    # Read-only role: can view every page but every write route rejects
    # them. A row should never have both is_superuser and is_viewer set --
    # see set_user_role() below, the only place either flag is written.
    is_viewer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    pass


async def create_db_and_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_is_viewer_column_if_missing)


def _add_is_viewer_column_if_missing(sync_conn) -> None:
    """create_all only creates missing *tables*, not missing columns on a
    table that already existed before this column was added -- the live
    auth.db already has a populated user table without is_viewer, so a
    fresh install (where create_all above already included it) and an
    upgrade (needs this ALTER TABLE) both end up consistent."""
    columns = [row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info(user)").fetchall()]
    if "is_viewer" not in columns:
        sync_conn.exec_driver_sql("ALTER TABLE user ADD COLUMN is_viewer BOOLEAN NOT NULL DEFAULT 0")


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User)


async def get_access_token_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyAccessTokenDatabase(session, AccessToken)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = AUTH_SECRET
    verification_token_secret = AUTH_SECRET


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)


cookie_transport = CookieTransport(
    cookie_name="pzadmin_auth",
    cookie_max_age=SESSION_LIFETIME_SECONDS,
    cookie_secure=COOKIE_SECURE,
    cookie_samesite="lax",
)


def get_database_strategy(
    access_token_db: SQLAlchemyAccessTokenDatabase = Depends(get_access_token_db),
) -> DatabaseStrategy:
    return DatabaseStrategy(access_token_db, lifetime_seconds=SESSION_LIFETIME_SECONDS)


auth_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_database_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_user_optional = fastapi_users.current_user(optional=True, active=True)
current_user_token_optional = fastapi_users.authenticator.current_user_token(
    optional=True, active=True
)


async def migrate_users_json(users_json_path: Path) -> int:
    """One-time import of the legacy plaintext users.json into the auth DB,
    hashing passwords on the way in. No-ops once the DB already has users,
    or if there's no users.json to import."""
    if not users_json_path.exists():
        return 0

    password_helper = PasswordHelper()
    created = 0
    async with async_session_maker() as session:
        existing = await session.execute(select(User.id).limit(1))
        if existing.first() is not None:
            return 0

        data = json.loads(users_json_path.read_text())
        user_db = SQLAlchemyUserDatabase(session, User)
        for entry in data.get("users", []):
            username = (entry.get("username") or "").strip()
            password = entry.get("password") or ""
            if not username or not password:
                continue
            await user_db.create(
                {
                    "email": username,
                    "hashed_password": password_helper.hash(password),
                    "is_active": True,
                    "is_superuser": True,
                    "is_verified": True,
                }
            )
            created += 1
    return created


class UsernameTakenError(Exception):
    pass


class LastSuperuserError(Exception):
    """Raised when an action would leave zero active admins, locking everyone out."""


async def list_users() -> list[User]:
    async with async_session_maker() as session:
        result = await session.execute(select(User).order_by(User.email))
        return list(result.scalars())


async def get_user_by_id(user_id: uuid.UUID) -> User | None:
    async with async_session_maker() as session:
        return await session.get(User, user_id)


async def create_user(username: str, password: str, role: str = "user") -> User:
    """role: "admin" | "user" | "viewer"."""
    password_helper = PasswordHelper()
    async with async_session_maker() as session:
        user_db = SQLAlchemyUserDatabase(session, User)
        if await user_db.get_by_email(username) is not None:
            raise UsernameTakenError(username)
        return await user_db.create(
            {
                "email": username,
                "hashed_password": password_helper.hash(password),
                "is_active": True,
                "is_superuser": role == "admin",
                "is_viewer": role == "viewer",
                "is_verified": True,
            }
        )


async def _active_superuser_count(session: AsyncSession, exclude_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(User)
        .where(User.is_active.is_(True), User.is_superuser.is_(True), User.id != exclude_id)
    )
    return (await session.execute(stmt)).scalar_one()


async def set_user_active(user_id: uuid.UUID, active: bool) -> None:
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        if user is None:
            return
        if not active and user.is_superuser and await _active_superuser_count(session, user_id) == 0:
            raise LastSuperuserError()
        user.is_active = active
        session.add(user)
        await session.commit()


async def set_user_role(user_id: uuid.UUID, role: str) -> None:
    """role: "admin" | "user" | "viewer". Sets is_superuser/is_viewer
    together so a row is never both (or neither meaningfully ambiguous)."""
    is_superuser = role == "admin"
    is_viewer = role == "viewer"
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        if user is None:
            return
        if (
            not is_superuser
            and user.is_superuser
            and user.is_active
            and await _active_superuser_count(session, user_id) == 0
        ):
            raise LastSuperuserError()
        user.is_superuser = is_superuser
        user.is_viewer = is_viewer
        session.add(user)
        await session.commit()


async def set_user_password(user_id: uuid.UUID, new_password: str) -> None:
    password_helper = PasswordHelper()
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        if user is None:
            return
        user.hashed_password = password_helper.hash(new_password)
        session.add(user)
        await session.commit()


async def delete_user(user_id: uuid.UUID) -> None:
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        if user is None:
            return
        if user.is_superuser and user.is_active and await _active_superuser_count(session, user_id) == 0:
            raise LastSuperuserError()
        await session.delete(user)
        await session.commit()
