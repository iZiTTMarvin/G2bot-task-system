#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把文本任务导出成交付用的 xlsx（唯一的交付文件格式）。

用法:
  python export_xlsx.py 任务.md 输出.xlsx      # 或第一个参数用 - 读标准输入
文本格式同 check.py：`# 任务名称` 后接 `1.xxx` 步骤；可选 `物料：书本2个、杯子1个` 一行。
没写“物料：”时按步骤里的【物料】自动生成；写了就以写的为准（建议先跑 check.py 校验一致）。

表格列固定三列，顺序为：任务名字、任务步骤、单套所需物料。
任务步骤单元格为纯文本，每行一步 `1.xxx`；不写代码围栏。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import parse_text  # noqa: E402
from materials import materials_text  # noqa: E402

HEADERS = ["任务名字", "任务步骤", "单套所需物料"]


def export(rows, out_path):
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "任务"
    ws.append(HEADERS)
    for row in rows:
        steps = row["任务步骤"]
        material = row.get("单套所需物料") or materials_text(steps)
        ws.append([row["任务名称"], steps, material])

    side = Side(style="thin", color="BBBBBB")
    border = Border(top=side, bottom=side, left=side, right=side)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="305496")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for r in range(2, ws.max_row + 1):
        lines = ws.cell(r, 2).value.count("\n") + 1
        ws.row_dimensions[r].height = max(30, 15 * lines + 4)
        for c in (1, 2, 3):
            ws.cell(r, c).alignment = Alignment(vertical="top", wrap_text=True)
    for row in ws.iter_rows():
        for cell in row:
            cell.border = border
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 58
    ws.column_dimensions["C"].width = 36
    ws.freeze_panes = "A2"
    wb.save(out_path)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, out = sys.argv[1], sys.argv[2]
    text = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
    rows = parse_text(text)
    if not rows:
        sys.exit("[FATAL] 没有解析到任务")
    if not out.lower().endswith(".xlsx"):
        sys.exit("[FATAL] 交付文件只用 xlsx")
    export(rows, out)
    print(f"已导出 {len(rows)} 条 → {out}")


if __name__ == "__main__":
    main()
