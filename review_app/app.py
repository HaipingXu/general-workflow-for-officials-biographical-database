# -*- coding: utf-8 -*-
"""
省级官员数据库 · 人工清洗工具

工作单元 = 官员（做完一个人再下一个）：静态分配(选省) + 软锁(认领) + 自动分配。
存储后端经 storage.py 抽象：配了 Supabase 用云端共享，否则本地 CSV。

原则：行结构冻结（只改值，不增删行）；原始 Excel 只读；app 只写改动提案，
      不生成新版数据（生成由管理员手动跑 apply 脚本）。

运行
----
    本地:  uv run streamlit run review_app/app.py
    云端:  Streamlit Community Cloud，secrets 配 app_password + supabase
"""
from __future__ import annotations

import os
import re
import html

import pandas as pd
import streamlit as st

import storage  # 同目录

# ---------------------------------------------------------------- 配置
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
OFFICIALS_DIR = os.path.join(PROJECT, "officials")
PROMPTS_DIR = os.path.join(PROJECT, "prompts")

CONF_THRESHOLD = 85
LOCK_TTL_MIN = 15
AUTO_PICK = "（自动：下一个未完成）"

DATA_SOURCES = {
    "省长": os.path.join(PROJECT, "output", "全省_省长数据库.xlsx"),
    "省委书记": os.path.join(PROJECT, "output", "全省_省委书记数据库.xlsx"),
}
STEP_FIELDS: dict[str, list[str]] = {
    "step1 提取": ["起始时间", "终止时间", "供职单位", "职务"],
    "step2 分类": ["组织标签", "标志位", "任职地（省）", "任职地（市）", "中央/地方"],
    "step3 级别": ["该条行政级别"],
    "step4 标签": ["升迁_省长", "升迁_省委书记", "本省提拔", "本省学习", "全日制本科", "是否落马"],
}
# step2/step3 评判某条经历时，在原文下展示该条 step1 结果作为定位参照
STEP1_CONTEXT = ["起始时间", "终止时间", "供职单位", "职务"]
CONTEXT_STEPS = {"step2 分类", "step3 级别"}
STEP_JUDGE = {"step1 提取": "judge1con", "step2 分类": "judge2con",
              "step3 级别": "judge3con", "step4 标签": "judge4con"}
STEP_PROMPT = {
    "step1 提取": ["step1_extraction.md"],
    "step2 分类": ["step2_classify.md"],
    "step3 级别": ["step3_rank.md", "ref_soe_rank.md", "ref_university_rank.md"],
    "step4 标签": ["step4_labeling.md"],
}
TEXT_COL = "原文引用"
FULLTEXT_STEPS = {"step4 标签"}

_CONF_RE = re.compile(r"\[信心[:：]\s*(\d+)\]")
_PROV_SUFFIX = re.compile(r"(省|市|自治区|维吾尔|壮族|回族|特别行政区)")


# ---------------------------------------------------------------- 工具
def parse_min_conf(cell):
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return None
    nums = [int(x) for x in _CONF_RE.findall(str(cell))]
    return min(nums) if nums else None


def _has_judge(v) -> bool:
    """该格是否有裁判记录（有分歧才会有 judgeXcon）。空=无分歧，不进队列。"""
    return v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v).strip() != ""


def disputed_fields(judge_text: str, fields: list[str]) -> set[str]:
    """从裁判理由里识别具体分歧字段（形如 `标志位[信心:92]`）。
    有具名字段 → 只标这些；只有裸 `[信心:NN]`（整行级）→ 整步字段全标。"""
    t = str(judge_text or "")
    spec = set()
    for f in fields:
        core = re.sub(r"（.*?）", "", f)  # 任职地（省）→ 任职地
        if re.search(re.escape(f) + r"\s*\[信心", t) or re.search(re.escape(core) + r"\s*\[信心", t):
            spec.add(f)
    if spec:
        return spec
    return set(fields) if re.search(r"\[信心", t) else set()


def norm_province(p) -> str:
    return _PROV_SUFFIX.sub("", str(p)).strip() if p else ""


@st.cache_data(show_spinner=False)
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=0, dtype=object).reset_index(drop=True)
    df["__rowid__"] = df.index
    return df


