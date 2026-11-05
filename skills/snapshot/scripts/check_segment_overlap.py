"""查找跨任务连续相同段；输出候选供人工判断，不代替场景与终态审查。"""
import argparse
import csv
import json
import re
from difflib import SequenceMatcher
from pathlib import Path


def normalize(step, mask_objects=False):
    step = re.sub(r"^\s*\d+[.、]\s*", "", step).strip()
    step = step.replace("桌面上的", "").replace("桌面上", "桌面")
    step = re.sub(r"【([^】]+?)\d+】", r"【\1】", step)
    if mask_objects:
        step = re.sub(r"【[^】]+】", "【物】", step)
    return step


def load_tasks(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    return [
        {"id": row.get("序号", str(index)), "name": row["任务名称"],
         "steps": row["任务步骤"].splitlines()}
        for index, row in enumerate(rows, 1)
    ]


def find_overlaps(left, right=None, min_run=4, mask_objects=False):
    results = []
    other = left if right is None else right
    for i, first in enumerate(left):
        for j, second in enumerate(other):
            if right is None and j <= i:
                continue
            a = [normalize(s, mask_objects) for s in first["steps"]]
            b = [normalize(s, mask_objects) for s in second["steps"]]
            for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
                if block.size >= min_run:
                    results.append({
                        "left_id": first["id"], "left_name": first["name"],
                        "right_id": second["id"], "right_name": second["name"],
                        "left_start": block.a + 1, "right_start": block.b + 1,
                        "length": block.size,
                        "left_steps": first["steps"][block.a:block.a + block.size],
                        "right_steps": second["steps"][block.b:block.b + block.size],
                    })
    return sorted(results, key=lambda item: -item["length"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch")
    parser.add_argument("--min-run", type=int, default=4)
    parser.add_argument("--mask-objects", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.min_run < 2:
        parser.error("--min-run 至少为2")
    rows = find_overlaps(load_tasks(args.batch), None, args.min_run, args.mask_objects)
    Path(args.output).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"发现 {len(rows)} 段待人工复核的连续重叠；不是自动淘汰或通过结论。")


if __name__ == "__main__":
    main()
