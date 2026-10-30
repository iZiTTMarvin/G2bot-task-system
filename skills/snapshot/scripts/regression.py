#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
G2 任务设计技能的回归测试。

用例在 assets/regression_cases.csv：审核通过的任务必须判“通过”，已知坏例必须判“不通过”，
并且拦截原因里要含“应命中”关键词。每次按用户意见修改技能或校验脚本后都要跑，
防止新规则把好任务误杀，或把以前学到的禁令改丢。

用法:
  python regression.py
退出码 0 表示全部符合预期。
"""
import csv
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from validate_tasks import validate_row  # noqa: E402

CASES_PATH = SCRIPT_DIR.parent / "assets" / "regression_cases.csv"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    with open(CASES_PATH, encoding="utf-8-sig", newline="") as f:
        cases = list(csv.DictReader(f))
    failed = 0
    for c in cases:
        row = {"任务名称": c["任务名称"], "任务步骤": c["任务步骤"]}
        # 回归只看规则拦截，不做批内指纹判重，所以每条用独立的空台账
        min_steps = int(c.get("最少步数") or 10)
        max_steps = int(c.get("最多步数") or 20)
        issues, _, _ = validate_row(row, min_steps, max_steps, [])
        blocks = [msg for level, msg in issues if level == "BLOCK"]
        warns = [msg for level, msg in issues if level == "WARN"]
        # 期望取值：通过=无拦截｜不通过=有拦截｜提醒=无拦截但有提醒｜干净=无拦截也无提醒
        if blocks:
            actual = "不通过"
        elif warns:
            actual = "提醒"
        else:
            actual = "干净"
        expect = c["期望"]
        ok = actual == expect or (expect == "通过" and actual in ("提醒", "干净"))
        if ok and expect == "不通过" and c.get("应命中"):
            ok = any(c["应命中"] in m for m in blocks)
        if ok and expect == "提醒" and c.get("应命中"):
            ok = any(c["应命中"] in m for m in warns)
        mark = "OK  " if ok else "FAIL"
        print(f"[{mark}] {c['用例']}：期望{c['期望']}，实际{actual}")
        if not ok:
            failed += 1
            for m in blocks:
                print(f"       ✗ {m}")
    print(f"\n共 {len(cases)} 条，失败 {failed} 条")
    failed += run_tool_checks()
    sys.exit(1 if failed else 0)


def run_tool_checks():
    """check.py、lookup_history.py 和速查文件的接缝检查；返回失败数。"""
    from check import parse_text, select_overlaps
    from lookup_history import load_delivered, load_feishu, similar_entries
    import learn

    failures = 0

    def expect(label, ok):
        nonlocal failures
        print(f"[{'OK  ' if ok else 'FAIL'}] 工具-{label}")
        failures += 0 if ok else 1

    rows = parse_text("# 嘉兴数采-甲\n1.拿起【杯子】\n2.放下\n\n# 乙\n1.拿起\n")
    expect("文本格式解析出两条任务及步骤", [(r["任务名称"], len(r["任务步骤"].splitlines())) for r in rows]
           == [("嘉兴数采-甲", 2), ("乙", 1)])

    def hit(length, left, right):
        return {"left_id": "1", "left_name": "甲", "right_id": "2", "right_name": "乙",
                "left_steps": left, "right_steps": right, "length": length,
                "left_start": 1, "right_start": 1}

    same = [f"{i}.拿起【杯子】" for i in range(1, 5)]
    swapped = [f"{i}.拿起【碗】" for i in range(1, 5)]
    shown, skipped = select_overlaps([hit(4, same, same), hit(4, same, swapped)], 6)
    expect("字面相同的 4 步重叠保留，仅换物名的 4 步重叠省略", len(shown) == 1 and skipped == 1)

    from materials import compare_materials, materials_text
    steps = "1.拿起【碗1】\n2.拿起【碗2】\n3.拿起【筷子1】\n4.拿起【筷子2】\n5.拿起【书本】"
    expect("物料按【】汇总并去编号", materials_text(steps) == "碗2个、筷子2双、书本1个")
    expect("物料与步骤一致时无问题", not compare_materials(steps, "碗2个、筷子2双、书本1个"))
    expect("物料数量不符或缺项会报出", len(compare_materials(steps, "碗1个、书本1个")) == 2)
    expect("文本任务能读取物料行",
           parse_text("# 甲\n1.拿起【杯子】\n物料：杯子1个\n")[0]["单套所需物料"] == "杯子1个")

    delivered, feishu = load_delivered(), load_feishu()
    near, near_feishu = similar_entries("嘉兴数采-补充茶叶", "拧开【茶叶罐】的盖子倒干料", delivered, feishu)
    expect("历史查询能找回补充茶叶", any(e["name"] == "补充茶叶" for _, e in near)
           and any(n == "补充茶叶" for _, n in near_feishu))

    _, entries = learn.load()
    expect("速查 06-brief.md 与教训库一致",
           learn.BRIEF_PATH.exists() and learn.BRIEF_PATH.read_text(encoding="utf-8") == learn.render_brief(entries))
    return failures


if __name__ == "__main__":
    main()
