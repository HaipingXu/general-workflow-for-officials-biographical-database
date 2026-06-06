"""
删除某省 logs 缓存中【单个官员】的所有条目，以便用
  uv run main_province.py --province X --official 某人   (不加 --force)
只重做该人、保留其他人缓存。

用法: uv run python temp/del_person_cache.py 江西 刘奇
"""
import json
import sys
from pathlib import Path

ROOT = Path("/Users/xuhaiping/Desktop/Workflow省级官员")

# list 型缓存：每项有 _meta.name 或 official_name
LIST_CACHES = [
    "llm1_step1_results.json", "llm2_step1_results.json",
    "llm1_step2_classify.json", "llm2_step2_classify.json",
    "llm1_step3_rank.json", "llm2_step3_rank.json",
    "llm1_step4_labels.json", "llm2_step4_labels.json",
    "merged_episodes.json", "merged_episodes_step1.json",
    "step1_diff_report.json", "step2_diff_report.json",
    "step3_diff_report.json", "step4_diff_report.json",
]
# dict 型缓存：key 以 "姓名||" 开头
DICT_CACHES = [
    "step1_judge_decisions.json", "step2_judge_decisions.json",
    "step3_judge_decisions.json", "step4_judge_decisions.json",
]


def _name_of(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    return (item.get("_meta", {}) or {}).get("name", "") or item.get("official_name", "")


def main() -> None:
    prov, name = sys.argv[1], sys.argv[2]
    L = ROOT / "logs" / prov
    if not L.exists():
        print(f"✗ logs/{prov} 不存在")
        return

    removed = {}
    for fn in LIST_CACHES:
        p = L / fn
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        before = len(data)
        data = [x for x in data if _name_of(x) != name]
        if len(data) != before:
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            removed[fn] = before - len(data)

    pref = name + "||"
    for fn in DICT_CACHES:
        p = L / fn
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        keys = [k for k in data if k.startswith(pref)]
        if keys:
            for k in keys:
                del data[k]
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            removed[fn] = len(keys)

    print(f"=== 已从 logs/{prov} 删除 [{name}] 的缓存条目 ===")
    if removed:
        for fn, n in removed.items():
            print(f"  {fn}: -{n}")
    else:
        print("  (未找到该人任何缓存条目)")
    print("\n下一步(不加 --force, 保留其他人):")
    print(f"  uv run main_province.py --province {prov} --official {name}")


if __name__ == "__main__":
    main()
