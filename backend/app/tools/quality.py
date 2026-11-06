"""物料快照与人工核验契约；未知现场事实不推断为已满足。"""
from __future__ import annotations

import csv
import io
import json
import re


def parse_inventory(filename: str, data: bytes, source_id: str) -> list[dict]:
    if filename.lower().endswith('.csv'):
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('gbk')
        tables = [list(csv.reader(io.StringIO(text)))]
    elif filename.lower().endswith('.xlsx'):
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
        try:
            tables = [list(sheet.iter_rows(values_only=True)) for sheet in book.worksheets]
        finally:
            book.close()
    else:
        return []
    aliases = {
        'name': ('物品泛化名', '物料名称', '物料名', 'name'),
        'category': ('类别', 'category'), 'quantity': ('总数量', 'quantity'),
        'available_sets': ('可备套数', 'available_sets'), 'color': ('颜色', 'color'),
        'scene': ('场景', 'scene'), 'initial_position': ('初始位置', 'initial_position'),
        'grippable': ('可夹取', 'grippable'),
        'moving_container': ('移动容器', 'moving_container'),
    }
    records = []
    for table_no, table in enumerate(tables, 1):
        if not table:
            continue
        headers = [str(v or '').strip() for v in table[0]]
        positions = {key: next((headers.index(a) for a in names if a in headers), None)
                     for key, names in aliases.items()}
        if positions['name'] is None:
            continue
        for row_no, row in enumerate(table[1:], 2):
            item = {key: str(row[pos] if pos is not None and pos < len(row)
                             and row[pos] is not None else '').strip()
                    for key, pos in positions.items()}
            if not item['name']:
                continue
            invalid_fields = []
            for key in ('quantity', 'available_sets'):
                raw = item[key]
                if len(raw) <= 12 and re.fullmatch(r'\d+(?:\.0+)?', raw):
                    item[key] = int(raw.split('.')[0])
                else:
                    item[key] = None
                    if raw:
                        invalid_fields.append(key)
            for key in ('grippable', 'moving_container'):
                item[key] = {'是': True, '否': False, 'true': True, 'false': False,
                             '1': True, '0': False}.get(item[key].lower())
            records.append({**item, 'source_attachment_id': source_id,
                            'source_table': table_no, 'source_row': row_no,
                            'verification_status': 'source_declared',
                            'invalid_fields': invalid_fields})
    return records


def issue(code: str, severity: str, message: str) -> dict:
    return {'code': code, 'severity': severity, 'message': message,
            'step_no': None, 'rule_id': None}


def quality_issues(content: dict, inventory: list[dict]) -> list[dict]:
    issues = []
    total = sum(m['quantity'] for m in content['materials'])
    if total > 20:
        issues.append(issue('MATERIAL_TOTAL', 'error', f'任务物品总数 {total} 件，超过 20 件'))
    by_name: dict[str, list[dict]] = {}
    for item in inventory:
        by_name.setdefault(item['name'], []).append(item)
    containers = 0
    for material in content['materials']:
        name, quantity = material['name'], material['quantity']
        matches = by_name.get(name, [])
        if len(matches) != 1:
            issues.append(issue('INVENTORY_' + name, 'review_required',
                                f'核对【{name}】单套 {quantity} 件及五套库存：'
                                + ('物料表未提供唯一对应记录' if matches else '无结构化库存证据')))
            continue
        item = matches[0]
        if item['quantity'] is not None and item['quantity'] < quantity * 5:
            issues.append(issue('STOCK_' + name, 'error',
                                f'【{name}】五套需 {quantity * 5} 件，总库存仅 {item["quantity"]} 件'))
        if item['available_sets'] is not None and item['available_sets'] < 5:
            issues.append(issue('SETS_' + name, 'error', f'【{name}】可备套数不足五套'))
        if item['grippable'] is False:
            issues.append(issue('GRIP_' + name, 'error', f'物料表声明【{name}】不可夹取'))
        if item['moving_container'] is True:
            containers += quantity
        missing = [key for key in ('quantity', 'available_sets', 'color', 'scene',
                                   'grippable', 'moving_container')
                   if item.get(key) is None or item.get(key) == '']
        if missing:
            issues.append(issue('MATERIAL_EVIDENCE_' + name, 'review_required',
                                f'核对【{name}】缺失或无效字段：' + '、'.join(missing)))
    if containers > 2:
        issues.append(issue('CONTAINER_LIMIT', 'error', f'已明确的移动容器共 {containers} 个，超过 2 个'))
    for code, message in (
        ('PURPOSE', '说明任务服务的真实活动，确认步骤均为该活动所需'),
        ('INITIAL_STATE', '核对物品、工具来源及初始摆放符合现场'),
        ('TERMINAL_STATE', '确认终态符合待用、携带、收存或待洗目的，不撤销准备成果'),
        ('SITE', '现场核对可抓取、稳定、可达、颜色与桌面区分；同时在场物品 2～10 件、移动容器不超过 2 个'),
        ('WORKLOAD', '确认工作量来自必要操作和真实数量，长任务时长经实测'),
    ):
        issues.append(issue(code, 'review_required', message))
    if any(word in ''.join(content['steps']) for word in ('擦', '刷', '清洁')):
        issues.append(issue('CLEANING', 'review_required', '说明清洁对象及实际清洁需要，确认没有用擦刷凑步数'))
    return issues


def batch_inventory(conn, batch_id: str) -> list[dict]:
    row = conn.execute('SELECT material_snapshot_json FROM batches WHERE id=?', (batch_id,)).fetchone()
    return json.loads(row['material_snapshot_json']) if row else []
