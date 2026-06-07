# 上线部署指南（Streamlit Community Cloud + Supabase）

> 决策：① repo 转私有　② Supabase 共享后端　③ 全组共享密码
> 我（Claude）已完成代码与仓库准备；下面带 ☐ 的是**需要你用自己账号操作**的步骤。

---

## 架构

```
组员浏览器 ──HTTPS──> Streamlit Community Cloud（跑 review_app/app.py）
                          │  密码门 (st.secrets.app_password)
                          ├─ 读数据: repo 内 output/*.xlsx + officials/ + prompts/
                          └─ 读写: Supabase（claims / review_edits / review_progress）
```

本地无 secrets 时自动回退本地 CSV，开发照常 `uv run streamlit run review_app/app.py`。

---

## A. Supabase（约 10 分钟）

☐ 1. 注册 https://supabase.com → New project（记住数据库区域，选离你们近的）
☐ 2. 进项目 → SQL Editor → New query → 粘贴下面整段 → Run：

```sql
create table if not exists claims (
  id bigint generated always as identity primary key,
  step text, province text, name text, reviewer text,
  claimed_at text, heartbeat text, status text
);
create table if not exists review_edits (
  id bigint generated always as identity primary key,
  ts text, reviewer text, rowid text, province text, name text,
  episode_no text, step text, field text, old_value text, new_value text, note text
);
create table if not exists review_progress (
  id bigint generated always as identity primary key,
  ts text, reviewer text, rowid text, step text, action text
);

-- 内部工具，关掉行级安全（RLS），让服务端 key 可直接读写
alter table claims disable row level security;
alter table review_edits disable row level security;
alter table review_progress disable row level security;
```

☐ 3. Project Settings → API，复制两项备用：
   - **Project URL**（形如 `https://xxxx.supabase.co`）
   - **service_role key**（⚠️ 私密，只放进 Streamlit secrets，绝不进 repo）

---

## B. Streamlit Community Cloud（约 5 分钟）

☐ 4. 注册 https://share.streamlit.io，用 GitHub 账号登录并**授权访问私有 repo**
☐ 5. New app → 选你自己的 repo（建议私有，因含官员数据）
       - Branch: `main`
       - **Main file path: `review_app/app.py`**
☐ 6. Advanced settings → **Secrets**，粘贴（替换成真实值）：

```toml
app_password = "你们的团队密码"

[supabase]
url = "https://xxxx.supabase.co"
key = "粘贴 service_role key"
```

☐ 7. Deploy。几分钟后得到一个 `https://xxx.streamlit.app` 网址。
☐ 8. 把网址 + 团队密码发给组员。各人左侧选**自己负责的省份**即为静态分配，互不撞车。

---

## 已完成（我这边）

- [x] repo 转为私有
- [x] 两个数据库 Excel 纳入 repo（私有，供云端读取）
- [x] `storage.py` 后端抽象（有 secrets→Supabase，无→CSV）
- [x] 共享密码登录门
- [x] `.streamlit/config.toml` 隐藏 Deploy/开发按钮（保留主题切换）
- [x] `requirements.txt` 补 streamlit + supabase
- [x] `.gitignore` 忽略真实 secrets.toml

## 验证清单（部署后自查）

- [ ] 打开网址 → 出现密码门 → 输入密码进入
- [ ] 左下角「存储后端」显示 **Supabase**（不是本地CSV）
- [ ] 两人用不同省份/同省，认领到不同官员、看到对方 🔒
- [ ] 改一条 → Supabase 的 `review_edits` 表出现记录

## 注意

- **不自动生成新版数据**：网页只往 Supabase 写改动提案。生成清洗后 Excel 由你（管理员）之后手动跑 apply 脚本（待做）。
- service_role key 拥有完全读写权限，务必只放 Streamlit secrets。若担心，可改用 anon key + 写 RLS 策略（更复杂）。
