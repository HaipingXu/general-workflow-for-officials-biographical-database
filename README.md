# 官员履历数据库 · 通用 Workflow

把**官员名单 + 履历文本**经多 LLM 提取、双跑比对、裁判仲裁，转成结构化的 **Excel 履历数据库**。

> 这是一个**可复用的基座（base）**。现成实现以「省级主官（省长 / 省委书记）」为参考样例；要做**市级 / 县级 / 中央 / 部委 / 人大**等其它层级，只需改输入与少量配置，引擎代码（`code/`）基本不动。

```
履历文本 → [LLM1 ∥ LLM2] → diff → 裁判 → 结构化 Excel
```

两个独立 LLM 并行提取，第三个模型对分歧做字段级裁决；每一步都跑「双跑 → diff → 裁判」，再进入下一步。

---

## Pipeline（v9 interleaved）

```
Phase 0    载入名单
Phase 0.5  履历文本 → logs/{范围}/preprocessed_texts.json

Phase A（并行）  Step1 ∥ Step4
  Step1 提取    起止时间 · 供职单位 · 职务
  Step4 个人信息 raw_bio（姓名/出生年/籍贯/民族/性别/本科）· 是否落马   ← 只读文本

Phase B（并行）  Step2 ∥ Step3   （均依赖 merged_step1）
  Step2 分类    组织标签 · 标志位 · 任职地 · 中央/地方
  Step3 级别    该条行政级别（用 ref_soe_rank / ref_university_rank 对照表）

Phase 5  后处理 → logs/{范围}/final_rows.json
Phase 6  导出 + battle → output/{范围}/{范围}_officials.xlsx
```

**派生标签由代码计算（非 LLM）**：`升迁 · 本省提拔 · 本省学习` 不再让 LLM 整体判断，而是在**后处理**阶段由代码在「**任期组**」序列上确定性计算——把同期兼职聚合成一段任期，避免机械看上一行/下一行误判，并复用 step2/step3 已算好的任职地与行政级别。LLM 退守到只读文本的简单判断（个人信息、落马）。过渡期 code 主列与 LLM 原值（`*_llm` 对照列）并存，便于审计与回退。

> 设计动机：LLM 擅长「简单提取 + 查表匹配」，不擅长「多条件综合判读、跨任期 rank 序列比较」。所以把确定性逻辑外置成代码，让 LLM 只做简单判断。

### 模型与并发

| 角色 | 模型 | 来源 |
|------|------|------|
| LLM1（提取） | `deepseek-v4-flash` | DeepSeek |
| LLM2（验证） | `claude-opus-4-7` | BLTCY |
| Judge（裁判） | `gpt-5.5` | BLTCY |

API key 支持逗号分隔多 key 轮询；裁判信心阈值、并发上限（`LLM1/LLM2/JUDGE_MAX_WORKERS`）见 `code/config.py`。

---

## 目录结构

```
.
├── code/                 # 引擎（Python pipeline）—— 一般不用动
│   ├── main_province.py  #   入口 + CLI（命名带 province，逻辑与层级无关）
│   ├── extraction.py     #   统一 step1-4 提取（LLM1+LLM2 共用）
│   ├── diff.py judge.py  #   diff 比较 + 裁判
│   ├── tenure.py         #   任期组原语（兼职就高不就低 + 谓词/归一化，纯函数）
│   ├── derive_labels.py  #   代码派生：升迁 / 本省提拔 / 本省学习
│   ├── postprocess.py export.py  #   后处理 + Excel 导出
│   ├── config.py         #   API keys · 路径 · 列定义 · 并发常量
│   └── tests/            #   离线单元测试（tenure / derive_labels）
├── data/                 # 输入①：官员名单  {范围}_officials.txt（人工维护）
├── officials/            # 输入②：履历文本  {范围}/{姓名}_biography.txt
├── prompts/              # 提取规则（权威；改提取行为只改这里，不改代码）
├── output/               # 产物：{范围}/*.xlsx（运行生成）
├── logs/                 # 中间 JSON（运行生成，可删可重建）
├── workflow/             # 人读 SOP
├── scripts/              # 表格后处理小工具
└── code_scrape_reference/ # ⚠️ 爬虫代码仅供参考，不在主 pipeline 内
# （另有 review_app/ 人工清洗网站，含密钥，不随本仓库发布）
```

路径约定：`code/config.py` 的 `PROJECT_ROOT` = `code/` 的上一级，所有目录按根目录解析——**从根目录运行即可，无需 `cd code/`**。

---

## 环境 & 运行

包管理器：**`uv`**（唯一权威；禁止直接 `pip install`，依赖变更走 `uv add / uv remove`）。Python `>=3.11`。

```bash
uv sync                                                # 首次：同步环境
cp .env.example .env                                   # 然后填入自己的 API keys

uv run code/main_province.py --province 浙江            # 跑单个范围（现有文本，不爬）
uv run code/main_province.py --province 浙江 --skip-extract  # 复用已有 LLM 结果
uv run code/main_province.py --batch                   # 批量跑 data/ 下所有名单
uv run code/main_province.py --province 浙江 --drop-study    # 导出时删除脱产学习经历（默认保留）
# uv run code/main_province.py --help                  # 完整选项
```

> CLI 参数 `--province` 是历史命名，传入的其实是「范围名」= `data/{范围}_officials.txt` 与 `officials/{范围}/` 的前缀，对市/县/部委等同样适用（例：`--province 苏州市`）。

测试（纯离线，无 API）：

```bash
cd code && uv run python -m pytest tests/ -q
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

---

## 适配到新层级（市 / 县 / 中央 / 部委 / 人大）

目标：尽量只改**输入 + prompts + config 的几个常量**，不动引擎。

1. **放名单** → `data/{范围}_officials.txt`
2. **放履历文本** → `officials/{范围}/{姓名}_biography.txt`（纯文本，UTF-8）
3. **微调 prompts** → `prompts/*.md`（角色词、地域标签按新层级语义改写）
4. **核对列定义** → `code/config.py → COLUMNS`
5. **核对参考表** → `prompts/ref_soe_rank.md` / `prompts/ref_university_rank.md`
6. **并发与模型** → `code/config.py`
7. **跑** → `uv run code/main_province.py --province {范围}`，产物在 `output/{范围}/`

---

## 规则

1. **不爬虫** — 主 pipeline 默认 `skip_scrape=True`；`code_scrape_reference/` 仅作思路参考，新层级请自行确保拿到最新、完整的履历文本再放进 `officials/`。
2. **prompts 只读改逻辑** — 改提取行为只改 `prompts/*.md`，不改 `code/` 里的字符串。
3. **输入只读** — `officials/` 文本与 `data/{范围}_officials.txt` 不被代码覆写。
4. **按范围分存** — 中间产物写 `logs/{范围}/`，不写顶层 `logs/`。

| 内容 | 权威文件 |
|------|---------|
| Step1-4 提取/分类/级别/标签规则 | `prompts/step1_extraction.md` / `step2_classify.md` / `step3_rank.md` / `step4_labeling.md`（+ `ref_*.md`） |
| 列定义与顺序 | `code/config.py → COLUMNS` |
| 官员名单 | `data/{范围}_officials.txt`（人工维护） |
| 派生标签算法 | `code/derive_labels.py` + `code/tenure.py` |

---

## 可选：人工清洗网站

项目另有一个 Streamlit + Supabase 的人工核查界面，只对机器**有分歧且裁判没把握**（信心 < 85）的条目排队，改动写成「提案」不覆盖原始数据。该网站含部署密钥，**不随本仓库公开发布**（已在 `.gitignore` 中排除）。
