"""Unit tests for derive_labels.py — 升迁 / 本省提拔 / 本省学习 (兼职 correctness).

Covers the C1–C10 兼职 correctness checklist from the plan (§4), the three
algorithms in isolation, plus the public entry point.

Run: `cd code && uv run python -m pytest tests/test_derive_labels.py -q`
Also runnable without pytest: `cd code && python3 tests/test_derive_labels.py`
"""
from derive_labels import (
    build_tenure_groups,
    compute_promotion,
    compute_local_promotion,
    compute_local_study,
    derive_person_labels,
)

TARGET = "浙江"


def ep(sl, start, end, pos, unit="", prov="浙江", rank="正部级", flag="无"):
    return {
        "source_line": sl, "起始时间": start, "终止时间": end,
        "职务": pos, "供职单位": unit, "任职地（省）": prov,
        "行政级别": rank, "标志位": flag,
    }


def _gov(eps, departure=""):
    return compute_promotion(build_tenure_groups(eps, TARGET), "governor", departure)


def _sec(eps, departure=""):
    return compute_promotion(build_tenure_groups(eps, TARGET), "secretary", departure)


# ── Baseline algorithm cases ─────────────────────────────────────────────────

def test_never_held_office_returns_empty():
    eps = [ep(1, "1998.01", "2003.01", "副省长", "浙江省人民政府", rank="副部级")]
    assert _gov(eps) == ""