@st.cache_data(show_spinner=False)
def load_full_bio(province: str, name: str):
    path = os.path.join(OFFICIALS_DIR, norm_province(province), f"{name}_biography.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return None


@st.cache_data(show_spinner=False)
def load_prompt_files(step: str):
    out = []
    for fn in STEP_PROMPT.get(step, []):
        p = os.path.join(PROMPTS_DIR, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                out.append((fn, f.read()))
    return out


def _is_active(hb: str) -> bool:
    import datetime as dt
    try:
        return (dt.datetime.now() - dt.datetime.strptime(str(hb), "%Y-%m-%d %H:%M:%S")).total_seconds() < LOCK_TTL_MIN * 60
    except Exception:
        return False


# ----------------------------- claims（基于 storage，列名英文）
def assign_official(reviewer: str, step: str, pool, exclude=None):
    exclude = exclude or set()
    claims = storage.load("claims")
    now = storage.now_str()
    sub = claims[claims["step"] == step] if not claims.empty else claims

    mine = sub[(sub["reviewer"] == reviewer) & (sub["status"] == "in_progress")] if not sub.empty else sub
    if not mine.empty:
        r = mine.iloc[0]
        if (str(r["province"]), str(r["name"])) not in exclude:
            storage.update("claims", {"step": step, "province": r["province"], "name": r["name"]},
                           {"heartbeat": now})
            return (r["province"], r["name"])

    done, busy = set(), set()
    if not sub.empty:
        for _, r in sub.iterrows():
            key = (r["province"], r["name"])
            if r["status"] == "done":
                done.add(key)
            elif r["status"] == "in_progress" and r["reviewer"] != reviewer and _is_active(r["heartbeat"]):
                busy.add(key)

    for prov, name in pool:
        if (prov, name) in done or (prov, name) in busy or (prov, name) in exclude:
            continue
        storage.append("claims", {"step": step, "province": prov, "name": name,
                                   "reviewer": reviewer, "claimed_at": now,
                                   "heartbeat": now, "status": "in_progress"})
        return (prov, name)
    return None


def heartbeat(reviewer, step, prov, name):
    storage.update("claims", {"step": step, "province": prov, "name": name, "reviewer": reviewer},
                   {"heartbeat": storage.now_str()})


def set_status(reviewer, step, prov, name, status):
    match = {"step": step, "province": prov, "name": name, "reviewer": reviewer}
    if status == "release":
        storage.delete("claims", match)
    else:
        storage.update("claims", match, {"status": status, "heartbeat": storage.now_str()})


def compute_status(step: str, reviewer: str):
    """当前步骤下每位官员的状态：返回 (done, locked, mine)。
    done/locked: {(省,名): reviewer}；mine: set[(省,名)]。done 优先于锁定。"""
    claims = storage.load("claims")
    done, locked, mine = {}, {}, set()
    if not claims.empty:
        sub = claims[claims["step"] == step]
        for _, r in sub.iterrows():
            key = (str(r["province"]), str(r["name"]))
            if r["status"] == "done":
                done[key] = str(r["reviewer"])
            elif r["status"] == "in_progress" and _is_active(r["heartbeat"]):
                if str(r["reviewer"]) == reviewer:
                    mine.add(key)
                else:
                    locked[key] = str(r["reviewer"])
    return done, locked, mine


def claim_specific(reviewer, step, prov, name):
    """手动选人认领：先释放我在本步骤的其它进行中锁（避免悬挂），再认领指定官员。"""
    claims = storage.load("claims")
    now = storage.now_str()
    if not claims.empty:
        mineip = claims[(claims["step"] == step) & (claims["reviewer"] == reviewer)
                        & (claims["status"] == "in_progress")]
        for _, r in mineip.iterrows():
            if (str(r["province"]), str(r["name"])) != (str(prov), str(name)):
                storage.delete("claims", {"step": step, "province": r["province"],
                                          "name": r["name"], "reviewer": reviewer})
    exists = False
    if not claims.empty:
        m = ((claims["step"] == step) & (claims["province"].astype(str) == str(prov))
             & (claims["name"].astype(str) == str(name)))
        exists = bool(m.any())
    if exists:
        storage.update("claims", {"step": step, "province": prov, "name": name},
                       {"reviewer": reviewer, "status": "in_progress", "heartbeat": now})
    else:
        storage.append("claims", {"step": step, "province": prov, "name": name,
                                  "reviewer": reviewer, "claimed_at": now,
                                  "heartbeat": now, "status": "in_progress"})


# ---------------------------------------------------------------- 登录
def check_password() -> bool:
    try:
        pw = st.secrets.get("app_password")
    except Exception:
        pw = None
    if not pw:               # 本地无密码 → 放行
        return True
    if st.session_state.get("auth_ok"):
        return True
    st.title("请输入团队访问密码")
    with st.form("login"):
        inp = st.text_input("密码", type="password")
        if st.form_submit_button("进入"):
            if inp == pw:
                st.session_state.auth_ok = True
                st.rerun()
            else:
                st.error("密码错误")
    return False


# ---------------------------------------------------------------- 页面
st.set_page_config(page_title="官员库人工清洗", layout="wide")

# ---------------------------------------------------------------- 视觉风格
# 全站宋体 + 绛红强调，去阴影/弱边框/克制色块（简约大气）。配色基线在 .streamlit/config.toml [theme]。
_SONG = ('"Songti SC","宋体","SimSun","STSong",'
         '"Source Han Serif SC","Noto Serif CJK SC",serif')
st.markdown(f"""
<style>
/* ===== 全站宋体（务必排除 Material 图标字体，否则箭头/对勾变方框）===== */
html, body, .stApp, [class*="st-"], [data-baseweb],
h1,h2,h3,h4,h5,h6, p, span, div, label, li, a, td, th, caption,
input, textarea, select, button,
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"] p {{
  font-family: {_SONG} !important;
}}
[data-testid="stIconMaterial"], .material-icons,
.material-symbols-rounded, .material-symbols-outlined, span[translate="no"] {{
  font-family: "Material Symbols Rounded","Material Icons" !important;
}}

/* ===== 去阴影、收圆角，整体克制 ===== */
*, *::before, *::after {{ box-shadow: none !important; }}

/* ===== 强调绛红：自管变量，暗色(系统)下提亮——Streamlit 不暴露主题变量，故自定义 ===== */
:root {{ --accent: #8c1f28; }}
@media (prefers-color-scheme: dark) {{ :root {{ --accent: #cf5a63; }} }}

/* ===== 标题：放字距，serif 更舒展大气（颜色继承主题，明暗自适应）===== */
h1,h2,h3 {{ letter-spacing: .03em; font-weight: 600; }}
h1 {{ font-size: 1.6rem !important; }}
h2 {{ font-size: 1.3rem !important; }}
h3 {{ font-size: 1.08rem !important; }}

/* ===== 主区留白更舒展 ===== */
.block-container, [data-testid="stMainBlockContainer"] {{
  padding-top: 2.2rem; max-width: 1120px;
}}

/* 表面色一律用半透明灰：白底偏深、黑底偏浅，明暗自动适配，无需写死两套 */
/* ===== Alert：去浓背景色块，中性底 + 一道细左线 ===== */
[data-testid="stAlertContainer"] {{
  background: rgba(128,128,128,.08) !important;
  border: none !important;
  border-left: 2px solid rgba(128,128,128,.45) !important;
  border-radius: 0 !important;
  padding: .5rem .9rem !important;
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {{
  border-left-color: var(--accent) !important;   /* error 用绛红左线，其余中性 */
}}

/* ===== 原文引用块：中性底 + 绛红细引线（绛红随主题，文字继承主题色）===== */
.yuanwen {{
  background: rgba(128,128,128,.08);
  border-left: 3px solid var(--accent);
  padding: .7rem 1rem; margin: .2rem 0 .6rem; line-height: 1.95;
  white-space: pre-wrap;
}}

/* ===== Expander：中性细边框，无阴影 ===== */
[data-testid="stExpander"] {{
  border: 1px solid rgba(128,128,128,.25) !important; border-radius: 3px !important;
}}
[data-testid="stExpander"] summary {{ font-weight: 600; }}

/* ===== 表格：去重边框，仅中性横线 ===== */
[data-testid="stTable"] table {{ border: none !important; }}
[data-testid="stTable"] th, [data-testid="stTable"] td {{
  border: none !important; border-bottom: 1px solid rgba(128,128,128,.2) !important;
}}

/* ===== 输入框：中性弱描边，focus 绛红 ===== */
.stTextInput input {{
  border: 1px solid rgba(128,128,128,.35) !important; border-radius: 3px !important;
}}
.stTextInput input:focus {{ border-color: var(--accent) !important; }}

/* ===== 按钮：去阴影、方正 ===== */
.stButton button, .stFormSubmitButton button {{ border-radius: 3px !important; }}

/* ===== 强调红（低置信/分歧）：用 primary 绛红，明暗各自取色 ===== */
.accent-red {{ color: var(--accent) !important; font-weight: 700; }}

/* ===== metric：去卡片感，数值缩小（适中，不过小）===== */
[data-testid="stMetric"] {{ background: transparent !important; padding: 0 !important; }}
[data-testid="stMetricValue"] {{ font-weight: 600; font-size: 1.7rem !important; }}

hr {{ border-color: rgba(128,128,128,.2) !important; }}
</style>
""", unsafe_allow_html=True)

if not check_password():
    st.stop()

with st.sidebar:
    st.header("设置")
    src_name = st.selectbox("数据源", list(DATA_SOURCES.keys()), index=0)
    xlsx_path = DATA_SOURCES[src_name]
    reviewer = st.text_input("审核人", value="")
    step = st.selectbox("审核步骤", list(STEP_FIELDS.keys()), index=0)
    threshold = st.number_input("置信度阈值（< 标红）", 0, 100, CONF_THRESHOLD)
    st.caption(f"存储后端：{storage.backend_name()}")

if not os.path.exists(xlsx_path):
    st.error(f"找不到 Excel：{xlsx_path}")
    st.stop()

df = load_data(xlsx_path)
judge_col = STEP_JUDGE[step]
fields = [f for f in STEP_FIELDS[step] if f in df.columns]
# step4：省长库不审「升迁_省委书记」，书记库不审「升迁_省长」
if step in FULLTEXT_STEPS:
    drop_col = "升迁_省委书记" if src_name == "省长" else "升迁_省长"
    fields = [f for f in fields if f != drop_col]
df["__conf__"] = df[judge_col].map(parse_min_conf) if judge_col in df.columns else None
# 待审队列：该步骤有分歧 且 裁判信心 < 阈值（低置信才需人工；高置信分歧裁判可靠，不进）
if judge_col in df.columns:
    review_df = df[df["__conf__"].notna() & (df["__conf__"] < threshold)]
else:
    review_df = df
# 作用域：claims/edits/progress 按「数据源::步骤」隔离，省长库与书记库互不串
sstep = f"{src_name}::{step}"

# 各省人名（按出现顺序去重）+ 当前步骤的完成/锁定状态
prov_to_names: dict[str, list[str]] = {}
for _p, _nm in zip(review_df["省份"].astype(str), review_df["姓名"].astype(str)):
    _lst = prov_to_names.setdefault(_p, [])
    if _nm not in _lst:
        _lst.append(_nm)
done_map, locked_map, mine_set = compute_status(sstep, reviewer)


def _prov_label(p):
    if p == "（全部）":
        return "（全部）"
    names = prov_to_names.get(p, [])
    tot = len(names)
    dn = sum(1 for nm in names if (p, nm) in done_map)
    lk = sum(1 for nm in names if (p, nm) in locked_map)
    tag = "　已完成" if (tot and dn == tot) else ""
    return f"{p}　{dn}/{tot}{tag}" + (f"　锁定{lk}" if lk else "")


def _prov_order(p):
    if p == "（全部）":
        return (-1, "")
    names = prov_to_names.get(p, [])
    tot = len(names)
    dn = sum(1 for nm in names if (p, nm) in done_map)
    return (1 if (tot and dn == tot) else 0, p)   # 未完成省在前


with st.sidebar:
    # 「返回上一条」回退：在 widget 实例化前消费 _goto，设定省/人/落点行
    _goto = st.session_state.pop("_goto", None)
    if _goto:
        st.session_state["prov_sel"] = _goto[0]
        st.session_state["_prev_prov"] = _goto[0]      # 防止下方把人重置成 AUTO
        st.session_state["person_sel"] = _goto[1]
        st.session_state["_pending_pidx"] = _goto[2]
    prov_options = sorted(["（全部）"] + list(prov_to_names.keys()), key=_prov_order)
    prov_filter = st.selectbox("省份（未完成在前）", prov_options,
                               format_func=_prov_label, key="prov_sel")

    # 省份变化 / 完成释放 → 在创建人选择框前重置为「自动」（须早于 widget 实例化）
    if st.session_state.get("_prev_prov") != prov_filter:
        st.session_state["_prev_prov"] = prov_filter
        st.session_state["person_sel"] = AUTO_PICK
    if st.session_state.pop("_reset_person", False):
        st.session_state["person_sel"] = AUTO_PICK

    if prov_filter == "（全部）":
        person_choice = AUTO_PICK
        st.caption("选择具体省份后，可在此指定到人。")
    else:
        _names = prov_to_names.get(prov_filter, [])

        def _porder(nm):
            key = (prov_filter, nm)
            if key in done_map:
                return 3
            if key in locked_map:
                return 2
            if key in mine_set:
                return 1
            return 0

        def _plabel(nm):
            if nm == AUTO_PICK:
                return AUTO_PICK
            key = (prov_filter, nm)
            if key in done_map:
                return f"{nm}　已完成"
            if key in mine_set:
                return f"{nm}　进行中（我）"
            if key in locked_map:
                return f"{nm}　{locked_map[key]} 审核中"
            return nm

        _opts = [AUTO_PICK] + sorted(_names, key=lambda n: (_porder(n), n))
        if st.session_state.get("person_sel") not in _opts:
            st.session_state["person_sel"] = AUTO_PICK
        person_choice = st.selectbox("人（未完成/锁定在前）", _opts,
                                     format_func=_plabel, key="person_sel")
    st.caption("提示：不同人选不同省份即静态分配，互不撞车。")

st.title(f"{src_name}数据库 · {step} 人工清洗")

if not reviewer.strip():
    st.warning("请先在左侧填写「审核人」再开始。")
    st.stop()

flagged = review_df
if prov_filter != "（全部）":
    flagged = flagged[flagged["省份"].astype(str) == prov_filter]

pool = list(dict.fromkeys(zip(flagged["省份"].astype(str), flagged["姓名"].astype(str))))
st.session_state.setdefault("nav_hist", [])
if st.session_state.get("_hist_scope") != sstep:   # 换数据源/步骤 → 清空回退历史
    st.session_state["_hist_scope"] = sstep
    st.session_state["nav_hist"] = []

# 当前官员：手动选人优先，否则自动分配下一个未完成
manual = (prov_filter != "（全部）") and (person_choice != AUTO_PICK)
if manual:
    cur_prov, cur_name = prov_filter, person_choice
else:
    assigned = assign_official(reviewer, sstep, pool)
    if assigned is None:
        _c = storage.load("claims")
        _dn = len(_c[(_c["step"] == sstep) & (_c["status"] == "done")]) if not _c.empty else 0
        a, b, cc = st.columns(3)
        a.metric("待审官员（本筛选）", len(pool))
        b.metric("本步已完成", _dn)
        cc.metric("审核人", reviewer)
        st.success("当前范围：官员都已完成或被他人锁定。可在左侧换省，或指定到具体人。")
        st.stop()
    cur_prov, cur_name = assigned

claims_all = storage.load("claims")
done_cnt = len(claims_all[(claims_all["step"] == sstep) & (claims_all["status"] == "done")]) if not claims_all.empty else 0

c1, c2, c3 = st.columns(3)
c1.metric("待审官员（本筛选）", len(pool))
c2.metric("本步已完成", done_cnt)
c3.metric("审核人", reviewer)

if not claims_all.empty:
    others = claims_all[(claims_all["step"] == sstep) & (claims_all["status"] == "in_progress") & (claims_all["reviewer"] != reviewer)]
    busy_now = [f"{r['name']}({r['province']})·{r['reviewer']}" for _, r in others.iterrows() if _is_active(r["heartbeat"])]
    if busy_now:
        st.caption("其他人进行中：" + "、".join(busy_now))

cur_key = f"{sstep}||{cur_prov}||{cur_name}"
if st.session_state.get("cur_key") != cur_key:
    st.session_state.cur_key = cur_key
    st.session_state.pidx = 0
    if manual:
        claim_specific(reviewer, sstep, cur_prov, cur_name)
heartbeat(reviewer, sstep, cur_prov, cur_name)

# 手动选到他人锁定/已完成的人时给出提示
if manual:
    _mk = (cur_prov, cur_name)
    if _mk in locked_map and locked_map[_mk] != reviewer:
        st.warning(f"{locked_map[_mk]} 正在审核此人（软锁），你已强制认领。")
    elif _mk in done_map:
        st.info("此人此步骤先前已标记完成，你正在重新查看/修改。")

person = flagged[(flagged["省份"].astype(str) == cur_prov) & (flagged["姓名"].astype(str) == cur_name)].reset_index(drop=True)
# 官员级步骤（step4 标签）：判断针对整个人，各经历值相同 → 只留一条，一人判一次
if step in FULLTEXT_STEPS and not person.empty:
    person = person.iloc[[0]].reset_index(drop=True)
n_rows = len(person)
if "_pending_pidx" in st.session_state:   # 回退还原到记录的那一条
    st.session_state.pidx = max(0, min(int(st.session_state.pop("_pending_pidx")), max(n_rows - 1, 0)))

st.markdown(f"## {cur_name} · {cur_prov}　<span style='color:#9a9a9a;font-size:.78em'>（你已认领）</span>", unsafe_allow_html=True)
top_l, top_r = st.columns([3, 1])
with top_r:
    show_prompt = st.toggle("显示规则 prompt", value=st.session_state.get("show_prompt", False), key="show_prompt")
    if st.button("返回上一条", use_container_width=True,
                 disabled=not st.session_state["nav_hist"]):
        st.session_state["_goto"] = st.session_state["nav_hist"].pop()
        st.rerun()
    if st.button("释放，换一个人", use_container_width=True):
        set_status(reviewer, sstep, cur_prov, cur_name, "release")
        st.session_state["_reset_person"] = True   # 下一轮回到「自动」，不再锁回此人
        st.session_state.pidx = 0
        st.rerun()
    if st.button("完成此人，下一位", type="primary", use_container_width=True):
        set_status(reviewer, sstep, cur_prov, cur_name, "done")
        st.session_state["_reset_person"] = True   # 下一轮回到「自动」，自动跳下一位
        st.session_state.pidx = 0
        st.rerun()

main_col, ref_col = (st.columns([2, 1]) if show_prompt else (st.container(), None))

with main_col:
    if n_rows == 0:
        st.info("此官员在当前筛选下没有待审行。点「完成此人」继续。")
    else:
        st.session_state.pidx = max(0, min(st.session_state.get("pidx", 0), n_rows - 1))
        pidx = st.session_state.pidx
        row = person.iloc[pidx]
        rowid = str(row["__rowid__"])
        conf = row["__conf__"]
        if pd.isna(conf):
            conf_html = "—"
        elif int(conf) < threshold:                       # 低于阈值 → 标红
            conf_html = f"<span class='accent-red'>{int(conf)}</span>"
        else:
            conf_html = str(int(conf))
        if step in FULLTEXT_STEPS:
            st.markdown(f"**全人判断（一人一次）　裁判置信度：**{conf_html}", unsafe_allow_html=True)
        else:
            st.markdown(f"**经历 {pidx + 1} / {n_rows}　序号 {row.get('经历序号','')}　裁判置信度：**{conf_html}",
                        unsafe_allow_html=True)

        if step in FULLTEXT_STEPS:
            full = load_full_bio(cur_prov, cur_name)
            if full:
                with st.expander("完整履历原文（officials txt）", expanded=True):
                    st.text(full)
            elif TEXT_COL in df.columns and pd.notna(row.get(TEXT_COL)):
                st.warning("未找到完整履历 txt，回退到行级引用：")
                st.markdown(f"<div class='yuanwen'>{html.escape(str(row[TEXT_COL]))}</div>",
                            unsafe_allow_html=True)
        elif TEXT_COL in df.columns and pd.notna(row.get(TEXT_COL)):
            st.markdown("**原文引用**")
            st.markdown(f"<div class='yuanwen'>{html.escape(str(row[TEXT_COL]))}</div>",
                        unsafe_allow_html=True)

        # step2/step3：在原文下显示对应的 step1 经历，便于定位是哪个职位
        if step in CONTEXT_STEPS:
            ctx = {c: ("" if pd.isna(row.get(c)) else str(row.get(c)))
                   for c in STEP1_CONTEXT if c in df.columns}
            st.markdown("**对应 step1 经历**")
            st.table(pd.DataFrame([ctx]))

        if judge_col in df.columns and pd.notna(row.get(judge_col)):
            with st.expander("裁判理由（仅参考，拆分不改）", expanded=True):
                st.write(str(row[judge_col]))

        dispute_set = disputed_fields(row.get(judge_col), fields)
        st.markdown("**字段（只改内容，不增删行）**" +
                    ("　<span class='accent-red'>标红＝裁判指出的分歧字段</span>" if dispute_set else ""),
                    unsafe_allow_html=True)
        with st.form("edit_form", clear_on_submit=False, border=False):
            new_vals = {}
            for f in fields:
                cur = "" if pd.isna(row.get(f)) else str(row.get(f))
                if f in dispute_set:                       # 分歧字段：红色标签
                    st.markdown(f"<span class='accent-red'>{f}（分歧）</span>",
                                unsafe_allow_html=True)
                    new_vals[f] = st.text_input(f, value=cur, key=f"{rowid}_{f}",
                                                label_visibility="collapsed")
                else:
                    new_vals[f] = st.text_input(f, value=cur, key=f"{rowid}_{f}")
            note = st.text_input("备注", value="", key=f"{rowid}_note")
            b1, b2, b3, b4 = st.columns(4)
            back = b1.form_submit_button("返回上一条", use_container_width=True,
                                         disabled=not st.session_state["nav_hist"])
            ok = b2.form_submit_button("通过，不修改", use_container_width=True)
            doubt = b3.form_submit_button("依然存疑，下一条", use_container_width=True)
            save = b4.form_submit_button("保存修改，下一条", type="primary", use_container_width=True)

        now = storage.now_str()
        official_level = step in FULLTEXT_STEPS

        def done_next_person():
            """标记此人完成 → 回自动，跳下一位。"""
            set_status(reviewer, sstep, cur_prov, cur_name, "done")
            st.session_state["_reset_person"] = True
            st.session_state.pidx = 0
            st.rerun()

        def _push_hist():
            """前进前记录当前位置，供「返回上一条」回退（可跨人）。"""
            h = st.session_state["nav_hist"]
            snap = (cur_prov, cur_name, int(st.session_state.pidx))
            if not h or h[-1] != snap:
                h.append(snap)
                del h[:-300]

        def advance():
            """保存/通过：非最后一条 → 下一条；最后一条 → 完成此人并跳下一位。"""
            _push_hist()
            if st.session_state.pidx < n_rows - 1:
                st.session_state.pidx += 1
                st.rerun()
            else:
                done_next_person()

        def flush_note(extra: str = ""):
            """备注无论字段改没改都记录，独立成「备注」提案行（step 信息在 sstep 里）。"""
            txt = note.strip()
            if extra:
                txt = f"{txt}｜{extra}" if txt else extra
            if txt:
                storage.append("edits", {
                    "ts": now, "reviewer": reviewer, "rowid": rowid,
                    "province": cur_prov, "name": cur_name,
                    "episode_no": "" if official_level else str(row.get("经历序号", "")),
                    "step": sstep, "field": "备注", "old_value": "", "new_value": txt, "note": "",
                })

        if save:
            changed = 0
            for f in fields:
                old = "" if pd.isna(row.get(f)) else str(row.get(f))
                if new_vals[f] != old:
                    storage.append("edits", {
                        "ts": now, "reviewer": reviewer, "rowid": rowid,
                        "province": cur_prov, "name": cur_name,
                        "episode_no": "" if official_level else str(row.get("经历序号", "")),
                        "step": sstep, "field": f, "old_value": old, "new_value": new_vals[f], "note": "",
                    })
                    changed += 1
            flush_note()
            storage.append("progress", {"ts": now, "reviewer": reviewer, "rowid": rowid,
                                        "step": sstep, "action": f"改正({changed})" if changed else "通过"})
            heartbeat(reviewer, sstep, cur_prov, cur_name)
            st.toast(f"已保存：{changed} 处改动")
            advance()
        if ok:
            flush_note()
            storage.append("progress", {"ts": now, "reviewer": reviewer, "rowid": rowid,
                                        "step": sstep, "action": "通过"})
            heartbeat(reviewer, sstep, cur_prov, cur_name)
            advance()
        if doubt:
            flush_note("依然存疑")
            storage.append("progress", {"ts": now, "reviewer": reviewer, "rowid": rowid,
                                        "step": sstep, "action": "存疑"})
            heartbeat(reviewer, sstep, cur_prov, cur_name)
            advance()
        if back and st.session_state["nav_hist"]:
            st.session_state["_goto"] = st.session_state["nav_hist"].pop()
            st.rerun()

if ref_col is not None:
    with ref_col:
        st.markdown(f"### {step} 规则")
        with st.container(height=650):
            for fn, content in load_prompt_files(step):
                st.caption(f"`prompts/{fn}`")
                st.markdown(content)
                st.divider()
