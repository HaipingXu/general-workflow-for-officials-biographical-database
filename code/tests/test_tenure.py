"""Unit tests for tenure.py — tenure-group rank primitives (兼职 + cummax).

Run: `cd code && uv run python -m pytest tests/test_tenure.py -q`
Also runnable without pytest: `cd code && python3 tests/test_tenure.py`
"""
from tenure import (
    period_sort_key,
    group_ranks_by_source_line,
    highest_rank_per_group,
    ordered_source_lines,
    running_cummax,
    source_line_rank_maps,
    normalise_province,
    normalise_city,
    is_governor_row,
    is_prov_secretary_row,
)


# ── period_sort_key ─────────────────────────────────────────────────────────

def test_period_sort_key_full():
    assert period_sort_key("1998.03") == 199803


def test_period_sort_key_month_unknown():
    assert period_sort_key("1998.00") == 199800


def test_period_sort_key_year_only():
    assert period_sort_key("2003") == 200300


def test_period_sort_key_missing_sorts_last():
    assert period_sort_key("") == 999900
    assert period_sort_key("至今") == 999900       # 至今 only appears in 终止; robustness
    assert period_sort_key("n/a") == 999900


# ── group_ranks_by_source_line ──────────────────────────────────────────────

def test_group_ranks_concurrent_share_source_line():
    # 兼职: two episodes share a source_line → grouped together
    eps = [
        {"source_line": 5, "行政级别": "正厅级"},
        {"source_line": 5, "行政级别": "副部级"},
        {"source_line": 6, "行政级别": "正处级"},
    ]
    assert group_ranks_by_source_line(eps) == {5: ["正厅级", "副部级"], 6: ["正处级"]}


def test_group_ranks_falls_back_to_rank_map_by_position():
    eps = [
        {"source_line": 1},                       # no 行政级别 → rank_map[1]
        {"source_line": 2, "行政级别": "正处级"},
    ]
    assert group_ranks_by_source_line(eps, {1: "副处级"}) == {1: ["副处级"], 2: ["正处级"]}


def test_group_ranks_missing_source_line_uses_position():
    eps = [{"行政级别": "正科级"}, {"行政级别": "副处级"}]
    assert group_ranks_by_source_line(eps) == {1: ["正科级"], 2: ["副处级"]}


# ── highest_rank_per_group ──────────────────────────────────────────────────

def test_highest_rank_per_group_takes_highest():
    groups = {5: ["正厅级", "副部级"], 6: ["无", "正处级"]}
    assert highest_rank_per_group(groups) == {5: "副部级", 6: "正处级"}


def test_highest_rank_per_group_no_valid_rank_is_empty():
    # study-only group ("无" is not in RANK_LEVELS) → ""
    assert highest_rank_per_group({7: ["无"]}) == {7: ""}


# ── ordered_source_lines ────────────────────────────────────────────────────

def test_ordered_source_lines_sorts_by_time_and_dedups():
    eps = [
        {"source_line": 6, "起始时间": "2003.01"},
        {"source_line": 6, "起始时间": "2003.01"},   # 兼职 dup line
        {"source_line": 5, "起始时间": "1998.03"},
    ]
    slh = {5: "正厅级", 6: "副部级"}
    assert ordered_source_lines(eps, slh) == [(5, "正厅级"), (6, "副部级")]


# ── running_cummax ──────────────────────────────────────────────────────────

def test_running_cummax_monotonic_through_study():
    # study episode has 无 rank → cummax must NOT drop
    ordered = [(1, "正处级"), (2, "正厅级"), (3, "无")]
    assert running_cummax(ordered) == {1: "正处级", 2: "正厅级", 3: "正厅级"}


def test_running_cummax_first_empty_rank():
    # first group rank "" is used as-is (best is falsy) then real rank takes over
    ordered = [(1, ""), (2, "正处级")]
    assert running_cummax(ordered) == {1: "", 2: "正处级"}


# ── source_line_rank_maps (integration / behaviour preservation) ────────────

def test_source_line_rank_maps_integration():
    # Realistic: 兼职 (sl5 省长+省委副书记) then 进修 (sl7 无) — input out of order
    eps = [
        {"source_line": 7, "起始时间": "2001.09", "行政级别": "无"},       # 进修
        {"source_line": 5, "起始时间": "1998.03", "行政级别": "副部级"},    # 省长
        {"source_line": 5, "起始时间": "1998.03", "行政级别": "正厅级"},    # 同期兼职
    ]
    sl_highest, sl_cummax = source_line_rank_maps(eps)
    assert sl_highest == {7: "", 5: "副部级"}          # study group → ""; 兼职 就高 → 副部级
    # chronological sl5(1998)→副部级, sl7(2001, 无)→cummax 保持 副部级（不降）
    assert sl_cummax == {5: "副部级", 7: "副部级"}


# ── place normalisation + office predicates (moved from postprocess) ─────────

def test_normalise_province_adds_suffix():
    assert normalise_province("浙江") == "浙江省"
    assert normalise_province("浙江省") == "浙江省"
    assert normalise_province("") == ""


def test_normalise_city_keeps_suffix():
    assert normalise_city("杭州市") == "杭州市"
    assert normalise_city("") == ""


def test_is_governor_row_includes_acting():
    # 代省长 counts as 省长 (governor) — C5 prerequisite
    assert is_governor_row("代省长", "浙江省人民政府", "浙江", "浙江") == 1
    assert is_governor_row("省长", "浙江省人民政府", "浙江", "浙江") == 1


def test_is_governor_row_excludes_deputy_and_assistant():
    assert is_governor_row("副省长", "浙江省人民政府", "浙江", "浙江") == 0
    assert is_governor_row("省长助理", "浙江省人民政府", "浙江", "浙江") == 0


def test_is_governor_row_wrong_province():
    assert is_governor_row("省长", "江苏省人民政府", "江苏", "浙江") == 0


def test_is_prov_secretary_row_basic():
    assert is_prov_secretary_row("省委书记", "中共浙江省委", "浙江", "浙江") == 1
    assert is_prov_secretary_row("省委副书记", "中共浙江省委", "浙江", "浙江") == 0


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
