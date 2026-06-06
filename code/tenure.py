"""
Tenure-group primitives (v9) — pure helpers shared by postprocess
(本时期行政级别 running cummax) and derive_labels (升迁/本省提拔/本省学习).

Background
----------
step1 splits one original career line into multiple episodes that share a
``source_line`` when an official held concurrent posts (兼职). Rank logic must
therefore operate on the *group* of episodes for a source_line, taking the
highest rank in the group (就高不就低), not on individual rows.升迁/本省提拔
判定（PR3）同样必须在「任期组序列」上跑，不能机械看上下行。

These functions were extracted verbatim from ``postprocess.build_person_rows``
(no behaviour change, PR2) so derive_labels can reuse the exact same grouping
the Excel export already trusts.

All functions are pure: no I/O, no LLM, deterministic. ``get_highest_rank`` is
imported from ``config`` (the same one postprocess已在用) to keep behaviour
byte-identical.
"""
from __future__ import annotations

import re

from config import (
    CITY_NORMALIZE,
    DIRECT_MUNICIPALITIES,
    PROVINCE_NORMALIZE,
    get_highest_rank,
)

__all__ = [
    # rank / group primitives
    "period_sort_key",
    "group_ranks_by_source_line",
    "highest_rank_per_group",
    "ordered_source_lines",
    "running_cummax",
    "source_line_rank_maps",
    # place normalisation + single-row office predicates
    "normalise_province",
    "normalise_city",
    "is_mayor_row",
    "is_secretary_row",
    "is_governor_row",
    "is_prov_secretary_row",
    "_strip_admin_suffix",
]


def period_sort_key(start: str) -> int:
    """Sortable int for a 起始时间 string ``"YYYY.MM"``.

    Missing/partial/invalid → sorts last (year 9999). Month defaults to 0 when
    absent (e.g. ``"YYYY.00"`` or bare ``"YYYY"``). Mirrors the inline logic
    previously in postprocess.
    """
    s = start or ""
    year = int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else 9999
    month = int(s[5:7]) if len(s) >= 7 and s[5:7].isdigit() else 0
    return year * 100 + month


def group_ranks_by_source_line(
    episodes: list[dict], rank_map: dict[int, str] | None = None,
) -> dict[int, list[str]]:
    """Group per-episode ranks by source_line (concurrent 兼职 share a line).

    Rank for an episode = its own ``"行政级别"`` field, else ``rank_map[pos]``
    where ``pos`` is the 1-based position of the episode in ``episodes``.
    Episodes lacking ``source_line`` fall back to their 1-based position.
    """
    rank_map = rank_map or {}
    groups: dict[int, list[str]] = {}
    for idx, ep in enumerate(episodes):
        sl = ep.get("source_line", idx + 1)
        rank_val = ep.get("行政级别") or rank_map.get(idx + 1, "")
        groups.setdefault(sl, []).append(rank_val)
    return groups


def highest_rank_per_group(
    sl_rank_groups: dict[int, list[str]],
) -> dict[int, str]:
    """Per source_line, the highest concurrent rank (就高不就低).

    A group with no valid rank (e.g. only ``"无"`` / study) → ``""``.
    """
    return {sl: get_highest_rank(ranks) for sl, ranks in sl_rank_groups.items()}


def ordered_source_lines(
    episodes: list[dict], sl_highest_rank: dict[int, str],
) -> list[tuple[int, str]]:
    """Source lines ordered by start time, deduped (first occurrence kept).

    Returns ``[(source_line, group_highest_rank), ...]`` in chronological order.
    """
    order: list[tuple[int, int, str]] = []
    for idx, ep in enumerate(episodes):
        sl = ep.get("source_line", idx + 1)
        start = ep.get("起始时间", "") or ""
        order.append((period_sort_key(start), sl, sl_highest_rank.get(sl, "")))
    seen: set[int] = set()
    ordered: list[tuple[int, str]] = []
    for _, sl, rank in sorted(order):
        if sl not in seen:
            seen.add(sl)
            ordered.append((sl, rank))
    return ordered


def running_cummax(ordered_sl: list[tuple[int, str]]) -> dict[int, str]:
    """Running maximum rank per source_line (本时期行政级别).

    Monotonic non-decreasing: never drops below a previously achieved rank
    (so a temporary study episode with ``"无"`` does not lower the standing).
    """
    cummax: dict[int, str] = {}
    best = ""
    for sl, rank in ordered_sl:
        best = get_highest_rank([best, rank]) if best else rank
        cummax[sl] = best
    return cummax


def source_line_rank_maps(
    episodes: list[dict], rank_map: dict[int, str] | None = None,
) -> tuple[dict[int, str], dict[int, str]]:
    """Convenience composite: ``(sl_highest_rank, sl_cummax)``.

    - ``sl_highest_rank[sl]`` = 该 source_line 组内最高级别（兼职就高不就低）
    - ``sl_cummax[sl]``       = 截至该 source_line 的 running cummax（本时期行政级别）

    This is exactly the pair postprocess.build_person_rows consumes.
    """
    groups = group_ranks_by_source_line(episodes, rank_map)
    sl_highest = highest_rank_per_group(groups)
    ordered = ordered_source_lines(episodes, sl_highest)
    sl_cummax = running_cummax(ordered)
    return sl_highest, sl_cummax


