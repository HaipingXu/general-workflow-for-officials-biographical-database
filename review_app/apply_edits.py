# -*- coding: utf-8 -*-
"""
管理员手动执行：把 Supabase `review_edits` 里审完的改动叠加到原 Excel，
生成「清洗后」新版本到 output/cleaned/，**不覆盖原始 Excel**。

凭据来源（任一）：
  - 环境变量 SUPABASE_URL / SUPABASE_KEY
  - .streamlit/secrets.toml 里的 [supabase] url/key（与网站同一份）

用法：
  uv run python review_app/apply_edits.py --dry-run     # 只打印将应用的改动，不写文件
  uv run python review_app/apply_edits.py               # 应用全部 → output/cleaned/
  uv run python review_app/apply_edits.py --source 省长  # 只处理某库
  uv run python review_app/apply_edits.py --doubts       # 额外导出「依然存疑」清单

约定（与 app 一致）：
  - review_edits.step 形如「省长::step4 标签」，先按 :: 拆出数据源选对应 Excel。
  - field=="备注" 的行 → 追加进对应行的「备注栏」，前缀标 step 来源。
  - episode_no 为空（step4 官员级）→ 该字段/备注按 (省份,姓名) 应用到整人首行；
    episode_no 非空（step1-3 经历级）→ 按 (省份,姓名,经历序号) 定位该经历行。
  - 同一格多次改动按时间 ts 升序应用，后者覆盖前者。
"""
from __future__ import annotations

import os
import sys
import argparse
import datetime as dt

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
SOURCES = {
    "省长": os.path.join(PROJECT, "output", "全省_省长数据库.xlsx"),
    "省委书记": os.path.join(PROJECT, "output", "全省_省委书记数据库.xlsx"),
}
OUT_DIR = os.path.join(PROJECT, "output", "cleaned")
NOTE_COL = "备注栏"


def load_creds():
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if url and key:
        return url, key
    p = os.path.join(PROJECT, ".streamlit", "secrets.toml")
    if os.path.exists(p):
        import tomllib
        with open(p, "rb") as f:
            sb = tomllib.load(f).get("supabase", {})
        return sb.get("url"), sb.get("key")
    return None, None


def fetch_edits(url, key) -> pd.DataFrame:
    from supabase import create_client
    client = create_client(url, key)
    res = client.table("review_edits").select("*").execute()
    return pd.DataFrame(res.data or [])


def parse_step(s):
    s = str(s)
    return tuple(s.split("::", 1)) if "::" in s else (None, s)


def norm_epi(x) -> str:
    s = str(x).strip()
    return s[:-2] if s.endswith(".0") else s


def apply_source(source: str, xlsx: str, sub: pd.DataFrame, dry: bool):
    df = pd.read_excel(xlsx, sheet_name=0, dtype=object)
    if NOTE_COL not in df.columns:
        df[NOTE_COL] = ""
    prov_s = df["省份"].astype(str)
    name_s = df["姓名"].astype(str)
    epi_s = df["经历序号"].map(norm_epi)

    n_field, n_note, n_miss = 0, 0, 0
    for _, e in sub.sort_values("ts").iterrows():
        prov, name = str(e["province"]), str(e["name"])
        epi = norm_epi(e["episode_no"]) if e.get("episode_no") not in (None, "") else ""
        field = str(e["field"])
        newv = "" if pd.isna(e["new_value"]) else str(e["new_value"])
        _, stp = parse_step(e["step"])

        mask = (prov_s == prov) & (name_s == name)
        if epi:
            mask = mask & (epi_s == epi)
        idx = list(df.index[mask])
        if not idx:
            print(f"  ⚠ 未匹配: {source} {name}({prov}) 序号{epi or '-'} 字段{field}")
            n_miss += 1
            continue

        if field == NOTE_COL or field == "备注":
            tgt = idx[0]                      # 备注只落首行，避免整人重复
            prev = df.at[tgt, NOTE_COL]
            prev = "" if pd.isna(prev) else str(prev)
            df.at[tgt, NOTE_COL] = (prev + " " if prev else "") + f"[{stp}]{newv}"
            n_note += 1
        else:
            df.loc[idx, field] = newv         # step4(epi空)→整人所有行；step1-3→该经历行
            n_field += 1
            print(f"  ✓ {source} {name}({prov}) 序号{epi or '整人'} {field}={newv!r}")

    print(f"[{source}] 字段改动 {n_field}，备注 {n_note}，未匹配 {n_miss}")
    if dry:
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M")
    out = os.path.join(OUT_DIR, f"{source}_cleaned_{ts}.xlsx")
    df.to_excel(out, index=False)
    print(f"[{source}] → 写出 {out}")


def export_doubts(edits: pd.DataFrame):
    d = edits[edits["new_value"].astype(str).str.contains("依然存疑", na=False)]
    if d.empty:
        print("（无『依然存疑』记录）")
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"doubts_{dt.datetime.now():%Y%m%d_%H%M}.xlsx")
    d.to_excel(out, index=False)
    print(f"依然存疑 {len(d)} 条 → {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=list(SOURCES), help="只处理某库")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    ap.add_argument("--doubts", action="store_true", help="额外导出依然存疑清单")
    args = ap.parse_args()

    url, key = load_creds()
    if not (url and key):
        sys.exit("缺少 Supabase 凭据：设 SUPABASE_URL/SUPABASE_KEY 或填 .streamlit/secrets.toml")

    edits = fetch_edits(url, key)
    print(f"Supabase review_edits 共 {len(edits)} 条")
    if edits.empty:
        return
    edits["_src"] = edits["step"].map(lambda s: parse_step(s)[0])

    for source, xlsx in SOURCES.items():
        if args.source and source != args.source:
            continue
        sub = edits[edits["_src"] == source]
        if sub.empty:
            continue
        if not os.path.exists(xlsx):
            print(f"  ⚠ 找不到 Excel: {xlsx}")
            continue
        apply_source(source, xlsx, sub, args.dry_run)

    if args.doubts:
        export_doubts(edits)


if __name__ == "__main__":
    main()
