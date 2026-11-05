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
    """check.py、判重、清洁提醒与速查文件的接缝检查；返回失败数。"""
    from check import parse_text, select_overlaps
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

    _, entries = learn.load()
    expect("速查 06-brief.md 与教训库一致",
           learn.BRIEF_PATH.exists() and learn.BRIEF_PATH.read_text(encoding="utf-8") == learn.render_brief(entries))

    from validate_tasks import step_difference, task_fingerprint, validate_atomic_tags
    def fingerprint(skeletons):
        return {"objects": ["书本", "笔"], "atomic_skills": ["Fold"], "step_skeletons": skeletons}

    original = fingerprint([f"旧{i}" for i in range(10)])
    boundary = fingerprint([f"旧{i}" for i in range(5)] + [f"新{i}" for i in range(5)])
    more = fingerprint([f"旧{i}" for i in range(4)] + [f"新{i}" for i in range(6)])
    less = fingerprint([f"旧{i}" for i in range(6)] + [f"新{i}" for i in range(4)])
    expect("同物料同技能时恰好50%差异可通过", step_difference(original, boundary) == 0.5)
    expect("超过50%差异可通过", step_difference(original, more) > 0.5)
    expect("不足50%差异供复核", step_difference(original, less) < 0.5)
    expect("不同长度按较长任务计算", step_difference(fingerprint(["甲", "乙"]),
           fingerprint(["甲", "乙", "丙", "丁"])) == 0.5)
    expect("无完整步骤不能计算差异", step_difference(original, {"actions": ["Fold"]}) is None)

    common = ["打开【文具盒】的盒盖", "从【文具盒】里拿出【笔】", "将【笔】放到桌面右侧",
              "从【文具盒】里拿出【印章】", "将【印章】放到桌面右侧"]
    left = common + ["将【纸袋】对折", "将【纸袋】展开铺平", "打开【印泥盒】的盒盖",
                     "用【印章】在【书本】页面盖章", "将【印章】推到桌面后侧"]
    right = common + ["将【笔】插入【笔筒】", "拔下【笔】上的【笔帽】", "用【笔】在【书本】页面画一横",
                      "将【书本】叠放在【书本2】上", "将【纸袋】拉开"]
    row = {"任务名称": "嘉兴数采-整理资料", "任务步骤": "\n".join(
        f"{i}.{step}" for i, step in enumerate(right, 1))}
    old = task_fingerprint("嘉兴数采-整理书本", left)
    issues, _, _ = validate_row(row, 1, None, [old])
    expect("真实步骤骨架恰好50%差异不拦截也不提示近似",
           step_difference(old, task_fingerprint(row["任务名称"], right)) == 0.5
           and not any("动作骨架" in message or "步骤完全相同" in message for _, message in issues))

    old_steps = ["拿起桌面上的【书本】", "将【书本】对折", "将【书本】放到桌面右侧"]
    old = task_fingerprint("嘉兴数采-整理书本", old_steps)
    reverse_row = {"任务名称": "嘉兴数采-整理资料", "任务步骤": "\n".join(
        f"{i}.{step}" for i, step in enumerate(reversed(old_steps), 1))}
    issues, _, _ = validate_row(reverse_row, 1, None, [old])
    expect("同批完全相同的步骤只换顺序仍拦截",
           any(level == "BLOCK" and "步骤完全相同" in message for level, message in issues))
    changed_row = {"任务名称": "嘉兴数采-整理资料", "任务步骤": "\n".join(
        f"{i}.{step.replace('书本', '毛巾')}" for i, step in enumerate(old_steps, 1))}
    issues, _, _ = validate_row(changed_row, 1, None, [old])
    expect("骨架近似只提醒不自动淘汰", any(level == "WARN" and "动作骨架" in message for level, message in issues)
           and not any(level == "BLOCK" and "步骤完全相同" in message for level, message in issues))

    for action in ("用【抹布】擦拭桌面", "用【刷子】刷拭【鞋子】表面", "用【刷子】刷【鞋子】表面"):
        issues, _, _ = validate_row({"任务名称": "嘉兴数采-整理用品", "任务步骤": f"1.{action}"}, 1, None, [])
        expect(f"缺少脏污线索提醒-{action}", any(level == "WARN" and "缺少明确脏污线索" in message
                                              for level, message in issues))
    issues, _, _ = validate_row({"任务名称": "嘉兴数采-清理桌面灰尘",
                                 "任务步骤": "1.用【抹布】擦去桌面的灰尘"}, 1, None, [])
    expect("有明确灰尘的清洁不误报缺少线索", not any("缺少明确脏污线索" in message for _, message in issues))
    pen_steps = "1.拔下【笔】上的【笔帽】\n2.用【笔】在【书本】页面画一横\n3.将【笔帽】盖回【笔】上"
    issues, _, _ = validate_row({"任务名称": "嘉兴数采-标记书本", "任务步骤": pen_steps}, 1, None, [])
    expect("笔帽和画一横可用", not any(level == "BLOCK" for level, _ in issues))
    expect("画一横的Write标签可核对", not any(level == "BLOCK" for level, _ in validate_atomic_tags("Write", pen_steps)[0]))
    issues, _, _ = validate_row({"任务名称": "嘉兴数采-标记书本", "任务步骤": "1.用【笔】在【书本】上签名"}, 1, None, [])
    expect("仍拦截签名", any(level == "BLOCK" and "签名" in message for level, message in issues))

    for name in ("嘉兴数采-铺平并叠好短裤", "嘉兴数采-补充茶叶并收纳茶罐"):
        issues, _, _ = validate_row({"任务名称": name, "任务步骤": "1.将【毛巾】对折"}, 1, None, [])
        expect(f"避免用并连接动作-{name}", any(level == "BLOCK" and "名称不得含" in m for level, m in issues))
    for name in ("张江数采-叠短袖", "嘉兴数采-夹取零食装盒", "嘉兴数采-铺平折叠短裤",
                 "嘉兴数采-用食物夹装零食", "嘉兴数采-在柜台摆放样品", "嘉兴数采-从盒里取出毛巾",
                 "张江数采-在桌面叠T恤", "张江数采-从果蔬栏取货", "嘉兴数采-在后厨整理厨具",
                 "并州-折叠毛巾", "嘉兴数采-整理并线夹"):
        issues, _, _ = validate_row({"任务名称": name, "任务步骤": "1.将【毛巾】对折"}, 1, None, [])
        expect(f"有效动宾主干或必要修饰不误拦-{name}", not any(level == "BLOCK" for level, _ in issues))
    for name, reason in (("折叠短裤", "缺少实际基地前缀"), ("-折叠短裤", "缺少实际基地前缀"),
                         ("嘉兴数采-洗护用品分拣", "宾语前置"),
                         ("嘉兴数采-铺平短裤后叠好", "XX后XX")):
        issues, _, _ = validate_row({"任务名称": name, "任务步骤": "1.将【毛巾】对折"}, 1, None, [])
        expect(f"不符合命名规则需拦截-{name}", any(level == "BLOCK" and reason in m for level, m in issues))
    issues, _, _ = validate_row({"任务名称": "嘉兴数采-收纳夹子",
                                 "任务步骤": "1.拿起桌面上的【并线夹】"}, 1, None, [])
    expect("并字连接词规则不扩展到步骤物料", not any(level == "BLOCK" and "并" in m for level, m in issues))
    failures += run_long_task_checks()
    return failures


