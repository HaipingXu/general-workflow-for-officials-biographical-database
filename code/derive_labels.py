"""Code-derived step4 labels (升迁 / 本省提拔 / 本省学习) — Phase 1.

Why
---
These three labels are essentially a *multi-condition comparison over a rank
sequence* — the inductive task class LLMs are worst at. step2/step3 already
computed the structured intermediates (任职地, 标志位, 行政级别); deriving the
labels in code just *compares ranks that are already computed* instead of
asking the model to re-infer them from raw prose.

Tenure-group model (兼职 解法)
------------------------------
官员常同期身兼数职；step1 把一条履历行按职务拆成多条 episode。机械地看上一行/
下一行会把**同期兼职**误当成前后任。所以判定**不在 episode 序列上跑，而在
「任期组（tenure group）序列」上跑**：同一 ``source_line`` 的 episodes = 同一
原始履历行的兼任 = 同一任期组（与 Excel 导出的 就高不就低 分组一致）。

升迁/提拔在「任期组序列」上比较组内最高级别（``get_highest_rank``）。

All functions are pure: no I/O, no LLM. ``departure`` (LLM 离任去向) is the only
LLM-sourced input, used solely to disambiguate 退休(2)/去世(3) when there is no
next tenure group (Phase 5).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from config import RANK_LEVELS, STUDY_FLAG, get_highest_rank
from tenure import (
    is_governor_row,
    is_prov_secretary_row,
    normalise_province,
    period_sort_key,
)

__all__ = [
    "derive_person_labels",
    "build_tenure_groups",
    "compute_promotion",
    "compute_local_promotion",
    "compute_local_study",
]

# Sentinel: 终止时间 == "至今" (or contains 今) → tenure still ongoing, sorts last.
ONGOING = 99999999

# Promotion label values (mirror the historical LLM coding):
#   1 升迁 | 0 平/降 | 2 退休 | 3 去世 | -1 在任 | "" 未任该职
PROMO_UP, PROMO_FLAT, PROMO_RETIRE, PROMO_DIED, PROMO_INCUMBENT, PROMO_NA = (
    1, 0, 2, 3, -1, "",
)


def _prov_field(ep: dict) -> str:
    return ep.get("任职地（省）", ep.get("任职地", "")) or ""


def _is_provincial_secretary(ep: dict) -> bool:
    """True iff 职务 is a *province-level* party secretary (省委书记 / 自治区党委书记).

    Deliberately **excludes 直辖市市委书记** (also 正部级): the C6/Q2 special case
    "省长→省委书记 算升迁" is about 省级行政区一把手. A 直辖市委书记 (不兼政治局)
    must fall through to the rank comparison, where 正部级→正部级 = 平调 (C4).
    """
    pos = ep.get("职务", "")
    if not pos or "副书记" in pos:
        return False
    return bool(
        re.search(r"(^|[\s、，,])省委书记", pos)
        or re.search(r"(^|[\s、，,])自治区党委书记", pos)
    )


def _rank_index(rank: str) -> int | None:
    return RANK_LEVELS.index(rank) if rank in RANK_LEVELS else None


def _rank_higher(a: str, b: str) -> bool:
    """True iff rank ``a`` is strictly higher than ``b`` (smaller index = higher).

    Unknown / off-scale ranks → not higher (conservative: no promotion).
    """
    ia, ib = _rank_index(a), _rank_index(b)
    if ia is None or ib is None:
        return False
    return ia < ib


# ── Tenure group ─────────────────────────────────────────────────────────────

@dataclass
class TenureGroup:
    sl: int
    start_key: int
    end_key: int
    is_ongoing: bool
    maxrank: str
    is_gov: bool          # 目标省省长（含代省长/自治区主席）
    is_sec: bool          # 目标省省委书记（含自治区党委书记）
    is_prov_sec_any: bool  # 省委书记/自治区党委书记（任意省，C6 用，不含直辖市）
    in_target: bool       # 组内任一 episode 任职地省 == 目标省
    eps: list[dict] = field(default_factory=list)

    def is_focal(self, role: str) -> bool:
        return self.is_gov if role == "governor" else self.is_sec


def build_tenure_groups(
    episodes: list[dict], target_province: str,
    rank_map: dict[int, str] | None = None,
) -> list[TenureGroup]:
    """Aggregate episodes into time-ordered tenure groups by ``source_line``."""
    rank_map = rank_map or {}
    target_norm = normalise_province(target_province)

    by_sl: dict[int, list[tuple[int, dict]]] = {}
    for idx, ep in enumerate(episodes):
        sl = ep.get("source_line", idx + 1)
        by_sl.setdefault(sl, []).append((idx, ep))

    groups: list[TenureGroup] = []
    for sl, items in by_sl.items():
        eps = [ep for _, ep in items]
        ranks = [ep.get("行政级别") or rank_map.get(idx + 1, "") for idx, ep in items]
        start_key = min(period_sort_key(ep.get("起始时间", "")) for ep in eps)

        ends = [ep.get("终止时间", "") or "" for ep in eps]
        is_ongoing = any("今" in e for e in ends)
        if is_ongoing:
            end_key = ONGOING
        else:
            eks = [period_sort_key(e) for e in ends if e.strip()]
            end_key = max(eks) if eks else start_key

        is_gov = any(
            is_governor_row(ep.get("职务", ""), ep.get("供职单位", ""),
                            _prov_field(ep), target_province)
            for ep in eps
        )
        is_sec = any(
            is_prov_secretary_row(ep.get("职务", ""), ep.get("供职单位", ""),
                                  _prov_field(ep), target_province)
            for ep in eps
        )
        is_prov_sec_any = any(_is_provincial_secretary(ep) for ep in eps)
        in_target = any(
            normalise_province(_prov_field(ep)) == target_norm and target_norm
            for ep in eps
        )

        groups.append(TenureGroup(
            sl=sl, start_key=start_key, end_key=end_key, is_ongoing=is_ongoing,
            maxrank=get_highest_rank(ranks), is_gov=is_gov, is_sec=is_sec,
            is_prov_sec_any=is_prov_sec_any, in_target=in_target, eps=eps,
        ))

    groups.sort(key=lambda g: (g.start_key, g.sl))
    return groups


# ── 升迁 (省长 / 省委书记) ────────────────────────────────────────────────────

def compute_promotion(
    groups: list[TenureGroup], role: str, departure: str = "",
) -> int | str:
    """升迁_{role}. role ∈ {"governor", "secretary"}.

    Returns 1 升 / 0 平降 / 2 退休 / 3 去世 / -1 在任 / "" 未任该职.
    """
    focal_idx = next(
        (i for i in range(len(groups) - 1, -1, -1) if groups[i].is_focal(role)),
        None,
    )
    if focal_idx is None:
        return PROMO_NA  # 未任该职

    # Merge backward consecutive focal groups → continuous 主官任期 (C5 代理连续).
    span_start = focal_idx
    while span_start - 1 >= 0 and groups[span_start - 1].is_focal(role):
        span_start -= 1
    span = groups[span_start:focal_idx + 1]
    span_end_key = groups[focal_idx].end_key
    span_ongoing = groups[focal_idx].is_ongoing
    span_maxrank = get_highest_rank([g.maxrank for g in span])
    span_ids = {id(g) for g in span}

    # Next tenure group: earliest group starting at/after the span's departure
    # (concurrent 兼职 groups start before span_end → naturally skipped, C2).
    g_next = None
    for g in groups:
        if id(g) in span_ids:
            continue
        if g.start_key >= span_end_key:
            if g_next is None or g.start_key < g_next.start_key:
                g_next = g

    if g_next is None:
        if span_ongoing:
            return PROMO_INCUMBENT  # 在任 (-1)
        if "退休" in departure:
            return PROMO_RETIRE
        if any(k in departure for k in ("去世", "逝世", "病逝", "病故", "殉职")):
            return PROMO_DIED
        return PROMO_FLAT  # 离任但无可比下一任期组：保守计 0

    # 升任省委书记 (任意省) → 1，即便行政级别平级 (C6/Q2)；仅对 省长 标签生效.
    if role == "governor" and g_next.is_prov_sec_any:
        return PROMO_UP

    return PROMO_UP if _rank_higher(g_next.maxrank, span_maxrank) else PROMO_FLAT


# ── 本省提拔 ──────────────────────────────────────────────────────────────────

def compute_local_promotion(groups: list[TenureGroup]) -> int:
    """本省提拔: 任前上一任期组是否在目标省. Returns 1 / 0 / -1.

    放宽口径（决策1）：只看任职地省==目标省，不要求省级机构；任前在本省地级市
    任职（如市长）也算 1.
    """
    g_first_idx = next(
        (i for i, g in enumerate(groups) if g.is_gov or g.is_sec),
        None,
    )
    if g_first_idx is None or g_first_idx == 0:
        return -1  # 无法判断 / 无前一任期组
    g_prev = groups[g_first_idx - 1]
    return 1 if g_prev.in_target else 0


# ── 本省学习 ──────────────────────────────────────────────────────────────────

def compute_local_study(
    episodes: list[dict], groups: list[TenureGroup], target_province: str,
) -> int:
    """本省学习: 任目标省主官前，是否有在目标省的脱产学习经历. Returns 1 / 0."""
    target_norm = normalise_province(target_province)
    t0 = next(
        (g.start_key for g in groups if g.is_gov or g.is_sec),
        None,
    )
    if t0 is None:
        return 0
    for ep in episodes:
        if period_sort_key(ep.get("起始时间", "")) >= t0:
            continue
        if ep.get("标志位", "") != STUDY_FLAG:
            continue
        if normalise_province(_prov_field(ep)) == target_norm and target_norm:
            return 1
    return 0


# ── Public entry ─────────────────────────────────────────────────────────────

def derive_person_labels(
    episodes: list[dict], target_province: str,
    rank_map: dict[int, str] | None = None,
    departure: dict | None = None,
) -> dict:
    """All four code-derived step4 labels for one official.

    ``departure`` = LLM 离任去向, e.g. ``{"省长": "退休", "省委书记": "有后续职务"}``
    (Phase 5; only used when there is no next tenure group).
    """
    departure = departure or {}
    groups = build_tenure_groups(episodes, target_province, rank_map)
    return {
        "升迁_省长": compute_promotion(groups, "governor", departure.get("省长", "")),
        "升迁_省委书记": compute_promotion(groups, "secretary", departure.get("省委书记", "")),
        "本省提拔": compute_local_promotion(groups),
        "本省学习": compute_local_study(episodes, groups, target_province),
    }
