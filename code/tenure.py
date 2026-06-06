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

from config import get_highest_rank

__all__ = [
    "period_sort_key",
    "group_ranks_by_source_line",
    "highest_rank_per_group",
    "ordered_source_lines",
    "running_cummax",
    "source_line_rank_maps",
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