def run_long_task_checks():
    """隔离验证步数和解析机制；重复擦拭仅为测试输入，不作为任务范例。"""
    import subprocess
    import tempfile
    from check import parse_text
    from materials import compare_materials, fill_text
    from validate_tasks import split_steps

    failures = 0

    def expect(label, ok):
        nonlocal failures
        print(f"[{'OK  ' if ok else 'FAIL'}] 长任务-{label}")
        failures += 0 if ok else 1

    # 通过公开 CLI 验证默认、显式上下限及错误参数。
    with tempfile.TemporaryDirectory(prefix="g2-long-regression-") as temp:
        path = Path(temp) / "tasks.md"
        for count, flags, expected_code, recommended_warning in [
            (19, ["--long"], 0, True), (20, ["--long"], 0, True),
            (29, ["--long"], 0, True), (30, ["--long"], 0, False),
            (31, ["--long"], 0, False), (40, ["--long"], 0, False),
            (120, ["--long"], 0, False),
            (40, ["--long", "--max-steps", "30"], 1, False),
            (29, ["--long", "--min-steps", "30"], 1, False),
            (29, ["--long", "--min-steps", "29"], 0, False),
            (25, ["--long", "--max-steps", "25"], 0, False),
            (21, [], 1, False), (20, [], 0, False),
            (20, ["--long", "--max-steps", "0"], 2, False),
        ]:
            text = "# 嘉兴数采-擦拭桌面\n" + "\n".join(
                f"{i}.用【抹布】擦拭桌面左侧" for i in range(1, count + 1))
            path.write_text(text, encoding="utf-8")
            result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT_DIR / "check.py"),
                                     str(path), "--fill-materials", *flags],
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            expect(f"CLI {count}步 {flags}", result.returncode == expected_code)
            expect(f"CLI {count}步 {flags} 长任务建议提醒",
                   (f"长任务 {count} 步，建议 30 步以上" in result.stdout) == recommended_warning)
            if result.returncode != expected_code:
                print(result.stdout[-1500:], result.stderr[-1500:])
            if count == 120:
                parsed = parse_text(text)
                expect("三位数编号不截断", len(parsed[0]["任务步骤"].splitlines()) == 120
                       and len(split_steps(parsed[0]["任务步骤"])) == 120)
                expect("物料读取器保留第100步后物料", "物料：杯子1个" in fill_text(
                    "# 甲\n100.拿起桌面上的【杯子】\n"))

        csv_path = Path(temp) / "tasks.csv"
        for count, expected_code, recommended_warning in [(29, 0, True), (30, 0, False), (120, 0, False)]:
            with csv_path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["任务名称", "任务步骤"])
                writer.writeheader()
                writer.writerow({"任务名称": "嘉兴数采-擦拭桌面", "任务步骤": "\n".join(
                    f"{i}.用【抹布】擦拭桌面左侧" for i in range(1, count + 1))})
            result = subprocess.run([sys.executable, "-X", "utf8", "-B",
                                     str(SCRIPT_DIR / "validate_tasks.py"), str(csv_path), "--long"],
                                    capture_output=True, text=True, encoding="utf-8", timeout=30)
            expect(f"独立校验CLI {count}步", result.returncode == expected_code)
            expect(f"独立校验CLI {count}步长任务建议提醒",
                   (f"长任务 {count} 步，建议 30 步以上" in result.stdout) == recommended_warning)
            if result.returncode != expected_code:
                print(result.stdout[-1500:], result.stderr[-1500:])

    examples = (SCRIPT_DIR.parent / "references" / "04-examples.md").read_text(encoding="utf-8")
    sample = examples.split("### 完整示例：", 1)[1].split("```txt\n", 1)[1].split("```", 1)[0].strip()
    issues, _, _ = validate_row({"任务名称": "嘉兴数采-盖章整理书本", "任务步骤": sample}, 1, None, [], 30)
    expect("39步完整模板文本校验", len(sample.splitlines()) == 39
           and not any(level == "BLOCK" for level, _ in issues))
    expect("模板物料与步骤一致", not compare_materials(
        sample, "文具盒1个、笔1支、印章1个、印泥盒1个、书本2个、笔帽1个"))
    failures += run_history_cli_checks(sample)
    return failures


