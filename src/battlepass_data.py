import json
from pathlib import Path


def load_battlepass_data(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _build_player(username: str, pdata: dict, total_feats: int, total_quests: int, total_tiers: int) -> dict:
    current = pdata.get("currentSeason") or {}
    lifetime = pdata.get("lifetimeStats") or {}
    skills = pdata.get("skillLevels") or {}
    tiers = current.get("tiers") or {}

    completed_quests = sum(len(v) for v in (current.get("completedQuestIds") or {}).values())
    top_skills = sorted(
        ((name, lvl) for name, lvl in skills.items() if lvl),
        key=lambda kv: kv[1],
        reverse=True,
    )[:3]

    return {
        "username": username,
        "balance": current.get("balance", 0),
        "lifetime_earned": current.get("lifetimeEarned", 0),
        "completed_feats": len(current.get("completedFeatIds") or []),
        "total_feats": total_feats,
        "completed_quests": completed_quests,
        "total_quests": total_quests,
        "completed_tiers": len(tiers.get("completedTierIds") or []),
        "total_tiers": total_tiers,
        "claimed_items": len(tiers.get("claimedItemIds") or []),
        "deaths": lifetime.get("deaths", 0),
        "drive_minutes": lifetime.get("driveMinutes", 0),
        "shots_fired": lifetime.get("shotsFired", 0),
        "reloads": lifetime.get("reloads", 0),
        "total_crafted": lifetime.get("totalCrafted", 0),
        "total_cooked": lifetime.get("totalCooked", 0),
        "total_harvests": lifetime.get("totalHarvests", 0),
        "total_mechanic_actions": lifetime.get("totalMechanicActions", 0),
        "skill_books_read": lifetime.get("skillBooksRead", 0),
        "fish_total_caught": lifetime.get("fishTotalCaught", 0),
        "fish_biggest_weight": lifetime.get("fishBiggestWeightLbs", 0),
        "top_skills": top_skills,
    }


def _counts_by_type(value) -> list[dict]:
    """`craftCountsByRecipe`/`farmCountsByType`/`fishCountsByType`/
    `vehicleCountsByType` are Lua maps (name -> count); an empty Lua table
    serializes as a JSON array (`[]`) since there's no way to tell an empty
    map from an empty list, so `value` may be a dict or an empty list."""
    if not isinstance(value, dict):
        return []
    return sorted(
        ({"name": name, "count": count} for name, count in value.items()),
        key=lambda e: e["count"],
        reverse=True,
    )


def build_player_detail(data: dict, username: str) -> dict | None:
    """Full per-player detail joining raw progress against the season's
    definitions, so every feat/quest/tier shows both its definition and
    whether this player has completed/claimed it - not just the raw
    completed-id lists."""
    players = data.get("players") or {}
    pdata = players.get(username)
    if pdata is None:
        return None

    definitions = data.get("definitions") or {}
    current = pdata.get("currentSeason") or {}
    lifetime = pdata.get("lifetimeStats") or {}
    skills = pdata.get("skillLevels") or {}
    tiers_progress = current.get("tiers") or {}

    completed_feat_ids = set(current.get("completedFeatIds") or [])
    feats = [
        {**feat, "completed": feat.get("id") in completed_feat_ids}
        for feat in (definitions.get("feats") or [])
    ]

    completed_quest_ids = current.get("completedQuestIds") or {}
    quests_by_category = []
    for category, quest_defs in (definitions.get("quests") or {}).items():
        completed_ids = set(completed_quest_ids.get(category) or [])
        quests = [
            {**q, "completed": q.get("id") in completed_ids}
            for q in quest_defs
        ]
        quests_by_category.append({
            "category": category,
            "quests": quests,
            "completed_count": sum(1 for q in quests if q["completed"]),
            "total_count": len(quests),
        })

    completed_tier_ids = set(tiers_progress.get("completedTierIds") or [])
    claimed_item_ids = set(tiers_progress.get("claimedItemIds") or [])
    tiers = []
    for tier in sorted(definitions.get("tiers") or [], key=lambda t: t.get("order", 0)):
        # Jinja's `t.items` would resolve to dict.items (a bound method) before
        # falling back to subscript, so this can't be named "items" in the dict.
        tier_items = [
            {**item, "claimed": item.get("id") in claimed_item_ids}
            for item in (tier.get("items") or [])
        ]
        tiers.append({**tier, "tier_items": tier_items, "completed": tier.get("id") in completed_tier_ids})

    skill_levels = sorted(
        ((name, lvl) for name, lvl in skills.items()),
        key=lambda kv: kv[1],
        reverse=True,
    )

    return {
        "username": username,
        "balance": current.get("balance", 0),
        "lifetime_earned": current.get("lifetimeEarned", 0),
        "feats": feats,
        "quests_by_category": quests_by_category,
        "tiers": tiers,
        "claimed_items_count": len(claimed_item_ids),
        "lifetime_stats": {
            "deaths": lifetime.get("deaths", 0),
            "drive_minutes": lifetime.get("driveMinutes", 0),
            "shots_fired": lifetime.get("shotsFired", 0),
            "reloads": lifetime.get("reloads", 0),
            "total_crafted": lifetime.get("totalCrafted", 0),
            "total_cooked": lifetime.get("totalCooked", 0),
            "total_harvests": lifetime.get("totalHarvests", 0),
            "total_mechanic_actions": lifetime.get("totalMechanicActions", 0),
            "skill_books_read": lifetime.get("skillBooksRead", 0),
            "fish_total_caught": lifetime.get("fishTotalCaught", 0),
            "fish_biggest_weight": lifetime.get("fishBiggestWeightLbs", 0),
        },
        "craft_counts": _counts_by_type(lifetime.get("craftCountsByRecipe")),
        "farm_counts": _counts_by_type(lifetime.get("farmCountsByType")),
        "fish_counts": _counts_by_type(lifetime.get("fishCountsByType")),
        "vehicle_counts": _counts_by_type(lifetime.get("vehicleCountsByType")),
        "skill_levels": skill_levels,
    }


def _compute_highlights(players: list[dict]) -> list[dict]:
    def leader(key: str, label: str, unit: str = "") -> dict | None:
        top = max(players, key=lambda p: p[key], default=None)
        if not top or not top[key]:
            return None
        return {"label": label, "username": top["username"], "value": top[key], "unit": unit}

    highlights = [
        leader("lifetime_earned", "Most Points Earned"),
        leader("total_crafted", "Most Items Crafted"),
        leader("deaths", "Most Deaths"),
        leader("fish_biggest_weight", "Biggest Catch", "lbs"),
    ]
    return [h for h in highlights if h]


def build_leaderboard(data: dict) -> dict:
    """Turn the raw BattlePassPlayerData.json export into a leaderboard-ready
    summary: derived per-player stats (ranked by lifetime points earned) plus
    season info and definition totals used for progress counts."""
    definitions = data.get("definitions") or {}
    total_feats = len(definitions.get("feats") or [])
    total_quests = sum(len(v) for v in (definitions.get("quests") or {}).values())
    total_tiers = len(definitions.get("tiers") or [])

    players = [
        _build_player(username, pdata, total_feats, total_quests, total_tiers)
        for username, pdata in (data.get("players") or {}).items()
    ]
    players.sort(key=lambda p: p["lifetime_earned"], reverse=True)
    for i, p in enumerate(players, start=1):
        p["rank"] = i

    season = data.get("season") or {}

    return {
        "season_name": season.get("name") or "",
        "season_description": season.get("description") or "",
        "exported_at": data.get("exportedAt"),
        "total_feats": total_feats,
        "total_quests": total_quests,
        "total_tiers": total_tiers,
        "players": players,
        "highlights": _compute_highlights(players),
    }
