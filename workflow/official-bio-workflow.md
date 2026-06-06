# 官员履历提取-标记 Workflow（SOP · v9）

> **定位**：本文件是「从 biography 文本 → 结构化 Excel」整条 pipeline 的**人读权威 SOP**，对齐**代码实际**（`code/main_province.py` + `prompts/*.md` + `config.py`），不对齐过时的描述。
>
> **配套资产**：
> - 可调用技能：`.claude/skills/official-bio-pipeline.md`（精简版，触发后照本文执行）
> - 执行 Agent：`.claude/agents/official-bio-agent.md`
>
> **适用范围**：当前代码跑**省级**；本文第 9 节「层级适配表」说明如何复用到**市级 / 部委 / 人大**。

---

## 1. 一句话流程

```
名单(.txt) → biography 文本 → 4步 LLM 双跑+裁判 → 扁平化 → Excel(主表+分类表+battle对比表)
```

整条 pipeline 的**唯一编排者是 Python 代码**（`ThreadPoolExecutor` 并发），不是 Claude。Claude/Agent 的角色是**驱动 CLI、读日志、排障、汇报**，不替代代码逻辑。

---

## 2. 环境与入口

**包管理器：`uv`（唯一权威）**，禁止 `pip install`。

```bash
uv run code/main_province.py --province 安徽            # 默认：用现有文本，不爬
uv run code/main_province.py --province 北京 --start 2000
uv run code/main_province.py --official 王清宪 --province 安徽   # 单官员调试
uv run code/main_province.py --batch                    # 全部31省
uv run code/main_province.py --batch --provinces 安徽,河北,广东
```

> 代码 docstring 里写的是 `python code/main_province.py`，**以 `uv run` 为准**（见 CLAUDE.md 环境约定）。

---

## 3. 三层模型架构（config.py 权威）

| 角色 | 变量 | 当前模型 | 通道 |
|------|------|---------|------|
| **LLM1** 提取器 | `LLM1_MODEL` | `deepseek-v4-flash` | DeepSeek 直连 |
| **LLM2** 验证器 | `LLM2_MODEL` | `claude-opus-4-7` | Clariontech 代理 |
| **Judge** 裁判 | `JUDGE_MODEL` | `gpt-5.4` | Clariontech 代理 |
| 安全审查兜底 | `SAFETY_FALLBACK_MODELS` | `claude-sonnet-4-6` → `gpt-5.4-mini` → `claude-3-7-sonnet` | BLTCY 代理 |

- LLM1 与 LLM2 **异质双跑**（不同厂商、不同模型），保证独立性；diff 不一致处交 Judge 裁决。
- API key 全部从 `.env` 读取（逗号分隔支持多 key 轮询 `RoundRobinClientPool`）。
- ⚠️ 旧文档里写的 “DeepSeek / Qwen / Kimi K2.5” 已过时，以本表为准。

---

## 4. 完整 Pipeline（Phase 0 → 6，interleaved）

代码实际是 **4 个提取步骤**，编排成 **Phase A / Phase B** 两个并行波次（`run_province_pipeline`）：

```
Phase 0    载入名单          load_officials → parsed{governors, secretaries, gov_title, sec_title, all_officials}
Phase 0.5  biography 文本     默认用 officials/{省}/*_biography.txt；--scrape 才爬

Phase A（并行）  Step1 ∥ Step4          ← 两者输入独立，可同时跑
  ├ Step1 提取  起止时间/供职单位/职务   LLM1∥LLM2 → diff → judge → merged_episodes_step1.json
  └ Step4 标签  raw_bio + 升迁/本省提拔/本省学习 + 落马   LLM1∥LLM2 → diff → judge
                （Step4 直接读 preprocessed career_lines，不依赖 Step1）

Phase B（并行）  Step2 ∥ Step3          ← 两者都依赖 merged_episodes_step1.json
  ├ Step2 分类  组织标签/标志位/任职地(省·市)/中央地方   LLM1∥LLM2 → diff → judge
  └ Step3 级别  该条行政级别（用 ref_soe_rank / ref_university_rank 参考表）   LLM1∥LLM2 → diff → judge

Phase 5    后处理            postprocess → logs/{省}/final_rows.json   （代码内 print 作 "Phase 5"）
Phase 6    导出 + battle     export + build_battles → output/{省}/*.xlsx   （代码内 print 作 "Phase 6"）
```

> **关键纠正**：旧描述把流程写成「step1/2/3 三步顺序」，**错误**。代码与 prompts 一致为 **4 步**，且 `step2=分类(classify)`、`step3=行政级别(rank)`、`step4=标签/落马(labeling)`。

### 每步的「双跑 → diff → judge」统一模式

每个 Step 都走同一套（模块：`extraction.py` / `diff.py` / `judge.py` / `merged_builder.py`）：

1. **extract**：`run_stepN(... cfg1)` 与 `run_stepN(... cfg2)` 并行 → `llm1_stepN_*.json` / `llm2_stepN_*.json`
2. **diff**：`diff_stepN(logs)` → `stepN_diff_report.json`（定位两模型分歧）
3. **judge**：`judge_stepN(logs, ...)` → `stepN_judge_decisions.json`（Judge 仅裁决分歧项，带 confidence）
4. Step1 额外产出 `merged_episodes_step1.json`（后续 Step2/3 的输入底座，由 `merged_builder.py` 构建）

