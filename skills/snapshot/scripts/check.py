#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交付前一键检查：规则校验 + 批内连续段重叠，只输出有问题的条目。

代替原来分别跑 validate_tasks.py、check_segment_overlap.py（字面和换物名两遍）、
默认不读取历史台账；显式提供历史表时仅提示同名。

用法:
  python check.py 任务.csv|任务.xlsx|任务.md [--long] [--fill-materials] [--export 输出.xlsx] [--history 旧任务.csv]
  python check.py -            # 从标准输入读文本任务（聊天内出题，不必先建表）

文本格式（.md/.txt/标准输入）：每条任务以 `# 任务名称` 开头，后接 `1.xxx` 形式的步骤，条与条之间空行分隔。
  --long            长任务建议 30 步以上，未达时提醒复核，无默认上限（常规默认 10～20）
  --fill-materials  自动按步骤里的【物料】计算并填充『单套所需物料』
  --export <xlsx>   当无“不通过”项时，直接把任务导出为标准三列交付表 .xlsx
退出码 0 表示无“不通过”项；警告、重叠和同名只是线索，仍由人工语义判断。
"""
import argparse
import csv
import io
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from check_segment_overlap import find_overlaps, normalize  # noqa: E402
from validate_tasks import load_ledger, resolve_step_limits, validate_row  # noqa: E402
from materials import compare_materials, materials_text  # noqa: E402


def parse_text(text):
    """解析文本任务：`# 名称` 开头，后续编号行为步骤。"""
    rows, name, steps, material = [], None, [], ""

    def flush():
        if name is not None:
            rows.append({"任务名称": name, "任务步骤": "\n".join(steps), "单套所需物料": material})

    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^#+\s*\S", line) or line.startswith("任务名称："):
            flush()
            name = re.sub(r"^#+\s*|^任务名称：", "", line).strip().strip("`")
            steps, material = [], ""
        elif re.match(r"^\d+\.", line) and name is not None:
            steps.append(line)
        elif re.match(r"^(单套所需)?物料[：:]", line) and name is not None:
            material = re.sub(r"^(单套所需)?物料[：:]\s*", "", line)
    flush()
    return rows


def load_rows(source):
    if source == "-":
        rows = parse_text(sys.stdin.read())
    else:
        path = Path(source)
        suffix = path.suffix.lower()
        if suffix == ".csv":
            # Excel 在中文 Windows 上另存的 csv 常是 GBK
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                text = path.read_text(encoding="gbk")
            rows = list(csv.DictReader(io.StringIO(text, newline="")))
        elif suffix in (".xlsx", ".xls"):
            import pandas as pd
            rows = pd.read_excel(path).fillna("").astype(str).to_dict("records")
        else:
            rows = parse_text(path.read_text(encoding="utf-8"))
    for index, row in enumerate(rows, 1):
        row.setdefault("序号", str(index))
        # 交付表的列名是“任务名字”，内部统一按“任务名称”处理
        if "任务名字" in row and "任务名称" not in row:
            row["任务名称"] = row["任务名字"]
    return rows


def overlap_tasks(rows):
    return [{"id": str(r.get("序号", i)), "name": str(r.get("任务名称", "")),
             "steps": str(r.get("任务步骤", "")).splitlines()}
            for i, r in enumerate(rows, 1)]


def describe_overlap(hit):
    """换物名才相同的段容易被当成不同任务，单独标出。"""
    literal = [normalize(s) for s in hit["left_steps"]] == [normalize(s) for s in hit["right_steps"]]
    kind = "字面相同" if literal else "仅换物名"
    return (f"序号{hit['left_id']}《{hit['left_name']}》第{hit['left_start']}步 ↔ "
            f"序号{hit['right_id']}《{hit['right_name']}》第{hit['right_start']}步，连续{hit['length']}步（{kind}）")


def select_overlaps(hits, masked_min_run):
    """字面相同的段不管多短都保留；仅换物名的段达到 masked_min_run 才保留。

    屏蔽物名后，开头“拿起A放进B”之类的通用套路会在大批量里产生成百上千处 4 步匹配，
    全部列出会淹没真正的复用长段；同一任务对只保留最长的一处。
    """
    best, skipped = {}, 0
    for hit in hits:
        literal = [normalize(s) for s in hit["left_steps"]] == [normalize(s) for s in hit["right_steps"]]
        if not literal and hit["length"] < masked_min_run:
            skipped += 1
            continue
        key = (hit["left_id"], hit["left_name"], hit["right_id"], hit["right_name"])
        if key not in best or hit["length"] > best[key]["length"]:
            best[key] = hit
    return sorted(best.values(), key=lambda h: -h["length"]), skipped


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tasks")
    ap.add_argument("--long", action="store_true")
    ap.add_argument("--fill-materials", action="store_true", help="自动按步骤【】计算并填充单套所需物料")
    ap.add_argument("--export", help="校验无 BLOCK 时直接导出标准三列 .xlsx")
    ap.add_argument("--min-steps", type=int)
    ap.add_argument("--max-steps", type=int)
    ap.add_argument("--ledger", help="可选历史台账，仅提示同名")
    ap.add_argument("--history", help="可选历史任务表，仅提示同名")
    ap.add_argument("--ignore-date", action="append", default=[],
                    help="兼容旧命令；默认不读取交付历史，此参数不再影响检查")
    ap.add_argument("--min-run", type=int, default=4, help="连续相同段的最短步数")
    ap.add_argument("--masked-min-run", type=int, default=6, help="仅换物名的重叠段至少多长才列出")
    ap.add_argument("--max-overlap-lines", type=int, default=15)
    args = ap.parse_args()

    min_steps, max_steps, recommended = resolve_step_limits(args.long, args.min_steps, args.max_steps)
    if min_steps < 1 or (max_steps is not None and max_steps < min_steps):
        ap.error("步数下限须为正数，上限不得小于下限")
    rows = load_rows(args.tasks)
    if not rows:
        sys.exit("[FATAL] 没有解析到任务；检查文件格式（csv 需含 任务名称、任务步骤 列）")
    if "任务步骤" not in rows[0] or "任务名称" not in rows[0]:
        sys.exit(f"[FATAL] 缺少 任务名称/任务步骤 列，当前列：{list(rows[0])}")
    if args.fill_materials:
        for row in rows:
            row["单套所需物料"] = materials_text(row.get("任务步骤", ""))

    ledger = []
    for history_path in (args.ledger, args.history):
        if history_path:
            ledger.extend(load_ledger(Path(history_path)))
    passed = warned = blocked = 0

    # 旧版 csv/xlsx 没有物料列时不强制，文本任务和带该列的表格必须填
    check_materials = "单套所需物料" in rows[0]
    upper_label = str(max_steps) if max_steps is not None else "无上限"
    print(f"检查 {len(rows)} 条｜步数 {min_steps}～{upper_label}｜仅列出有问题的条目")
    if recommended is not None:
        print(f"长任务建议 {recommended} 步以上，未达时提醒复核；步数不代表现场时长")
    if not check_materials:
        print("提示：表里没有『单套所需物料』列，未检查物料；交付表必须有该列")
    for row in rows:
        issues, fp, _ = validate_row(row, min_steps, max_steps, ledger, recommended)
        blocks = [m for lv, m in issues if lv == "BLOCK"]
        warns = [m for lv, m in issues if lv == "WARN"]
        if check_materials:
            listed = str(row.get("单套所需物料", "")).strip()
            if not listed:
                blocks.append("缺少单套所需物料（例：书本2个、杯子1个）；可用 materials.py 按步骤【】自动生成")
            else:
                blocks += compare_materials(row.get("任务步骤", ""), listed)
        if blocks:
            blocked += 1
        elif warns:
            warned += 1
        else:
            passed += 1
        if not (blocks or warns):
            continue
        tag = "不通过" if blocks else "有警告"
        print(f"[{tag}] 序号{row['序号']}  {fp['name']}")
        for m in blocks:
            print(f"    ✗ {m}")
        for m in warns:
            print(f"    ⚠ {m}")
    overlaps = find_overlaps(overlap_tasks(rows), None, args.min_run, mask_objects=True)
    shown, skipped = select_overlaps(overlaps, args.masked_min_run)
    for hit in shown[:args.max_overlap_lines]:
        print(f"[连续段重叠] {describe_overlap(hit)}")
    if len(shown) > args.max_overlap_lines:
        print(f"[连续段重叠] 另有 {len(shown) - args.max_overlap_lines} 处较短的未列出（--max-overlap-lines 可调）")
    if skipped:
        print(f"[已省略] {skipped} 处 {args.min_run}～{args.masked_min_run - 1} 步的仅换物名短重叠（多为拿放套路）；"
              f"需要全部列出时加 --masked-min-run {args.min_run}")

    print(f"汇总：干净 {passed}，有警告 {warned}，不通过 {blocked}｜批内连续段重叠 {len(shown)} 处")
    print("以上只覆盖规则可判部分；现场时长须实测，真实用途、清洁依据、终态、五套库存和批内近似仍需复核。")
    if args.export and not blocked:
        if not args.export.lower().endswith(".xlsx"):
            sys.exit("[FATAL] 交付文件只用 xlsx")
        from export_xlsx import export
        export(rows, args.export)
        print(f"已导出 {len(rows)} 条 → {args.export}")
    sys.exit(1 if blocked else 0)


if __name__ == "__main__":
    main()
