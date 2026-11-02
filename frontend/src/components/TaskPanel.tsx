import { Button, Checkbox, Empty } from 'antd';
import type { TaskSummary } from '../api/types';
import { STATUS_LABEL } from '../api/types';
import StatusChip from './StatusChip';

interface Props {
  tasks: TaskSummary[];
  selected: string[];
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  onOpen: (id: string) => void;
  onExport: () => void;
  onSubmit: () => void;
  exporting: boolean;
  submitting: boolean;
  reviewBusy: boolean;
}

function badge(task: TaskSummary) {
  if (task.issue_count && task.issue_count > 0) {
    return <span className="row-badge is-warn">留 {task.issue_count} 条意见</span>;
  }
  if (task.human_edited) return <span className="row-badge">人工改过</span>;
  return null;
}

export default function TaskPanel({
  tasks,
  selected,
  onToggle,
  onToggleAll,
  onOpen,
  onExport,
  onSubmit,
  exporting,
  submitting,
  reviewBusy,
}: Props) {
  const allSelected = tasks.length > 0 && selected.length === tasks.length;
  const approved = tasks.filter((task) => task.status === 'approved').length;

  return (
    <aside className="results">
      <header className="results-head">
        <div>
          <div className="results-title">任务 · {tasks.length}</div>
          <div className="results-sub">
            已确认 {approved} 条{selected.length ? ` · 选中 ${selected.length}` : ''}
          </div>
        </div>
        <Checkbox
          checked={allSelected}
          indeterminate={selected.length > 0 && !allSelected}
          onChange={onToggleAll}
          disabled={!tasks.length}
        >
          全选
        </Checkbox>
      </header>

      <div className="results-body">
        {tasks.map((task) => (
          <div
            key={task.id}
            className={`task-row${selected.includes(task.id) ? ' is-selected' : ''}`}
          >
            <Checkbox
              checked={selected.includes(task.id)}
              onChange={() => onToggle(task.id)}
              onClick={(event) => event.stopPropagation()}
            />
            <button type="button" className="task-open" onClick={() => onOpen(task.id)}>
              <div className="task-line">
                <span className="task-seq">{String(task.seq).padStart(2, '0')}</span>
                <span className="task-name">{task.name}</span>
                <StatusChip task={task} compact />
              </div>
              <div className="task-meta">
                {task.step_count} 步 · {STATUS_LABEL[task.status]}
                {badge(task)}
              </div>
            </button>
          </div>
        ))}
        {!tasks.length && (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有任务" />
        )}
      </div>

      <footer className="results-foot">
        <Button
          onClick={onSubmit}
          loading={submitting}
          disabled={!selected.length || reviewBusy}
        >
          {selected.length ? `送审 ${selected.length} 条` : '送审'}
        </Button>
        <Button
          type="primary"
          onClick={onExport}
          loading={exporting}
          disabled={!selected.length}
        >
          导出表格
        </Button>
      </footer>
    </aside>
  );
}
