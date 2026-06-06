# 单人重跑 SOP（只重做一人，不动同省其他人）

> 适用：某官员 bio 更新/爬错人/提取有误，需单独重新跑，**保留同省其他人结果**。

## 核心原理

- `--official 某人`：只对该人跑 step1-4 提取。
- **绝不能加 `--force`**：`--force` 会让 `load_json_cache(force=True)` 返回空字典，
  保存时把整省缓存覆盖成只剩这一人 → 同省其他人全部丢失。
- 不加 `--force` 时，`load_json_cache(force=False)` 读入现有缓存，
  `run_step` 只更新传入的单人条目（merge 写入），其余人保留。
- 但若该人**旧缓存还在**，`--official`（不 force）会命中缓存直接跳过提取，
  不会真正重做。所以必须**先删掉该人的旧缓存条目**。

## 标准两步

```bash
# 第 1 步：删除该官员在各 step 缓存中的所有条目（保留其他人）
uv run python del_person_cache.py <省> <姓名>
#   例：uv run python del_person_cache.py 江西 刘奇

# 第 2 步：单人重做（不加 --force！）
uv run code/main_province.py --province <省> --official <姓名>
#   例：uv run code/main_province.py --province 江西 --official 刘奇
```

`del_person_cache.py` 会清理：
- list 型缓存（`llm{1,2}_step{1-4}_*`、`merged_episodes{,_step1}`、`step*_diff_report`）
  按 `_meta.name` / `official_name` 删除该人项
- dict 型缓存（`step{1-4}_judge_decisions`）删除 `姓名||...` 前缀的 key

完成后该省 `output/{省}/{省}_{officials,governors,secretaries}.xlsx` 会整省重新导出，
但只有目标人的数据变化。

## 批量逐人（多人，仍各自独立、互不影响）

```bash
bash temp/redo_people.sh <省> <人1> <人2> ...
#   内部对每人执行：del_person_cache + --official（不 force），串行
```

## 验证（确认只目标人变）

用 git 字段级对比（忽略浮点格式差异，避免 to_csv 指纹误报）：

```python
import pandas as pd, io, subprocess
f = "output/<省>/<省>_officials.xlsx"
raw = subprocess.run(["git","show",f"HEAD:{f}"], capture_output=True).stdout
git = pd.read_excel(io.BytesIO(raw)); cur = pd.read_excel(f)
cols = ["年份","起始时间","供职单位","职务","升迁_省长","升迁_省委书记","该条行政级别"]
def norm(df):
    return {n:"##".join("|".join(str(x).replace(".0","") for x in g.sort_values("经历序号")[c])
                         for c in cols if c in g.columns)
            for n,g in df.groupby("姓名", sort=False)}
g,c = norm(git), norm(cur)
print("实质变化:", [n for n in set(g)|set(c) if g.get(n)!=c.get(n)])
# 应只列出目标人
```

## 之后

单省重做完后，如需更新全省汇总库：

```bash
uv run python build_allprovince.py   # 重新拼接 31 省 → output/全省_*.xlsx
```

## 注意

- judge 模型默认 `gpt-5.5`（config.py `JUDGE_MODEL`）。
  若 judge 阶段频繁 524/empty，多为通道临时故障，可探针测 gpt-5.4/5.5/claude-opus-4-8 择优切换。
- 年份列由 `export.py` 从 `data/1990/{省}_officials.txt` 名单注入
  （书记库=任书记年、省长库=任省长年），重抽不影响年份正确性。