裁决置信度 < `JUDGE_CONF_THRESHOLD`（=85）的归入「争议未解决」，并在 `judgeNcon` 列暴露。

---

## 5. 文件 I/O 清单（按目录）

> 规则：`preprocessed_texts.json` 与所有中间结果**按省分存**到 `logs/{省}/`，**不写**顶层 `logs/`。

```
data/[1990/]{省}_officials.txt        ← 人工维护名单（--data-subdir 默认 "1990"）
officials/{省}/{姓名}_biography.txt    ← 原始百科文本（数据只读）

logs/{省}/
  preprocessed_texts.json             Phase 0.5 预处理产物
  llm1_step1_results.json  llm2_step1_results.json
  step1_diff_report.json   step1_judge_decisions.json
  merged_episodes_step1.json          ★ Step2/3 的输入底座
  llm1_step2_classify.json llm2_step2_classify.json   step2_diff_report.json  step2_judge_decisions.json
  llm1_step3_rank.json     llm2_step3_rank.json       step3_diff_report.json  step3_judge_decisions.json
  llm1_step4_labels.json   llm2_step4_labels.json     step4_diff_report.json  step4_judge_decisions.json
  final_rows.json                     Phase 5 扁平化行
  api_stats.json   api_failures.json  pipeline.log

output/{省}/
  {省}_officials.xlsx                 全部官员全部履历行（主表）
  {省}_governors.xlsx                 曾任省长者的所有行
  {省}_secretaries.xlsx               曾任省委书记者的所有行
  {省}_battle1.xlsx … battle4.xlsx    四个裁决阶段的 LLM1/LLM2/Judge 对比表
```

---

## 6. CLI 全参数（code/main_province.py）

| 参数 | 默认 | 作用 |
|------|------|------|
| `--province` | "" | 省份简称（安徽、北京…） |
| `--provinces` | "" | 逗号分隔多省（batch） |
| `--batch` | off | 全部 31 省 |
| `--start` | None | 起始年份过滤（不填=全部） |
| `--official` | "" | 单官员调试 |
| `--scrape` | off | **启用爬虫**（默认关，用现有文本） |
| `--skip-extract` | off | 跳过全部 LLM（Phase 1-4），仅 postprocess+export |
| `--skip-battle` | off | 仅跑 Step1 提取，无 diff/judge、无 2/3/4 |
| `--skip-step1` | off | 跳过 Step1（需 `merged_episodes_step1.json` 已存在），仅跑 Step2/3/4 |
| `--force` | off | 忽略缓存全量重跑 |
| `--playwright-first` | off | 爬取优先用 Playwright（百度百科专用） |
| `--data-subdir` | `"1990"` | 名单子目录；传空串 `""` 用 `data/` 根 |

**断点续跑**：所有中间 JSON 增量保存且线程安全；重跑时已完成项命中缓存自动跳过，除非 `--force`。

---

## 7. 输出列 Schema（config.py → COLUMNS 权威）

人物级 + 履历行级共一张表。**`config.py → COLUMNS` 是列定义与顺序的唯一权威**，改列只改 config，不在文档里另立一份。当前列（含每步 judge 置信度列）：

- **人物级**：年份、省份、姓名、出生年份、籍贯、籍贯（市）、少数民族、女性、全日制本科、`升迁_省长`、`升迁_省委书记`、本省提拔、本省学习、`judge4con`
- **行级 / Step1**：经历序号、起始时间、终止时间、供职单位、职务、`judge1con`
- **Step2**：组织标签、标志位、任职地（省）、任职地（市）、中央/地方、`judge2con`
- **Step3**：该条行政级别、本时期行政级别（running cummax，截至本经历的最高级别）、`judge3con`
- **引用 / Step4**：原文引用、是否落马、落马原因、备注栏

标签枚举（均在 config.py）：`ORG_TAGS`（32类组织标签）、`POSITION_TAGS`（23类标志位）、`RANK_LEVELS`（10级行政级别 + 哨兵「难以判断」）。

---

## 8. 错误处理与排障

| 现象 | 行为 / 处置 |
|------|------|
| 百科爬取失败 | 记录失败，提示手动保存到 `officials/{省}/{姓名}_biography.txt` |
| API 429 / 5xx | 指数退避重试（`LLM_429_BACKOFF_*`，最多 `*_MAX_RETRIES`=3） |
| 内容安全审查拦截 | 走 `SAFETY_FALLBACK_MODELS` 级联兜底 |
| LLM 返回非法 JSON | `utils` 正则兜底解析 |
| 单官员崩溃 | 捕获并记入 `api_failures.json`，其他官员继续 |
| 某省批量失败 | `run_batch` 捕获，记入失败列表，继续下一省 |

排障入口：先看 `logs/{省}/pipeline.log`、`api_failures.json`、`api_stats.json`（用量与各阶段耗时）。

