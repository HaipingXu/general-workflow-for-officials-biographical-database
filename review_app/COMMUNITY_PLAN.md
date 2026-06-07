# 社区纠错系统 · 设计思路（Phase 2 规划）

> 背景：内部裁决工具（review_app）已上线。下一步是数据发布后，让**社区**给数据纠错、
> 我们核查后更改（类似 GitHub PR/comment）。本文是接手前的设计思路，不是最终实现。
> 作者：Claude；最后更新 2026-06-05。

---

## 0. 一句话

**复用现有 Supabase + Streamlit + apply_edits 这套**，加一个「公开只读浏览 + 提交勘误表单」的公众端，
和一个「审核队列」的管理端。**社区只能提议，绝不直接改库；强制带证据；我们审核后才进发布版。**

---

## 1. 不可动摇的原则（来自最初讨论）

1. **只提议、不直接改**：任何公开编辑必须经我们核查后才生效。绝不做维基式即时生效（政治敏感 + 防破坏）。
2. **强制证据来源**：勘误表单"出处/链接"为必填，没来源的直接挡掉一大半噪音。
3. **可溯源可回滚**：每条提议=结构化记录（定位+原值+新值+提交人+时间+证据+状态），沿用内部 `review_edits` 的提案模型。
4. **版本化发布 + 许可**：对外发布用**冻结版本**，挂 **Zenodo DOI**（可引用）+ **CC BY 4.0**（数据）/ **MIT**（代码）。
5. **登录防刷**：匿名=爬虫和破坏者的乐园，至少邮箱/GitHub 登录。
6. **政治敏感托管**：公开端只暴露"已发布的清洗版"，不暴露内部未审数据；托管位置（墙内外/合规）单独评估。

---

## 2. 推荐架构（复用现有栈，最省事）

```
公众浏览器
  ├─ 公开端 (Streamlit, 只读已发布数据 + 「提交勘误」表单)
  │     └─ 写 Supabase: community_proposals (status=pending, 强制证据)
  │
管理端 (review_app 加一个 admin 页 / 或独立页)
  └─ 列 pending 提议 → 核查 → approve/reject
        └─ approve 的提议 → 复用 apply_edits 思路 → 重新生成发布版 → 打版本/DOI
```

为什么复用而不另起炉灶：内部已经有「提案表 → apply 脚本 → 生成版本」的闭环，社区纠错本质是
**同一个提案模型，换一批提交人 + 加一道审核闸门 + 加证据字段**。

---

## 3. 数据模型（新增 Supabase 表）

```sql
create table community_proposals (
  id bigint generated always as identity primary key,
  ts text,                      -- 提交时间
  source text,                  -- 省长 / 省委书记
  province text, name text,     -- 定位：官员
  episode_no text,              -- 定位：经历序号（官员级留空）
  field text,                   -- 要改的字段
  old_value text,               -- 提交人看到的现值（用于乐观锁/冲突检测）
  new_value text,               -- 建议改成
  evidence text,                -- ⚠️ 必填：出处链接/引文
  contributor text,             -- 提交人标识（邮箱/GitHub handle）
  status text default 'pending',-- pending / approved / rejected
  reviewer text, decided_at text, review_note text
);
alter table community_proposals enable row level security;
-- 公众端用 anon key + RLS：只能 insert(带 evidence)、只能 select 自己的或已公开的；不能 update/delete。
-- 管理端用 service_role：可改 status。
```

> 注意：公众端**必须用 anon key + 严格 RLS**（不能给 service_role，否则等于把库权限交给公网）。
> 这与内部工具（service_role 藏在 secrets）不同——社区端是真·公开，安全模型要收紧。

---

## 4. 审核 → 发布流程

1. 社区在公开端按某行提交勘误（带证据）→ `community_proposals` status=pending。
2. 管理端审核队列：看 原值/新值/证据/原文 → approve 或 reject（写 reviewer/decided_at/review_note）。
3. approve 的提议：转成内部 `review_edits` 同构记录（或 apply 脚本直接吃 `community_proposals` 里 approved 的行），
   叠加到当前发布版 → 生成新版本 Excel/CSV。
4. 发布：版本号 + 变更日志(changelog) + 推 Zenodo（DOI）。GitHub 公开 repo 存发布版 CSV，git 历史即变更史。

---

## 5. 三条路线对比（选 A，必要时叠 C）

| 路线 | 做法 | 优 | 劣 | 适合 |
|------|------|----|----|------|
| **A. 复用 Supabase+Streamlit**（推荐） | 公开端表单 → community_proposals → 管理端审核 → apply | 与现有栈一致、零新基建、上手快 | 自己实现版本历史/讨论线程 | 现在最顺 |
| B. 纯 GitHub Issue/PR | 发布版 CSV 进公开 repo，社区提 Issue/PR | 免费版本史+审核+讨论，git 原生 | 非技术用户不会用；大 CSV diff 噪音 | 受众是研究者/技术圈 |
| **C. 混合**（A 的表单 + GitHub 后端） | 友好表单 → 用 API 自动建 GitHub Issue/PR | 用户友好 + 白嫖 git 版本史/评论 | 要维护 API 集成 | 想要"PR/comment"体验又要低门槛 |

> 起步用 A（和现有闭环最契合）；若后期想要公开透明的"评论/讨论"体验，再叠加 C 把 approved 变更同步到公开 GitHub repo 做版本史。

---

## 6. 防破坏 & 敏感性

- 登录：GitHub OAuth 或邮箱 magic link（Supabase Auth 自带），匿名一律拒。
- 频率限制：单用户/IP 每日提交上限；提交进 pending 不即时生效。
- 证据必填 + 字段级提议（不是自由编辑整行），降低噪音和误伤。
- 政治敏感：公开端只读"已发布清洗版"；是否对外、托管在哪（Streamlit Cloud 墙外 / 国内合规平台）单独决策；保留随时下线开关。

---

## 7. 版本化 & 许可（发布前必做）

- 数据：**CC BY 4.0**（开放 + 强制署名，拿引用 credit）。
- 代码：**MIT**。
- 每个对外版本：冻结 → GitHub Release + **Zenodo DOI**（可被论文引用）。
- 维护 `CHANGELOG`：每版列"社区贡献了哪些更正"。

---

## 8. MVP → 完整（建议分期）

- **MVP**：公开端只读浏览已发布版 + 提交勘误表单(带证据) → community_proposals；管理端一个 pending 列表能 approve/reject；approve 后手动跑 apply。够验证流程。
- **V1**：apply 自动吃 approved 提议 + 生成版本 + changelog；登录(GitHub/邮箱) + RLS + 频率限制。
- **V2**：公开提议列表/状态可查（透明）；可选叠加 GitHub 同步(路线 C)；Zenodo 自动发版。

---

## 9. 接手前要定的开放问题

1. 受众主要是**研究者(懂 git)**还是**泛公众**？→ 决定 A vs C 的权重。
2. 公开端**托管在哪**、**是否需要国内可访问/合规**？
3. 登录用 **GitHub** 还是**邮箱**？（影响门槛与防刷）
4. 发布**粒度与节奏**：滚动发布 vs 定期冻结版？
5. 谁是 maintainer、审核 SLA（多久处理一条提议）？

---

> 实现时复用：`review_app/storage.py`（再加一个 `community_proposals` kind）、`review_app/apply_edits.py`
> （加一个 `--from-community` 吃 approved 提议）、`.streamlit/config.toml`（公开端单独一份主题）。
