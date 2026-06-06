# 官员履历数据库 · 通用 Base (general workflow)

> **这是一个可复用的基座（base）。** 现成实现以「省级主官」为参考样例；要做 **市级 / 县级 / 中央 / 部委 / 人大** 等其它层级，按下方〈如何适配到新层级〉改输入与少量配置即可，引擎代码（`code/`）基本不动。

> **输入** = 官员名单 + 履历文本　→　**输出** = Excel。

> 🌐 可选：`review_app/` 是人工清洗网站（Streamlit + Supabase）。要部署自己那一份，先读 `review_app/DEPLOYMENT_INFO.md`（线上 URL、Supabase 坐标、密钥位置都在里面；样例里写的是省级实例的坐标，自部署时替换）。

---

## 目录结构

```
.
├── code/                 # 引擎（Python pipeline）—— 一般不用动
├── data/                 # 输入①：官员名单  {范围}_officials.txt（人工维护）
├── officials/            # 输入②：履历文本  {范围}/{姓名}_biography.txt
├── prompts/              # 提取规则（权威；改提取行为只改这里，不改代码）
├── output/               # 产物：{范围}/*.xlsx（运行生成）
├── logs/                 # 中间 JSON（运行生成，可删可重建）
├── workflow/             # 人读 SOP
├── scripts/              # 表格后处理小工具（standalone）
├── review_app/           # 可选：人工清洗网站
└── code_scrape_reference/  # ⚠️ 爬虫代码仅供参考，见下方说明
```

### `code/` 模块职责

| 文件 | 职责 |
|------|------|
| `code/main_province.py` | Pipeline 入口 + CLI（名字带 province，但逻辑与层级无关，可直接复用） |
| `code/extraction.py` | 统一 step1-4 提取（LLMConfig 参数化，LLM1+LLM2 共用） |
| `code/diff.py` | step1-4 diff 比较逻辑 |
| `code/judge.py` | 裁判调用 + judge_step1-4 + build_battles（battle1-4.xlsx） |
| `code/merged_builder.py` | build_merged_episodes + source-line group helpers |
| `code/postprocess.py` | 后处理 → final_rows.json |
| `code/export.py` | Excel 导出 |
| `code/utils.py` | llm_chat, LLMConfig, RoundRobinClientPool, TokenCounter |
| `code/config.py` | API keys, **路径**, **列定义**, 并发常量 |

> 路径约定：`code/config.py` 里 `PROJECT_ROOT = Path(__file__).parent.parent`，即 `code/` 的上一级。`data/ officials/ prompts/ output/ logs/` 都按根目录解析，**从根目录运行即可，无需 `cd code/`**。

---

## 环境 & 入口

**包管理器：`uv`**（唯一权威；禁止直接 `pip install`，依赖变更走 `uv add / uv remove`）

```bash
uv sync                                              # 首次：同步环境
cp .env.example .env                                 # 然后填入自己的 API keys
uv run code/main_province.py --province 浙江          # 跑单个范围（现有文本，不爬）
uv run code/main_province.py --province 浙江 --skip-extract  # 复用已有 LLM 结果
uv run code/main_province.py --batch                 # 批量跑 data/ 下所有名单
uv run code/main_province.py --province 浙江 --drop-study  # 导出时删掉学习/进修经历（默认保留）
# uv run code/main_province.py --help                # 完整选项
```

> **可选功能 `--drop-study`**：导出 Excel 时删除「脱产学习/进修」经历行（判定依据 `标志位 == 学习进修`，即本科生/研究生/进修学员/访问学者/留学），并按人把 `经历序号` 重排为连续。**默认关闭**（学习经历照常保留）。三个输出表（全部/省长/省委书记）一致生效。常量见 `code/config.py → STUDY_FLAG`。

> CLI 参数 `--province` 是历史命名，传入的其实是「范围名」=`data/{范围}_officials.txt` 与 `officials/{范围}/` 的前缀，对市/县/部委等同样适用（例：`--province 苏州市`）。

---

## 如何适配到新层级（市级 / 县级 / 中央 / 部委 / 人大）

> 目标：尽量只改 **输入 + prompts + config 的几个常量**，不动引擎逻辑。

