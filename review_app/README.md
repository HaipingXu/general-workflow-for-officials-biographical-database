# 人工清洗网站（review_app）· 使用 & 修改指南

一个 Streamlit 单页应用，给 pipeline 导出的 Excel 做**人工核查**：只把机器**有分歧、且裁判没把握**（信心 < 阈值）的条目排队，人逐条核对、改正。改动写成「提案」，**绝不覆盖原始 Excel**，可审计、可回滚。

```
组员浏览器 ──密码门──> Streamlit（review_app/app.py）
                          ├─ 读: output/*.xlsx + officials/ + prompts/
                          └─ 读写: Supabase（认领锁 / 改动提案 / 进度）；本地无 secrets 时回退本地 CSV
```

> ⚠️ 真实密钥（团队密码、Supabase key）**只在** `.streamlit/secrets.toml`（本地，已 gitignore）或 Streamlit Cloud 的 Secrets 里，**绝不入库**。仓库只有 `.streamlit/secrets.toml.example` 模板。本目录的 `DEPLOYMENT_INFO.md`（线上坐标/账号）也不随仓库发布。

---

## 一、快速开始（本地，零配置）

```bash
uv sync
uv run streamlit run review_app/app.py     # 浏览器自动开 http://localhost:8501
```

不配 `secrets.toml` 时：

- 无密码门（直接进）；
- 存储**回退本地 CSV**（写在 `review_app/edits/`，不污染任何线上库）；
- 适合开发、试用、改 UI。

要连云端共享后端（多人协作）→ 见〈六、上线部署〉。

---

## 二、怎么使用这个网站（核查员视角）

1. **进站**：输入团队密码（线上才有）。
2. **选范围**（左侧栏）：
   - **数据源**：省长 / 省委书记（即审哪个库）
   - **审核人**：填你的名字（用于留痕 + 认领锁）
   - **审核步骤**：step1 提取 / step2 分类 / step3 级别 / step4 标签
   - **省份**：选一个（未完成的排前面）→ 静态分配，各人选不同省天生不撞车
   - **置信度阈值**：默认 85，只影响红色高亮 + 队列范围
3. **认领**：系统自动给你锁定一个还没人做的官员（别人看到 🔒，15 分钟无操作自动释放）。
4. **逐条核查**：屏幕显示 **原文 + 裁判理由 + 红色标出的分歧字段**；step2/3 还会显示对应的 step1 经历（知道在评哪个职位）。
5. **表态**（都会留痕）：
   - `✅ 通过（不修改）` / `✓ 保存修改` / `🤔 依然存疑`
   - 做完一人 → 自动跳下一位；`← 返回上一条` 可跨人回看。
6. **队列规则**：只含「该步**有分歧** 且 **裁判信心 < 阈值**」的条目——高置信分歧（裁判可靠）不进队列，省大量时间。
7. **step4 是官员级判断**：一人只判一次（看完整履历），各经历值相同，故折叠为单条。

> 改动只进 Supabase 的 `review_edits`（或本地 CSV），**原始 Excel 原封不动**。生成清洗版由管理员事后跑 `apply_edits.py`（见〈五〉）。

---

## 三、代码结构（3 个文件）

| 文件 | 职责 | 改 UI 要不要动 |
|------|------|----------------|
| `app.py` | **唯一 UI 文件**（单文件 Streamlit）：配置常量 → 工具函数 → 认领 → 登录门 → 侧栏 → 主区表单 | 改这里 |
| `storage.py` | 存储后端抽象：有 `st.secrets["supabase"]` 走 Supabase，否则本地 CSV。表 schema = `*_COLS` | 一般不碰 |
| `apply_edits.py` | 管理员脚本：读 Supabase `review_edits` → 叠加到原 Excel → 写 `output/cleaned/`（不覆盖原始） | 不碰 |
| `.streamlit/config.toml` | 主题/工具栏（`toolbarMode=viewer` 隐藏 Deploy 按钮）。改配色优先在这里 | 改主题在这里 |

