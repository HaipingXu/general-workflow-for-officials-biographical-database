"""
Phase 5 (v2): Excel Export

Produces three output files:
  output/{city}_officials.xlsx    — all rows for the city (A→AD, 29 columns)
  output/{city}_governors.xlsx    — all rows for people who ever served as governor
  output/{city}_secretaries.xlsx  — all rows for people who ever served as prov secretary

Additionally the battle.xlsx produced by judge.py is kept in output/.

Column order follows config.COLUMNS exactly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from config import COLUMNS, DATA_DIR, LOGS_DIR, OUTPUT_DIR, PROVINCE_NAMES, STUDY_FLAG

# ── Style constants ────────────────────────────────────────────────────────────

FILL_HEADER    = PatternFill(fill_type="solid", fgColor="2F5496")   # dark blue
FILL_MAYOR     = PatternFill(fill_type="solid", fgColor="E2EFDA")   # light green
FILL_SECRETARY = PatternFill(fill_type="solid", fgColor="DAEEF3")   # light blue
FILL_ALT       = PatternFill(fill_type="solid", fgColor="F9F9F9")   # off-white alt row
HEADER_FONT    = Font(bold=True, color="FFFFFF", size=10)
NORMAL_FONT    = Font(size=10)
CENTER_ALIGN   = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT_ALIGN     = Alignment(horizontal="left",   vertical="center", wrap_text=True)

FILL_RED_CONF    = PatternFill(fill_type="solid", fgColor="FFCCCC")   # red for low confidence
FILL_RED_BLOCKED = PatternFill(fill_type="solid", fgColor="FF4444")   # deep red for blocked judge

THIN_BORDER = Border(
    left=Side(style="thin", color="BFBFBF"),
    right=Side(style="thin", color="BFBFBF"),
    top=Side(style="thin", color="BFBFBF"),
    bottom=Side(style="thin", color="BFBFBF"),
)

# Columns that look better centred
CENTRE_COLS = {
    "年份", "出生年份", "少数民族", "女性", "全日制本科",
    "升迁_省长", "升迁_省委书记", "本省提拔", "本省学习",
    "最终行政级别",
    "经历序号", "该条行政级别", "中央/地方", "是否落马",
}

# Fixed column widths (characters)
COL_WIDTHS: dict[str, int] = {
    "年份": 8, "省份": 10, "姓名": 8,
    "出生年份": 10, "籍贯": 12, "籍贯（市）": 14,
    "少数民族": 10, "女性": 6,
    "全日制本科": 10, "升迁_省长": 12, "升迁_省委书记": 14,
    "本省提拔": 10, "本省学习": 10, "最终行政级别": 14,
    "经历序号": 8, "起始时间": 10, "终止时间": 10,
    "组织标签": 18, "标志位": 20, "该条行政级别": 14,
    "供职单位": 30, "职务": 22,
    "原文引用": 40,
    "任职地（省）": 16, "任职地（市）": 14, "中央/地方": 10,
    "是否落马": 10, "落马原因": 30, "备注栏": 28,
    # v9 per-step judge confidence columns
    "judge1con": 30, "judge2con": 30, "judge3con": 30, "judge4con": 30,
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _drop_study_rows(rows: list[dict]) -> tuple[list[dict], int]:
    """Optional export-time filter: remove 脱产学习/进修 episodes (标志位 == STUDY_FLAG).

    After dropping, 经历序号 is renumbered contiguously *per person* (姓名) in the
    original order, so the exported sheet has no gaps. Returns (kept_rows, n_dropped).
    Input rows are not mutated.
    """
    kept: list[dict] = []
    n_dropped = 0
    per_person_idx: dict[str, int] = {}
    for r in rows:
        if r.get("标志位") == STUDY_FLAG:
            n_dropped += 1
            continue
        r = dict(r)  # copy before renumbering
        if "经历序号" in r:
            name = r.get("姓名", "")
            per_person_idx[name] = per_person_idx.get(name, 0) + 1
            r["经历序号"] = per_person_idx[name]
        kept.append(r)
    return kept, n_dropped


def _rows_to_df(rows: list[dict]) -> pd.DataFrame:
    """Convert list of row dicts → DataFrame with COLUMNS column order."""
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(rows)
    # Ensure all COLUMNS present (fill missing with "")
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[COLUMNS]


def _apply_styles(
    ws,
    df: pd.DataFrame,
    highlight_col: str | None = None,
    highlight_vals: set | None = None,
    highlight_fill: "PatternFill | None" = None,
):
    """Apply header styles, column widths, alternating rows, and optional highlight."""
    headers = list(df.columns)
    n_rows = len(df)

    # Header row
    for col_idx, col_name in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill  = FILL_HEADER
        cell.font  = HEADER_FONT
        cell.alignment = CENTER_ALIGN
        cell.border = THIN_BORDER
        # Column width
        w = COL_WIDTHS.get(col_name, 14)
        ws.column_dimensions[get_column_letter(col_idx)].width = w

    # Row height for header
    ws.row_dimensions[1].height = 20

    # Determine highlight fill for each data row
    highlight_col_idx = (headers.index(highlight_col) + 1) if highlight_col and highlight_col in headers else None

    for row_idx in range(2, n_rows + 2):
        # Base alternating fill
        base_fill = FILL_ALT if row_idx % 2 == 0 else None

        # Check if this row should be highlighted
        is_highlighted = False
        if highlight_col_idx:
            val = ws.cell(row=row_idx, column=highlight_col_idx).value
            if highlight_vals is not None:
                is_highlighted = val in highlight_vals
            else:
                is_highlighted = bool(val)

        for col_idx, col_name in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font   = NORMAL_FONT
            cell.border = THIN_BORDER

            if col_name in CENTRE_COLS:
                cell.alignment = CENTER_ALIGN
            else:
                cell.alignment = LEFT_ALIGN

            if is_highlighted and highlight_fill:
                cell.fill = highlight_fill
            elif base_fill:
                cell.fill = base_fill

        ws.row_dimensions[row_idx].height = 15

    # Highlight judgeNcon cells: deep red for blocked judge,
    # light red for low confidence (<85, v9 threshold)
    import re as _re
    cols_to_highlight = [
        c for c in ["judge1con", "judge2con", "judge3con", "judge4con"]
        if c in headers
    ]
    for col_name in cols_to_highlight:
        col_idx = headers.index(col_name) + 1
        for row_idx in range(2, n_rows + 2):
            cell = ws.cell(row=row_idx, column=col_idx)
            val = str(cell.value or "")
            if "[裁判被拦截]" in val:
                cell.fill = FILL_RED_BLOCKED
            elif "[信心:" in val:
                for m in _re.finditer(r'\[信心:(\d+)\]', val):
                    if int(m.group(1)) < 85:
                        cell.fill = FILL_RED_CONF
                        break

    ws.freeze_panes = "E2"   # freeze person-level cols + header


def write_excel(
    df: pd.DataFrame,
    path: Path,
    sheet_name: str = "数据",
    highlight_col: str | None = None,
    highlight_vals: set | None = None,
    highlight_fill: "PatternFill | None" = None,
):
    """Write a single-sheet Excel file with full styling."""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        ws = writer.sheets[sheet_name]
        _apply_styles(ws, df, highlight_col=highlight_col,
                      highlight_vals=highlight_vals, highlight_fill=highlight_fill)
    print(f"  ✓ 已保存: {path.name}  ({len(df)} 行)")


# ── Main export ────────────────────────────────────────────────────────────────

def _start_year(s: str) -> int | None:
    """Extract 4-digit start year from '1985.07' / '1985' style string."""
    import re
    m = re.match(r"\s*(\d{4})", str(s or ""))
    return int(m.group(1)) if m else None


def _load_names_from_txt(
    txt_path: Path,
) -> tuple[set[str], set[str], dict[str, int], dict[str, int]]:
    """
    Parse an officials.txt file.

    Returns (governor_names, secretary_names, gov_years, sec_years) where
    *_years map name → 上任年份 (earliest start year in that role segment).
    名单是年份的权威来源（data/1990/{省}_officials.txt）。
    """
    from code_scrape.input_parser_province import parse_province_officials_txt

    # Derive province short name from filename (e.g. "浙江_officials.txt" → "浙江")
    province_short = txt_path.stem.replace("_officials", "")
    parsed = parse_province_officials_txt(province_short, data_dir=txt_path.parent)

    governor_names = {o["name"] for o in parsed.get("governors", [])}
    secretary_names = {o["name"] for o in parsed.get("secretaries", [])}

    def _year_map(items: list[dict]) -> dict[str, int]:
        out: dict[str, int] = {}
        for o in items:
            y = _start_year(o.get("start", ""))
            if y is None:
                continue
            # 同一人多段任期取最早上任年
            if o["name"] not in out or y < out[o["name"]]:
                out[o["name"]] = y
        return out

    gov_years = _year_map(parsed.get("governors", []))
    sec_years = _year_map(parsed.get("secretaries", []))
    return governor_names, secretary_names, gov_years, sec_years


def run_export(
    province: str,
    final_rows_path: Path | None = None,
    output_dir: Path | None = None,
    officials_txt_path: Path | None = None,
    drop_study: bool = False,
) -> dict[str, Path]:
    """
    Load final_rows.json, write three Excel files.

    Args:
        officials_txt_path: Path to the officials.txt name list (e.g.
            data/1990/浙江_officials.txt). When provided, governor and
            secretary sheets are filtered by the names listed there.
            When None, falls back to inferring names from the 标志位 column.
        drop_study: When True, exclude 脱产学习/进修 episodes (标志位 == STUDY_FLAG)
            from ALL exported sheets and renumber 经历序号 per person. Default
            False (study episodes are kept — this is an opt-in feature).

    Returns dict of {label: Path}.
    """
    print(f"\n=== Phase 5 (v2): Excel 导出 ===")

    if final_rows_path is None:
        final_rows_path = LOGS_DIR / "final_rows.json"
    if output_dir is None:
        output_dir = OUTPUT_DIR

    output_dir.mkdir(parents=True, exist_ok=True)

    if not final_rows_path.exists():
        print(f"  ✗ final_rows.json 不存在: {final_rows_path}")
        return {}

    rows: list[dict] = json.loads(final_rows_path.read_text(encoding="utf-8"))
    if drop_study:
        rows, n_dropped = _drop_study_rows(rows)
        print(f"  [drop_study] 已删除学习/进修经历 {n_dropped} 行（标志位='{STUDY_FLAG}'），经历序号已按人重排")
    df_all = _rows_to_df(rows)

    # Governor / secretary highlight tags (for row colouring only)
    GOV_TAGS = {"省长", "省委副书记（省长）"}
    SEC_TAGS = {"省委书记"}

    # --- Determine governor / secretary name sets + 上任年份(名单权威) ---
    gov_years: dict[str, int] = {}
    sec_years: dict[str, int] = {}
    if officials_txt_path is not None and officials_txt_path.exists():
        governor_names, secretary_names, gov_years, sec_years = _load_names_from_txt(officials_txt_path)
        print(f"  从名单文件读取: 省长 {len(governor_names)} 人, 省委书记 {len(secretary_names)} 人")
    else:
        # Fallback: infer from 标志位 column
        governor_names = set(df_all[df_all["标志位"].isin(GOV_TAGS)]["姓名"].unique())
        secretary_names = set(df_all[df_all["标志位"].isin(SEC_TAGS)]["姓名"].unique())
        if officials_txt_path is not None:
            print(f"  ⚠ 名单文件不存在 ({officials_txt_path}), 回退到标志位推断")

    def _apply_year(df, year_map: dict[str, int]):
        """覆写'年份'列为名单上任年（按姓名）。无映射者保留原值。"""
        if not year_map or df.empty or "年份" not in df.columns:
            return df
        df = df.copy()
        df["年份"] = df.apply(
            lambda r: year_map.get(r["姓名"], r["年份"]), axis=1
        )
        return df

    # --- All officials: 年份取首次主官年(书记/省长名单年较早者) ---
    first_year = dict(gov_years)
    for nm, y in sec_years.items():
        if nm not in first_year or y < first_year[nm]:
            first_year[nm] = y
    df_all_out = _apply_year(df_all, first_year)
    path_all = output_dir / f"{province}_officials.xlsx"
    write_excel(df_all_out, path_all, sheet_name="全部履历")

    # --- Governors: ALL rows for anyone listed as governor; 年份=任省长上任年 ---
    df_mayors = df_all[df_all["姓名"].isin(governor_names)].reset_index(drop=True)
    df_mayors = _apply_year(df_mayors, gov_years)
    path_mayors = output_dir / f"{province}_governors.xlsx"
    write_excel(df_mayors, path_mayors, sheet_name="省长履历",
                highlight_col="标志位", highlight_vals=GOV_TAGS, highlight_fill=FILL_MAYOR)

    # --- Secretaries: ALL rows for anyone listed as secretary; 年份=任书记上任年 ---
    df_secs = df_all[df_all["姓名"].isin(secretary_names)].reset_index(drop=True)
    df_secs = _apply_year(df_secs, sec_years)
    path_secs = output_dir / f"{province}_secretaries.xlsx"
    write_excel(df_secs, path_secs, sheet_name="省委书记履历",
                highlight_col="标志位", highlight_vals=SEC_TAGS, highlight_fill=FILL_SECRETARY)

    print(f"\n  全部: {len(df_all)} 行")
    print(f"  省长: {len(df_mayors)} 行 ({df_mayors['姓名'].nunique() if not df_mayors.empty else 0} 人)")
    print(f"  省委书记: {len(df_secs)} 行 ({df_secs['姓名'].nunique() if not df_secs.empty else 0} 人)")

    return {
        "all":        path_all,
        "mayors":     path_mayors,
        "secretaries": path_secs,
    }