1. **放名单** → `data/{范围}_officials.txt`，格式见下方〈官员名单格式〉。`{范围}` 自取（如 `苏州市`、`财政部`、`全国人大`）。
2. **放履历文本** → `officials/{范围}/{姓名}_biography.txt`（纯文本，UTF-8）。
3. **核对/微调 prompts** → `prompts/*.md`。省级样例里的角色词（省长/省委书记）、「本省提拔/本省学习」等地域标签，按新层级语义改写；提取/分类/级别/标签四步的规则都在这里，**改提取行为只改 prompts，不改 `code/` 字符串**。
4. **核对列定义** → `code/config.py → COLUMNS`（输出 Excel 的列与顺序）。新层级若要增删字段，在此改。
5. **核对参考表** → `prompts/ref_soe_rank.md`、`prompts/ref_university_rank.md`（行政级别对照）。部委/央企层级可能需要补充。
6. **并发与模型** → `code/config.py`（`LLM1/LLM2/JUDGE_MAX_WORKERS`、各家 API key 来源）。
7. **跑** → `uv run code/main_province.py --province {范围}`，产物在 `output/{范围}/`。

> 省级的 `data/*.txt` 与 `officials/*` 作为**格式样例**保留，照着填即可；做完新层级后可删除省级样例。

---

## ⚠️ 爬虫代码仅供参考（`code_scrape_reference/`）

履历文本（`officials/`）的获取不在主 pipeline 内。`code_scrape_reference/` 是当初采集省级履历用的爬虫，**仅作参考**：

- 该方法**有时会爬到词条/页面的历史版本**，需人工核对时效；
- 不保证对新来源（市县政府网、部委官网、人大代表库）开箱可用；
- 建议把它当「思路参考」，新层级按数据源自行采集，确保拿到的是**最新、完整**的履历文本后再放进 `officials/`。

---

## 规则（每窗口强制）

1. **不爬虫** — 主 pipeline 默认 `skip_scrape=True`；爬虫仅参考，不在自动流程内
2. **按范围分存** — `preprocessed_texts.json` 等中间产物写 `logs/{范围}/`，不写顶层 `logs/`
3. **prompts 只读改逻辑** — 修改提取行为只改 `prompts/*.md`，不改 `code/` 里的字符串
4. **输入只读** — `officials/` 文本、`data/{范围}_officials.txt` 不可被代码覆写
5. **无指令不改代码** — 没有用户明确指令，不主动修改 `code/`；诊断结论先报告，等决策再动手

---

## 权威来源

| 内容 | 权威文件 |
|------|---------|
| Step1-4 提取规则 | `prompts/step1_extraction.md`（提取）/ `step2_classify.md`（分类）/ `step3_rank.md`（行政级别）/ `step4_labeling.md`（标签/落马）+ `ref_soe_rank.md` / `ref_university_rank.md` |
| 列定义与顺序 | `code/config.py → COLUMNS` |
| 官员名单 | `data/{范围}_officials.txt`（人工维护） |
| 路径根目录 | `code/config.py → PROJECT_ROOT` |
| 并发上限 | `code/config.py → LLM1_MAX_WORKERS / LLM2_MAX_WORKERS / JUDGE_MAX_WORKERS` |

---

## Pipeline 流程（v9 interleaved）

```
Phase 0   载入名单 → Phase 0.5 biography 文本 + logs/{范围}/preprocessed_texts.json

Phase A（并行）  Step1 ∥ Step4
  Step1 提取（起止时间/供职单位/职务）:
    LLM1 ∥ LLM2 → llm1/llm2_step1_results.json → diff → step1_diff_report.json
    → judge → step1_judge_decisions.json + merged_episodes_step1.json
  Step4 标签/落马（升迁/本地提拔/本地学习/是否落马，直接读 career_lines）:
    LLM1 ∥ LLM2 → llm1/llm2_step4_labels.json → diff → judge

Phase B（并行）  Step2 ∥ Step3（均依赖 merged_episodes_step1.json）
  Step2 分类（组织标签/标志位/任职地/中央地方）:
    LLM1 ∥ LLM2 → llm1/llm2_step2_classify.json → diff → judge
  Step3 行政级别（用 ref_soe_rank / ref_university_rank 参考表）:
    LLM1 ∥ LLM2 → llm1/llm2_step3_rank.json → diff → judge

Phase 5（postprocess）→ logs/{范围}/final_rows.json
Phase 6（export + battle）→ output/{范围}/{范围}_officials.xlsx + 分组表 + _battle1~4

# 完整流程见 workflow/official-bio-workflow.md（人读权威 SOP）
```

---

## 官员名单格式（`data/{范围}_officials.txt`）

```
省份：浙江                       # 「范围」标识行（沿用 key，可填省/市/县/部委名）
[省长]                          # 方括号 = 职务分组，按新层级改写（如 [市长] [厅长]）
张三, 2000.01-2003.06
李四（代）, 2003.07-2004.01      # （代）= 代理
[省委书记]
王五, 1999.06-2002.10
```

> 技能：`.claude/skills/official-bio-pipeline.md` ｜ Agent：`.claude/agents/official-bio-agent.md` ｜ 详细 SOP：`workflow/official-bio-workflow.md`