def run_history_cli_checks(sample):
    """通过公开入口核对默认不查历史、显式历史只提示同名及同批拦截。"""
    import shutil
    import subprocess
    import tempfile

    failures = 0

    def expect(label, ok):
        nonlocal failures
        print(f"[{'OK  ' if ok else 'FAIL'}] 历史与同批-{label}")
        failures += 0 if ok else 1

    with tempfile.TemporaryDirectory(prefix="g2-history-regression-") as temp:
        root = Path(temp)
        tasks = root / "tasks.md"
        name = "嘉兴数采-盖章整理书本"
        tasks.write_text(f"# {name}\n{sample}\n", encoding="utf-8")
        history = root / "history.csv"
        with history.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["任务名称", "任务步骤"])
            writer.writeheader()
            writer.writerow({"任务名称": name, "任务步骤": sample})
            writer.writerow({"任务名称": "嘉兴数采-其他名称", "任务步骤": sample})

        def run(script, *args):
            return subprocess.run([sys.executable, "-X", "utf8", "-B", str(script), *map(str, args)],
                                  capture_output=True, text=True, encoding="utf-8", timeout=30)

        checker = SCRIPT_DIR / "check.py"
        default = run(checker, tasks, "--long", "--fill-materials")
        expect("默认不提示历史同名", default.returncode == 0 and "历史任务同名" not in default.stdout)
        for option in ("--history", "--ledger"):
            result = run(checker, tasks, "--long", "--fill-materials", option, history)
            expect(f"{option}仅提示同名且不按历史步骤拦截",
                   result.returncode == 0 and "历史任务同名" in result.stdout
                   and "嘉兴数采-其他名称" not in result.stdout)
            if result.returncode:
                print(result.stdout[-1500:], result.stderr[-1500:])

        tasks.write_text(f"# {name}\n{sample}\n\n# 嘉兴数采-标记书本\n{sample}\n", encoding="utf-8")
        identical = run(checker, tasks, "--long", "--fill-materials")
        expect("同批步骤完全相同会拦截", identical.returncode == 1 and "步骤完全相同" in identical.stdout)
        changed = sample.replace("39.将【文具盒】放到桌面右后方", "39.将【文具盒】放到桌面左后方")
        tasks.write_text(f"# {name}\n{sample}\n\n# 嘉兴数采-标记书本\n{changed}\n", encoding="utf-8")
        near = run(checker, tasks, "--long", "--fill-materials")
        expect("同批骨架近似只提醒", near.returncode == 0 and "动作骨架估计差异" in near.stdout)

        obsolete = ("assets/delivered_tasks.txt", "assets/existing_tasks_feishu.txt",
                    "assets/ledger_template.csv", "scripts/lookup_history.py", "scripts/build_ledger.py")
        expect("技能目录内没有历史数据和旧查询入口",
               all(not (SCRIPT_DIR.parent / item).exists() for item in obsolete))
        overlap_help = run(SCRIPT_DIR / "check_segment_overlap.py", "--help")
        expect("连续段工具不提供历史步骤查询入口",
               overlap_help.returncode == 0 and "--history" not in overlap_help.stdout)

        isolated = root / "isolated"
        shutil.copytree(SCRIPT_DIR, isolated / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        (isolated / "assets").mkdir()
        (isolated / "references").mkdir()
        shutil.copy(SCRIPT_DIR.parent / "assets" / "atomic_skills_catalog.csv", isolated / "assets")
        shutil.copy(SCRIPT_DIR.parent / "references" / "06-learned-rules.md", isolated / "references")
        tasks.write_text(f"# {name}\n{sample}\n", encoding="utf-8")
        standalone = run(isolated / "scripts" / "check.py", tasks, "--long", "--fill-materials")
        expect("无历史文件时独立目录仍可校验", standalone.returncode == 0)
        if standalone.returncode:
            print(standalone.stdout[-1500:], standalone.stderr[-1500:])
    return failures


if __name__ == "__main__":
    main()