---

## 四、怎么改（常见任务对照表）

> 改完务必本地跑一遍验证（见〈七〉）。改 `app.py` 顶部的**配置常量**最稳，避免动逻辑。

| 我想… | 改哪里（`app.py`，除非注明） |
|-------|------------------------------|
| 换审核哪些 Excel / 加数据源 | `DATA_SOURCES`（字典：`{"显示名": "xlsx 路径"}`） |
| 改每个 step 审哪些字段 | `STEP_FIELDS`（字典：`{"step 名": [字段, ...]}`） |
| 改默认置信度阈值 | `CONF_THRESHOLD = 85` |
| 改认领锁超时 | `LOCK_TTL_MIN = 15`（分钟） |
| 改配色 / 字体 / 隐藏按钮 | `.streamlit/config.toml` 的 `[theme]` |
| 改红色高亮逻辑 | `disputed_fields()`（解析裁判理由里的 `字段名[信心` 标记） |
| 改登录方式 | `check_password()`（默认读 `st.secrets["app_password"]`） |
| 换存储后端 / 改表结构 | `storage.py`（`*_COLS` + 读写函数；Supabase 建表 SQL 见 `DEPLOY.md`） |

**新层级适配**：换库时只改 `DATA_SOURCES` 指向你的导出 Excel；若字段集变了同步改 `STEP_FIELDS`。注意 step4 的「按库过滤」——省长库不审 `升迁_省委书记`，反之亦然（逻辑在 app.py 内，按数据源裁字段）。

---

## 五、核查完 → 生成清洗版数据

管理员跑（需 Supabase 凭据：env `SUPABASE_URL/SUPABASE_KEY` 或 `.streamlit/secrets.toml`）：

```bash
uv run python review_app/apply_edits.py --dry-run            # 先预览
uv run python review_app/apply_edits.py --source 省长         # 叠加省长库改动
uv run python review_app/apply_edits.py --doubts             # 同时导出"依然存疑"清单
```

输出写 `output/cleaned/{源}_cleaned_{时间戳}.xlsx`（已 gitignore，**不覆盖原始**）。

---

## 六、上线部署（团队分散、无服务器）

完整步骤见 **`DEPLOY.md`**。要点：

1. 代码推到你自己的 **GitHub repo**（建议私有，含官员数据）；
2. **Streamlit Community Cloud** 从该 repo 部署，Main file = `review_app/app.py`；
3. **Supabase** 建 3 张表（`claims` / `review_edits` / `review_progress`，SQL 见 DEPLOY.md）做共享后端；
4. 在 Streamlit Cloud 的 **Secrets** 填 `app_password` + `[supabase]`（照 `.streamlit/secrets.toml.example`）。

全部有免费额度。社区纠错（公开端）的规划见 `COMMUNITY_PLAN.md`（尚未实现）。

---

## 七、本地开发不污染线上

`.streamlit/secrets.toml` 若存在（含真实 key），**本地跑会直连生产 Supabase**，点"保存/通过"会写进线上库。改 UI 时若不想污染：

- 临时把 `secrets.toml` 改名（如 `secrets.toml.bak`）→ 自动回退本地 CSV，改完再改回；
- 或用无头自测：`streamlit.testing.v1.AppTest.from_file('review_app/app.py')`（无 secrets 走 CSV），改完确认 `at.exception` 为空。

---

## 设计约定（不可破）

| 约定 | 说明 |
|------|------|
| **行结构冻结** | 不增/删/合并/拆分行，只改格子里的值 → 下游不会乱 |
| **原始只读** | 原始 Excel 只读；改动写提案（Supabase / CSV），可回滚 |
| **完整留痕** | 谁 / 何时 / 改了什么 / 为什么，全程记录；"依然存疑"也留痕 |
| **只裁分歧** | 无差异、或裁判高把握的条目不进队列 → 省时间 |
