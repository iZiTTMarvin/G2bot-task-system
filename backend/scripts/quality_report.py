"""只读统计本地批次、人工反馈与模型调用证据；不调用模型、不修改数据库。"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def report(database: Path, limit: int = 50) -> dict:
    conn = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        batches = conn.execute('SELECT id FROM batches ORDER BY created_at DESC, id DESC LIMIT ?', (limit,)).fetchall()
        batch_ids = [b['id'] for b in batches]
        if not batch_ids:
            return {'batch_count': 0, 'note': '暂无批次，比例不计算'}
        marks = ','.join('?' for _ in batch_ids)
        tasks = conn.execute(f'SELECT * FROM tasks WHERE batch_id IN ({marks})', batch_ids).fetchall()
        versions = conn.execute(f'SELECT v.* FROM task_versions v JOIN tasks t ON t.id=v.task_id WHERE t.batch_id IN ({marks})', batch_ids).fetchall()
        decisions = conn.execute(f'SELECT d.* FROM decisions d JOIN tasks t ON t.id=d.task_id WHERE t.batch_id IN ({marks}) ORDER BY d.created_at, d.id', batch_ids).fetchall()
        latest = {d['task_id']: d for d in decisions}
        human_edited = {v['task_id'] for v in versions if v['author_type'] == 'human'}
        decided = list(latest.values())
        hard_failures = sum(json.loads(v['validation_json']).get('status') == 'failed' for v in versions)
        duration = []
        runs = conn.execute(f'SELECT * FROM runs WHERE batch_id IN ({marks})', batch_ids).fetchall()
        calls_by_batch = Counter()
        model_seconds = Counter()
        measured_runs = set()
        review_duration = []
        for run in runs:
            if run['started_at'] and run['finished_at']:
                elapsed = (datetime.fromisoformat(run['finished_at']) - datetime.fromisoformat(run['started_at'])).total_seconds()
                duration.append(elapsed)
                if run['kind'] in ('review_task', 'review_batch'):
                    review_duration.append(elapsed)
            for trace in (database.parent / 'agent-traces' / run['id']).glob('*.jsonl'):
                for line in trace.read_text(encoding='utf-8').splitlines():
                    event = json.loads(line)
                    if event['event'] == 'model_call_started':
                        calls_by_batch[run['batch_id']] += 1
                        measured_runs.add(run['id'])
                    elif event['event'] == 'model_call_finished':
                        model_seconds[run['batch_id']] += event['elapsed_seconds']
        def ratio(numerator, denominator):
            return {'numerator': numerator, 'denominator': denominator,
                    'rate': numerator / denominator if denominator else None}
        from app.services.batch_checks import current_issues
        batch_findings = {task_id: findings for batch_id in batch_ids
                          for task_id, findings in current_issues(conn, batch_id).items()}
        return {
            'batch_count': len(batches), 'task_count': len(tasks),
            'rule_failed_version_rate': ratio(hard_failures, len(versions)),
            'human_edited_decided_task_rate': ratio(sum(d['task_id'] in human_edited for d in decided), len(decided)),
            'human_rejected_task_rate': ratio(sum(d['decision'] == 'reject' for d in decided), len(decided)),
            'current_duplicate_task_rate': ratio(sum(any(i['severity'] == 'error' for i in findings)
                                                       for findings in batch_findings.values()), len(tasks)),
            'material_mismatch_version_rate': ratio(sum(any(i['code'] == 'MATERIALS_MISMATCH' for i in json.loads(v['validation_json']).get('issues', [])) for v in versions), len(versions)),
            'feedback_categories': dict(Counter(d['change_category'] for d in decisions)),
            'human_edit_categories': dict(Counter(v['change_category'] for v in versions if v['author_type'] == 'human')),
            'average_finished_run_seconds': sum(duration) / len(duration) if duration else None,
            'average_finished_review_run_seconds': sum(review_duration) / len(review_duration) if review_duration else None,
            'model_calls_by_batch': dict(calls_by_batch), 'model_seconds_by_batch': dict(model_seconds),
            'runs_with_call_evidence': len(measured_runs),
            'notes': ['人工比例以每条任务最近一次人工决定为准，未审核任务不入分母',
                      '规则失败比例按已存版本报告统计，不代表确认请求拦截率',
                      '耗时为作业墙钟时间，模型次数仅统计带调用事件的真实轨迹；演示模型不计',
                      '现场执行成功率、人工实际审核时长未采集；不推断为零'],
        }
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('--limit', type=int, default=50)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000:
        parser.error('--limit 必须在 1～10000 之间')
    print(json.dumps(report(args.database, args.limit), ensure_ascii=False, indent=2))
