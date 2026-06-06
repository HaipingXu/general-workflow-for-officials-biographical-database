# 省级主官履历数据库 Pipeline

A multi-LLM extraction, verification, and adjudication pipeline that builds structured career databases of Chinese provincial leaders (governors and party secretaries) from Baidu Baike biographies.

## Overview

```
Biography Text → [LLM1 + LLM2] → Diff → Judge → Structured Excel
```

Two independent LLMs extract career episodes in parallel. A third reasoning model (DeepSeek-R) adjudicates disagreements. This cycle repeats for each of three extraction steps before proceeding to the next.

### Pipeline Phases

| Phase | Description | Output |
|-------|------------|--------|
| 0.5 | Preprocess biography text into numbered lines | `preprocessed_texts.json` |
| 1 | **Step 1** — Career episode extraction (LLM1+LLM2 → diff → judge) | `merged_episodes.json` |
| 2 | **Step 2** — Administrative rank assignment (LLM1+LLM2 → diff → judge) | `step2_judge_decisions.json` |
| 3 | **Step 3** — Person-level labels (LLM1+LLM2 → diff → judge) | `step3_judge_decisions.json` |
| 4 | Postprocess: merge all results into flat rows | `final_rows.json` |
| 5 | Export to Excel | `.xlsx` files |

### Models

| Role | Model |
|------|-------|
| LLM1 | Qwen-Plus (DashScope) |
| LLM2 | Doubao-Pro (Volcengine) |
| Judge | DeepSeek-Reasoner |

## Coverage

- **Scope**: 31 provinces, ~600 officials
- **Output**: ~20,000 career episode rows
- **Columns**: 30 structured fields per row (14 person-level + 16 episode-level)
- **Period**: 1949–present

## Output Schema (30 Columns)

**Person-level** (A–N): 年份, 省份, 姓名, 出生年份, 籍贯, 籍贯（市）, 少数民族, 女性, 全日制本科, 升迁\_省长, 升迁\_省委书记, 本省提拔, 本省学习, 本时期行政级别

**Episode-level** (O–AD): 经历序号, 起始时间, 终止时间, 组织标签, 标志位, 该条行政级别, 供职单位, 职务, 原文引用, 争议未解决, 任职地（省）, 任职地（市）, 中央/地方, 是否落马, 落马原因, 备注栏

## Project Structure

```
├── code/                  # Engine (Python pipeline) — usually untouched
│   ├── main_province.py   #   Pipeline entry point + CLI
│   ├── extraction.py      #   Step 1-4 LLM extraction (LLMConfig parameterized)
│   ├── diff.py            #   Step 1-4 diff comparison logic
│   ├── judge.py           #   Judge adjudication + battle.xlsx generation
│   ├── merged_builder.py  #   Build merged episodes from judge decisions
│   ├── postprocess.py     #   Post-process: flatten to final rows
│   ├── export.py          #   Excel export
│   ├── utils.py           #   LLM client pool, token counting, helpers
│   ├── config.py          #   API keys, paths, column definitions, concurrency
│   └── text_preprocessor.py  # Biography text preprocessing
├── prompts/               # Extraction rules (prompt-driven, code-free) [authoritative]
│   ├── step1_extraction.md
│   ├── step2_classify.md
│   ├── step3_rank.md
│   ├── step4_labeling.md
│   ├── ref_university_rank.md
│   └── ref_soe_rank.md
├── data/                  # INPUT (1): official roster files (hand-curated)
│   └── {scope}_officials.txt
├── officials/             # INPUT (2): biography text files
│   └── {scope}/{name}_biography.txt
├── logs/                  # Intermediate JSON results (generated, per scope)
├── output/                # Final Excel output (generated, per scope)
├── scripts/               # Standalone table post-processing tools
├── review_app/            # Optional: human-cleaning web app (Streamlit + Supabase)
└── code_scrape_reference/ # Scraper code — REFERENCE ONLY (may fetch stale revisions)
```

> Run from the project root — paths resolve via `code/config.py`'s `PROJECT_ROOT` (= parent of `code/`), so there is no need to `cd code/`.

## Usage

```bash
# Single province
uv run code/main_province.py --province 浙江

# Skip LLM extraction (reuse cached results)
uv run code/main_province.py --province 浙江 --skip-extract

# Enable Baidu Baike scraping
uv run code/main_province.py --province 浙江 --scrape

# Batch: all 31 provinces
uv run code/main_province.py --batch

# Run tests
uv run pytest tests/
```

## Quality Assurance

- **Dual-LLM verification**: Two LLMs extract independently; disagreements are adjudicated by a reasoning model
- **Field-level traceability**: Every extracted field links to a source line (L编号) in the original biography
- **Confidence scoring**: Judge assigns 0–100 confidence; scores below 90 are flagged in the output
- **Battle table**: Side-by-side comparison of LLM1 vs LLM2 vs Judge verdict for human review

## Requirements

- Python 3.11+
- Package manager: [uv](https://github.com/astral-sh/uv)
- API keys for DashScope (Qwen), Volcengine (Doubao), and DeepSeek (configured in `.env`)

## Research Applications

- Career trajectory analysis for Chinese officials
- Promotion incentives and local economic performance
- Anti-corruption campaign targeting patterns
- Factional politics and elite circulation