def test_promotion_up_by_rank():
    # 省长(正部级) → 国务院副总理(副国级) = 升
    eps = [
        ep(1, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(2, "2003.01", "2008.01", "国务院副总理", "国务院", prov="", rank="副国级"),
    ]
    assert _gov(eps) == 1


def test_flat_move_same_rank_other_province():
    # 省长 → 他省省长 (both 正部级, not 书记) = 平调
    eps = [
        ep(1, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(2, "2003.01", "2008.01", "省长", "江苏省人民政府", prov="江苏", rank="正部级"),
    ]
    assert _gov(eps) == 0


# ── C1: 主官与省委副书记同组 (group-level any, not single row) ─────────────────

def test_c1_focal_via_group_any_then_retire():
    # 省长 与 省委副书记 同 source_line 兼职；副书记单行 is_gov=0，但组 any→省长
    eps = [
        ep(1, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(1, "1998.01", "2003.01", "省委副书记", "中共浙江省委", rank="副部级"),
    ]
    assert _gov(eps, departure="退休") == 2          # 无下一组 + 离任去向退休 → 2


# ── C2: 下一行是同期兼职、非去向 → 跳到下一任期组 ─────────────────────────────

def test_c2_skip_concurrent_to_next_tenure_group():
    eps = [
        ep(1, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(2, "2000.01", "2003.01", "省人大常委会主任", "浙江省人大",
           rank="正部级"),                                   # 同期兼职, 应跳过
        ep(3, "2003.01", "2008.01", "国务院副总理", "国务院", prov="", rank="副国级"),
    ]
    # 若误把 2000 的人大主任当下一组 → 正部级=正部级=0；正确跳过 → 副总理=1
    assert _gov(eps) == 1


# ── C3: 下一去向多兼职 → 取组内 max-rank (就高不就低) ─────────────────────────

def test_c3_next_group_takes_highest_concurrent_rank():
    eps = [
        ep(1, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(2, "2003.01", "2008.01", "国务委员", "国务院", prov="", rank="正部级"),
        ep(2, "2003.01", "2008.01", "中央政治局委员", "中共中央", prov="",
           rank="副国级"),                                   # 同组兼职, 就高
    ]
    assert _gov(eps) == 1                                     # max(next)=副国级 > 正部级


# ── C4: 直辖市委书记(不兼政治局)=平调 (rank 交给 step3, 不触发书记特例) ────────

def test_c4_municipal_secretary_is_flat():
    eps = [
        ep(1, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(2, "2003.01", "2008.01", "市委书记", "中共北京市委", prov="北京",
           rank="正部级"),                                    # 直辖市委书记 ≠ 省委书记
    ]
    assert _gov(eps) == 0


# ── C5: 代省长 → 省长 合并为连续主官任期 ──────────────────────────────────────

def test_c5_acting_then_formal_merged_chain_to_secretary():
    eps = [
        ep(1, "2001.01", "2002.01", "代省长", "浙江省人民政府", rank="正部级"),
        ep(2, "2002.01", "2005.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(3, "2005.01", "2010.01", "省委书记", "中共浙江省委", rank="正部级"),
    ]
    assert _gov(eps) == 1                                     # →省委书记 = 升 (C6)


def test_c5_acting_then_formal_then_retire_continuous():
    # 代省长 与 省长 合并：离任以正式省长终止时间为准；无下一组 + 退休 → 2
    eps = [
        ep(1, "2001.01", "2002.01", "代省长", "浙江省人民政府", rank="正部级"),
        ep(2, "2002.01", "2005.01", "省长", "浙江省人民政府", rank="正部级"),
    ]
    assert _gov(eps, departure="退休") == 2


# ── C6: 升任省委书记(平级, 含他省) → 1 ───────────────────────────────────────

def test_c6_governor_to_secretary_other_province_is_promotion():
    eps = [
        ep(1, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(2, "2003.01", "2008.01", "省委书记", "中共江苏省委", prov="江苏",
           rank="正部级"),                                    # 他省书记, 平级
    ]
    assert _gov(eps) == 1


def test_c6_special_does_not_apply_to_secretary_label():
    # 升迁_省委书记: 书记→他省书记 = 平调 (C6 特例只对省长标签)
    eps = [
        ep(1, "1998.01", "2003.01", "省委书记", "中共浙江省委", rank="正部级"),
        ep(2, "2003.01", "2008.01", "省委书记", "中共江苏省委", prov="江苏",
           rank="正部级"),
    ]
    assert _sec(eps) == 0


# ── C7: 本省提拔, 前组多兼职 (any 在本省 → 1) ─────────────────────────────────

def test_c7_local_promotion_prev_group_any_in_province():
    eps = [
        ep(1, "1995.01", "1998.01", "副省长", "浙江省人民政府", rank="副部级"),
        ep(1, "1995.01", "1998.01", "省委常委", "中共浙江省委", rank="副部级"),
        ep(2, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
    ]
    groups = build_tenure_groups(eps, TARGET)
    assert compute_local_promotion(groups) == 1


def test_c7_local_promotion_prev_group_central_is_zero():
    eps = [
        ep(1, "1995.01", "1998.01", "国务院某部副部长", "国务院某部",
           prov="", rank="副部级"),                           # 任前在中央
        ep(2, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
    ]
    groups = build_tenure_groups(eps, TARGET)
    assert compute_local_promotion(groups) == 0


def test_local_promotion_no_prev_group_is_unknown():
    eps = [ep(1, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级")]
    groups = build_tenure_groups(eps, TARGET)
    assert compute_local_promotion(groups) == -1


# ── C8: 跨行同期兼任 (source_line 不同, 时间重叠) → 默认不合并 (已知局限) ──────

def test_c8_cross_line_concurrency_not_merged():
    eps = [
        ep(1, "2000.01", "2005.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(2, "2001.01", "2004.01", "省委副书记", "中共浙江省委", rank="副部级"),
    ]
    groups = build_tenure_groups(eps, TARGET)
    assert len(groups) == 2                                   # 不同 source_line → 两组


# ── C9: 时间解析鲁棒 (至今 / YYYY.00) ────────────────────────────────────────

def test_c9_ongoing_tenure_is_incumbent():
    eps = [ep(1, "1998.03", "至今", "省长", "浙江省人民政府", rank="正部级")]
    assert _gov(eps) == -1                                    # 在任


def test_c9_partial_month_start_parses():
    eps = [
        ep(1, "1998.00", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(2, "2003.01", "2008.01", "国务院副总理", "国务院", prov="", rank="副国级"),
    ]
    assert _gov(eps) == 1


# ── C10: 「下一任期」= 起始 ≥ 主官离任 的第一个组 (先兼任后专任) ───────────────

def test_c10_next_tenure_boundary_first_after_departure():
    eps = [
        ep(1, "2000.01", "2005.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(2, "2003.01", "2005.01", "省委副书记", "中共浙江省委",
           rank="副部级"),                                    # 兼任, 起始 < 离任 → 跳
        ep(3, "2005.01", "2010.01", "国务院副总理", "国务院", prov="", rank="副国级"),
    ]
    assert _gov(eps) == 1


# ── 本省学习 ─────────────────────────────────────────────────────────────────

def test_local_study_in_province_before_office():
    eps = [
        ep(1, "1990.01", "1992.01", "研究生", "浙江大学", rank="无",
           flag="学习进修"),
        ep(2, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
    ]
    groups = build_tenure_groups(eps, TARGET)
    assert compute_local_study(eps, groups, TARGET) == 1


def test_local_study_other_province_is_zero():
    eps = [
        ep(1, "1990.01", "1992.01", "研究生", "北京大学", prov="北京",
           rank="无", flag="学习进修"),
        ep(2, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
    ]
    groups = build_tenure_groups(eps, TARGET)
    assert compute_local_study(eps, groups, TARGET) == 0


def test_local_study_after_office_does_not_count():
    eps = [
        ep(1, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(2, "2004.01", "2005.01", "研究生", "浙江大学", rank="无",
           flag="学习进修"),                                  # 任后学习, 不算
    ]
    groups = build_tenure_groups(eps, TARGET)
    assert compute_local_study(eps, groups, TARGET) == 0


# ── Public entry point ───────────────────────────────────────────────────────

def test_derive_person_labels_integration():
    eps = [
        ep(1, "1990.01", "1992.01", "研究生", "浙江大学", rank="无", flag="学习进修"),
        ep(2, "1995.01", "1998.01", "副省长", "浙江省人民政府", rank="副部级"),
        ep(3, "1998.01", "2003.01", "省长", "浙江省人民政府", rank="正部级"),
        ep(4, "2003.01", "2008.01", "省委书记", "中共浙江省委", rank="正部级"),
    ]
    labels = derive_person_labels(eps, TARGET)
    assert labels == {
        "升迁_省长": 1,        # 省长→省委书记 (C6)
        "升迁_省委书记": 0,     # 末段书记 2003-2008 有终止、无下一组、无离任去向 → 保守计 0
        "本省提拔": 1,         # 任前副省长在浙江
        "本省学习": 1,         # 浙大研究生
    }


# Allow running without pytest installed.
if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