---

## 9. 层级适配表（复用到 市级 / 部委 / 人大）

> **核心思路**：把「省」抽象成一个 `{层级}` 维度。下表区分**通用部分（不动）**与**层级特定（需适配）**。
> 现状代码硬编码省级，但**名单解析器已部分支持市级**。

### 9.1 通用部分 —— 跨层级不需要改

- 三层模型架构（LLM1/LLM2/Judge + 安全兜底）
- `diff.py` / `judge.py` / `merged_builder.py` / `postprocess.py` / `export.py` 主体
- Phase A/B interleaved 编排
- **`ORG_TAGS` 组织标签体系**（已含「国务院及其组成部门」「直属机构/部委管理的国家局」「全国人大机关」「地方人大」「省属/市属国企」「科研院所(中央/地方)」等，天然跨层级）
- **`RANK_LEVELS` + rank 参考表**（`ref_soe_rank.md` / `ref_university_rank.md`）

### 9.2 层级特定 —— 需适配

| 维度 | 省级（现状代码） | 市级 | 部委 | 人大 |
|------|----------------|------|------|------|
| 名单文件 | `data/{省}_officials.txt` | `data/{市}_officials.txt` | `data/{部委}_officials.txt` | `data/{人大}_officials.txt` |
| 名单 section header | `[省长]` `[省委书记]` | `[市长]` `[市委书记]`（解析器**已支持**） | `[部长]`（需新增 header） | `[主任]`（需新增 header） |
| 主官定义 | 省长/自治区主席/直辖市市长 + 省委书记 | 市长 + 市委书记 | **需按研究设计确定**（部长？兼党组书记？） | **需按研究设计确定**（常委会主任？） |
| `gov_title`/`sec_title` | 省长 / 省委书记 | 市长 / 市委书记 | 部长 / —— | 主任 / —— |
| `POSITION_TAGS` 标志位 | 已含省级+市级 | 已含 | **缺**：部长、副部长、部党组书记 | **缺**：人大常委会主任、副主任、委员 |
| 升迁列名（COLUMNS） | `升迁_省长` `升迁_省委书记` | `升迁_市长` `升迁_市委书记` | `升迁_部长` | `升迁_主任` |
| prompts「目标X」措辞 | 目标省份 | 目标城市 | 目标部委 | 目标机构 |
| 目录维度 | `{省}/` | `{市}/` | `{部委}/` | `{机构}/` |

> 解析器位置：`code_scrape/input_parser_province.py`
> - `GOVERNOR_HEADERS = {"[省长]","[市长]","[主席]"}`
> - `SECRETARY_HEADERS = {"[省委书记]","[市委书记]","[自治区党委书记]","[书记]","[党委书记]"}`

### 9.3 泛化工作量评估

- **市级**：≈ 就绪。解析器支持、`POSITION_TAGS` 含市级、`ORG_TAGS` 通用。主要补：升迁列名、prompts 措辞、目录维度。
- **部委 / 人大**：工作量更大。需补 ① 名单 header；② `POSITION_TAGS` 新标志位；③ 升迁列名；④ prompts 的主官识别与升迁判定规则；⑤ 明确「主官」业务定义（**研究设计决策，非技术决策**）。

---

## 10. 移植到新数据 / 新层级的步骤

1. **准备名单**：`data/[子目录/]{X}_officials.txt`，按 section header 格式（见 CLAUDE.md「官员名单格式」）。
2. **放置文本**：把 `{姓名}_biography.txt` 放进 `officials/{X}/`（或加 `--scrape` 现爬）。
3. **配置 `.env`**：`DEEPSEEK_API_KEY` / `CLARIONTECH_API_KEYS` / `BLTCY_API_KEYS`（详见 config.py `validate_api_keys`）。
4. **（仅部委/人大需要）代码泛化**：按 §9.2 改 header、`POSITION_TAGS`、升迁列名、prompts —— **这一步需用户明确指令后再做**（项目规则：无指令不改代码）。
5. **跑**：`uv run code/main_province.py --province {X}`（或对应入口）。
6. **验收**：查 `output/{X}/` Excel + `battle1~4` 对比表 + `api_stats.json`。

---

## 11. 已知「代码 vs 旧文档」不一致（待用户决定是否同步）

| 项 | 旧文档（CLAUDE.md / 旧 skill） | 代码实际 |
|----|------|------|
| 步骤数 | step1/2/3（3步） | **4步**（step1提取 / step2分类 / step3级别 / step4标签） |
| step2/3 含义 | step2=rank, step3=labels | step2=分类, step3=行政级别, step4=标签/落马 |
| 模型 | DeepSeek / Qwen / Kimi K2.5 | DeepSeek-V4-Flash / Claude-Opus-4-7 / GPT-5.4 |
| 编排 | 顺序 Phase 1/2/3 | interleaved Phase A(1∥4) / B(2∥3) |
| 入口（旧 skill） | `python main_v2.py --city` | `uv run code/main_province.py --province` |

> 本 SOP 已按**代码实际**编写。是否回头同步更新 `CLAUDE.md` 的 Pipeline 流程图，由用户决定。
