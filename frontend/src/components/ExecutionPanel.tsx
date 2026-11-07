import { useEffect, useState } from 'react';
import type { Workspace } from '@/hooks/use-workspace';
import type { Run } from '@/api/types';
import { Button } from '@/components/ui/button';

const stages: Record<Run['stage'], string> = {
  queued: '等待执行', generating: '正在设计任务', validating: '正在检查规则', reviewing: '正在审核任务', done: '处理完成',
};

function duration(start: string, end: number) {
  const seconds = Math.max(0, Math.floor((end - new Date(start).getTime()) / 1000));
  return seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
}

export default function ExecutionPanel({ workspace: w }: { workspace: Workspace }) {
  const [now, setNow] = useState<number | null>(null);
  const run = w.currentRun;
  const active = Boolean(run && ['queued', 'running'].includes(run.status));
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);
  if (!run) return <div className="execution-empty"><div><strong>执行与结果</strong><p>提交后在这里查看进度和任务。</p></div></div>;
  const status = run.cancel_requested_at && active ? '正在停止' : run.status === 'cancelled' ? '已停止' :
    run.status === 'failed' || run.status === 'interrupted' ? '执行未完成' : stages[run.stage];
  const recent = w.activity.slice(-4);
  const currentTask = active && run.stage === 'reviewing' ? w.tasks.find((task) => task.id === run.task_ids[run.progress.completed]) : null;
  const lastEvent = recent.at(-1);
  return <section className="execution-panel" aria-label="本次执行">
    <div className="execution-top"><div className="execution-title"><strong>本次执行</strong></div>
      {run.started_at && <span className="execution-time">{duration(run.started_at, active ? (now ?? new Date(run.started_at).getTime()) : new Date(run.finished_at ?? run.started_at).getTime())}</span>}</div>
    <div className={`execution-status${active ? ' is-active' : ''}`} role="status">
      <span className="execution-dot" /><strong>{status}</strong>
      {run.stage === 'reviewing' && run.progress.total > 0 && <span>{run.progress.completed} / {run.progress.total}</span>}
    </div>
    {active && <p className="execution-hint">{run.cancel_requested_at ? '等待模型返回，已保存任务会保留。' :
      run.stage === 'generating' ? '等待模型结果，数量尚未确定。' : '进度会自动更新。'}</p>}
    {currentTask && <p className="execution-current-task">正在审核：{currentTask.name}</p>}
    {active && lastEvent && <p className="execution-last-update">最近活动：{duration(lastEvent.time, now ?? new Date(lastEvent.time).getTime())}前</p>}
    {recent.length > 0 && <ol className="execution-events">{recent.map((event) => <li key={event.id}>
      <span>{event.label}</span><time>{new Date(event.time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time>
    </li>)}</ol>}
    {active && w.activeRun.run?.id === run.id && <Button className="execution-stop" variant="outline" size="sm"
      disabled={w.stopping || Boolean(run.cancel_requested_at)} onClick={() => void w.stop()}>
      {run.cancel_requested_at ? '正在停止' : '停止本次执行'}</Button>}
  </section>;
}