# ── Place-name normalisation ────────────────────────────────────────────────
# Extracted verbatim from postprocess (PR2) so derive_labels can reuse the same
# province/city matching without importing postprocess (which would cycle, since
# postprocess imports derive_labels in Phase 2).

def normalise_province(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    if raw in PROVINCE_NORMALIZE.values():
        return raw
    if raw in PROVINCE_NORMALIZE:
        return PROVINCE_NORMALIZE[raw]
    for short, full in PROVINCE_NORMALIZE.items():
        if raw.startswith(short) or full.startswith(raw):
            return full
    return raw


def normalise_city(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    if re.search(r"[市区县州盟]$", raw):
        return raw
    if raw in CITY_NORMALIZE:
        return CITY_NORMALIZE[raw]
    for short, full in CITY_NORMALIZE.items():
        if raw.startswith(short):
            return full
    return raw


# ── Single-row office predicates ────────────────────────────────────────────

def _strip_admin_suffix(name: str) -> str:
    name = re.sub(r"(壮族|回族|维吾尔)?自治区$", "", name)
    name = re.sub(r"特别行政区$", "", name)
    name = re.sub(r"省$", "", name)
    # 仅删直辖市的"市"后缀；不可删"州/盟"（否则"贵州"→"贵"导致省份匹配失败）
    return re.sub(r"市$", "", name)


def _match_position(
    position: str, unit: str, location: str, target: str,
    *, role: str,
) -> int:
    if not position:
        return 0
    target_short = _strip_admin_suffix(target)
    context = (unit or "") + (location or "")
    if context and target_short not in context:
        return 0
    is_municipality = target_short in DIRECT_MUNICIPALITIES

    if role == "governor":
        if "副省长" in position or "副主席" in position or "常务副" in position:
            return 0
        if "助理" in position:  # 省长助理/主席助理 ≠ 行政首长
            return 0
        if re.search(r"(^|[\s、，,])(?:代)?省长(?!助理)", position):
            return 1
        if re.search(r"(^|[\s、，,])(?:代)?主席", position):
            ctx = (unit or "") + position
            # 排除群团/议事机构的"主席"（仅自治区政府主席才算行政首长）
            non_gov = ("政协", "人大", "工会", "妇联", "残联", "侨联",
                       "文联", "科协", "工商联", "红十字", "贸促",
                       "作协", "记协", "青联", "学联")
            if any(k in ctx for k in non_gov):
                return 0
            return 1
        if is_municipality:
            if "副市长" not in position and re.search(r"(^|[\s、，,])(?:代)?市长", position):
                return 1
    elif role == "secretary":
        if "副书记" in position:
            return 0
        if re.search(r"(^|[\s、，,])省委书记", position):
            return 1
        if re.search(r"(^|[\s、，,])自治区党委书记", position):
            return 1
        if is_municipality and re.search(r"(^|[\s、，,])市委书记", position):
            return 1
        if re.search(r"(^|[\s、，,])书记$", position):
            u = unit or ""
            # 群团/议事/纪检等含"委"但非党委的机构，一律排除
            bad_org = any(k in u for k in ("共青团", "团委", "纪委", "政法委",
                                            "工会", "妇联", "政协", "人大"))
            # 省级党委正名：中共XX省委 / 中共XX自治区委(员会) / XX自治区党委
            # 不可用"区委$"兜底（会误匹配县辖"华溪区委/城郊区委"）
            is_prov_party = (
                bool(re.search(r"中共.*省委(员会)?$", u))
                or "自治区党委" in u
                or bool(re.search(r"中共.*自治区委(员会)?$", u))
            )
            if is_prov_party and not bad_org:
                return 1
            # 直辖市党委：中共北京/上海/天津/重庆市委
            if is_municipality and re.search(r"中共.*市委(员会)?$", u) and not bad_org:
                return 1
    elif role == "mayor":
        if "副市长" in position or "常务副" in position:
            return 0
        if re.search(r"(^|[\s、，,])(?:代)?市长", position):
            return 1
    elif role == "city_secretary":
        if "副书记" in position or "副市委" in position:
            return 0
        if re.search(r"(^|[\s、，,])市委书记", position):
            return 1
        if re.search(r"(^|[\s、，,])书记$", position) and "市委" in (unit or ""):
            return 1
    return 0


def is_mayor_row(position, unit, location_city, target_city):
    return _match_position(position, unit, location_city, target_city, role="mayor")

def is_secretary_row(position, unit, location_city, target_city):
    return _match_position(position, unit, location_city, target_city, role="city_secretary")

def is_governor_row(position, unit, location_prov, target_province):
    return _match_position(position, unit, location_prov, target_province, role="governor")

def is_prov_secretary_row(position, unit, location_prov, target_province):
    return _match_position(position, unit, location_prov, target_province, role="secretary")
