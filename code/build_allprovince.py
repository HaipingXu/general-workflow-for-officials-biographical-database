"""
合并 31 省单省输出 → 全省汇总库。

读取 output/{省}/{省}_secretaries.xlsx 与 _governors.xlsx，
按 data/1990 名单的省份顺序纵向拼接，输出：
  output/全省_省委书记数据库.xlsx  (sheet: 省委书记数据库)
  output/全省_省长数据库.xlsx      (sheet: 省长数据库)

年份列已由 export.py 按名单注入（书记库=任书记年, 省长库=任省长年）。
"""
import glob
from pathlib import Path
import pandas as pd

ROOT = Path("/Users/xuhaiping/Desktop/Workflow省级官员")
OUT = ROOT / "output"

# 省份顺序（与 data/1990 一致，全名）
PROV_ORDER = [
    "上海", "云南", "内蒙古", "北京", "吉林", "四川", "天津", "宁夏", "安徽",
    "山东", "山西", "广东", "广西", "新疆", "江苏", "江西", "河北", "河南",
    "浙江", "海南", "湖北", "湖南", "甘肃", "福建", "西藏", "贵州", "辽宁",
    "重庆", "陕西", "青海", "黑龙江",
]


def _collect(suffix: str) -> pd.DataFrame:
    frames = []
    for prov in PROV_ORDER:
        fp = OUT / prov / f"{prov}_{suffix}.xlsx"
        if not fp.exists():
            print(f"  ⚠ 缺失: {fp}")
            continue
        df = pd.read_excel(fp)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    specs = [
        ("secretaries", "全省_省委书记数据库", "省委书记数据库"),
        ("governors", "全省_省长数据库", "省长数据库"),
    ]
    for suffix, fname, sheet in specs:
        df = _collect(suffix)
        out_path = OUT / f"{fname}.xlsx"
        df.to_excel(out_path, index=False, sheet_name=sheet)
        print(f"✓ {fname}: {df['姓名'].nunique()} 人, {len(df)} 行, "
              f"{df['省份'].nunique()} 省 → {out_path.name}")


if __name__ == "__main__":
    main()
