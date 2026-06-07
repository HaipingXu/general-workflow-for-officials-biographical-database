# -*- coding: utf-8 -*-
"""
存储抽象层：claims / review_edits / review_progress

两套后端，按是否配置 Supabase 自动切换：
- 配了 st.secrets["supabase"]["url"] → Supabase（云端，跨机器共享，上线用）
- 否则 → 本地 CSV（review_app/edits/，本地开发/单机用）

app.py 只调用这里的原子操作，与后端无关。所有列名用英文，便于落 Postgres。
"""
from __future__ import annotations

import os
import datetime as dt

import pandas as pd

try:
    import streamlit as st
except Exception:  # 允许在无 streamlit 环境下做单元测试
    st = None

HERE = os.path.dirname(os.path.abspath(__file__))
EDITS_DIR = os.path.join(HERE, "edits")
os.makedirs(EDITS_DIR, exist_ok=True)

CLAIMS_CSV = os.path.join(EDITS_DIR, "claims.csv")
EDITS_CSV = os.path.join(EDITS_DIR, "review_edits.csv")
PROGRESS_CSV = os.path.join(EDITS_DIR, "review_progress.csv")

CLAIM_COLS = ["step", "province", "name", "reviewer", "claimed_at", "heartbeat", "status"]
EDIT_COLS = ["ts", "reviewer", "rowid", "province", "name", "episode_no",
             "step", "field", "old_value", "new_value", "note"]
PROGRESS_COLS = ["ts", "reviewer", "rowid", "step", "action"]

TABLE = {"claims": "claims", "edits": "review_edits", "progress": "review_progress"}


# ------------------------------------------------ 后端选择
def _secrets() -> dict:
    if st is None:
        return {}
    try:
        return dict(st.secrets)
    except Exception:
        return {}


def _sb_client():
    """有 secrets 则返回 Supabase client，否则 None。结果缓存在模块级。"""
    if getattr(_sb_client, "_cached", "x") != "x":
        return _sb_client._cached
    client = None
    s = _secrets()
    sb = s.get("supabase") if isinstance(s, dict) else None
    if sb and sb.get("url") and sb.get("key"):
        from supabase import create_client
        client = create_client(sb["url"], sb["key"])
    _sb_client._cached = client
    return client


def backend_name() -> str:
    return "Supabase" if _sb_client() is not None else "本地CSV"


# ------------------------------------------------ CSV 原子操作
def _csv_path(kind: str) -> str:
    return {"claims": CLAIMS_CSV, "edits": EDITS_CSV, "progress": PROGRESS_CSV}[kind]


def _csv_cols(kind: str) -> list[str]:
    return {"claims": CLAIM_COLS, "edits": EDIT_COLS, "progress": PROGRESS_COLS}[kind]


def _csv_load(kind: str) -> pd.DataFrame:
    p = _csv_path(kind)
    if os.path.exists(p):
        return pd.read_csv(p, dtype=object).fillna("")
    return pd.DataFrame(columns=_csv_cols(kind))


def _csv_append(kind: str, row: dict):
    p = _csv_path(kind)
    pd.DataFrame([row]).to_csv(p, mode="a", header=not os.path.exists(p), index=False)


def _csv_update(kind: str, match: dict, fields: dict):
    df = _csv_load(kind)
    if df.empty:
        return
    mask = pd.Series(True, index=df.index)
    for k, v in match.items():
        mask &= df[k].astype(str) == str(v)
    for k, v in fields.items():
        df.loc[mask, k] = v
    df.to_csv(_csv_path(kind), index=False)


def _csv_delete(kind: str, match: dict):
    df = _csv_load(kind)
    if df.empty:
        return
    mask = pd.Series(True, index=df.index)
    for k, v in match.items():
        mask &= df[k].astype(str) == str(v)
    df[~mask].to_csv(_csv_path(kind), index=False)


# ------------------------------------------------ 统一接口
def load(kind: str) -> pd.DataFrame:
    c = _sb_client()
    if c is None:
        return _csv_load(kind)
    res = c.table(TABLE[kind]).select("*").execute()
    df = pd.DataFrame(res.data or [])
    return df if not df.empty else pd.DataFrame(columns=_csv_cols(kind))


def append(kind: str, row: dict):
    c = _sb_client()
    if c is None:
        _csv_append(kind, row)
    else:
        c.table(TABLE[kind]).insert(row).execute()


def update(kind: str, match: dict, fields: dict):
    c = _sb_client()
    if c is None:
        _csv_update(kind, match, fields)
    else:
        q = c.table(TABLE[kind]).update(fields)
        for k, v in match.items():
            q = q.eq(k, v)
        q.execute()


def delete(kind: str, match: dict):
    c = _sb_client()
    if c is None:
        _csv_delete(kind, match)
    else:
        q = c.table(TABLE[kind]).delete()
        for k, v in match.items():
            q = q.eq(k, v)
        q.execute()


def now_str() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
