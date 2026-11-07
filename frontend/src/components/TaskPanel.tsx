import { useState } from 'react';
import { ArrowDownToLine, ChevronDown, ClipboardList, Search, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import type { TaskSummary } from '@/api/types';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import StatusChip from '@/components/StatusChip';

interface Props {
  tasks: TaskSummary[]; selected: string[]; onSelection: (ids: string[]) => void;
  onOpen: (id: string) => void; onExport: (intent: 'draft' | 'delivery') => void;
  onSubmit: () => void; exporting: boolean; submitting: boolean; busy: boolean;
}

export default function TaskPanel({ tasks, selected, onSelection, onOpen, onExport, onSubmit, exporting, submitting, busy }: Props) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const filters: Record<string, string> = { all: '全部任务', pending: '待确认', approved: '已确认', attention: '需处理' };
  const visible = tasks.filter((task) => task.name.includes(query) && (filter === 'all' ||
    (filter === 'approved' ? task.status === 'approved' : filter === 'pending' ? task.status === 'human_pending' : ['ai_rejected', 'review_failed', 'rejected'].includes(task.status))));
  const approved = tasks.filter((t) => t.status === 'approved').length;
  const allChecked = visible.length > 0 && visible.every((t) => selected.includes(t.id));
  const chosen = tasks.filter((t) => selected.includes(t.id));
  const hiddenSelected = chosen.filter((task) => !visible.some((item) => item.id === task.id)).length;
  const deliveryReady = chosen.length > 0 && chosen.every((t) => t.status === 'approved' && !t.busy_run_id);
  const batchIds = [...new Set(visible.map((t) => t.batch_id))];
  return <section className="results-panel" aria-label="任务结果">
    <header className="results-header"><div><h2>任务结果 <span>{tasks.length}</span></h2><p>已确认 {approved} 条{tasks.length > approved ? `，还有 ${tasks.length - approved} 条待处理` : ''}</p></div>
      <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="筛选任务"><SlidersHorizontal className="size-4" /></Button></DropdownMenuTrigger>
        <DropdownMenuContent align="end">{Object.entries(filters).map(([value, label]) => <DropdownMenuItem key={value} onSelect={() => setFilter(value)}>{label}{filter === value && <span className="ml-auto">✓</span>}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu>
    </header>
    {tasks.length > 0 && <div className="result-tools"><div className="result-search"><Search className="size-3.5" /><Input aria-label="搜索任务" placeholder="搜索任务" value={query} onChange={(e) => setQuery(e.target.value)} /></div>
      <label className="select-visible"><Checkbox checked={allChecked ? true : visible.some((t) => selected.includes(t.id)) ? 'indeterminate' : false}
        disabled={!visible.length} onCheckedChange={() => onSelection(allChecked ? selected.filter((id) => !visible.some((t) => t.id === id)) : [...new Set([...selected, ...visible.map((t) => t.id)])])} />全选</label></div>}
    <div className="results-scroll">
      {batchIds.map((batchId) => {
        const batch = visible.find((task) => task.batch_id === batchId);
        return <div className="result-batch" key={batchId}>
        {batchIds.length > 1 && <div className="batch-label">{batch?.batch_name ?? '任务批次'}{batch?.batch_created_at && ` · ${new Date(batch.batch_created_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`}</div>}
        {visible.filter((t) => t.batch_id === batchId).map((task, index) => <div className={`task-row${selected.includes(task.id) ? ' is-selected' : ''}`} key={task.id}>
          <Checkbox aria-label={`选择任务 ${task.name}`} checked={selected.includes(task.id)} onCheckedChange={() => onSelection(selected.includes(task.id) ? selected.filter((id) => id !== task.id) : [...selected, task.id])} />
          <button type="button" className="task-open" onClick={() => onOpen(task.id)}>
            <span className="task-index">{String(index + 1).padStart(2, '0')}</span><span className="task-text"><strong>{task.name}</strong>
              <span className="task-metadata"><span>{task.step_count} 步</span><span>版本 {task.version_no}</span>{task.human_edited && <span>已编辑</span>}{Boolean(task.issue_count) && <span>{task.issue_count} 条审核意见</span>}</span>
              {(task.batch_comparison === 'duplicate' || task.batch_comparison === 'similar') && <span className="task-warning">{task.batch_comparison === 'duplicate' ? '步骤重复，需要调整' : '有相似线索，请留意用途与对象'}</span>}
            </span><StatusChip task={task} compact />
          </button>
        </div>)}
      </div>; })}
      {!visible.length && <div className="results-empty"><ClipboardList className="size-7" /><h3>{tasks.length ? '没有匹配的任务' : '任务将在这里出现'}</h3><p>{tasks.length ? '尝试调整关键词或筛选条件。' : '生成完成后，可逐条查看、编辑与确认。'}</p></div>}
    </div>
    <footer className="results-footer"><div className="selection-summary">{selected.length ? `已选 ${selected.length} 条任务${hiddenSelected ? `（${hiddenSelected} 条在当前筛选外）` : ''}` : '选择任务后可重新审核或导出'}{filter !== 'all' && <button onClick={() => setFilter('all')}>{filters[filter]}，清除筛选</button>}</div>
      <div className="result-actions"><Button variant="outline" disabled={!selected.length || busy || submitting || chosen.some((t) => Boolean(t.busy_run_id))} onClick={onSubmit}><ShieldCheck className="size-4" />{submitting ? '正在送审' : '重新审核所选'}</Button>
        <DropdownMenu><DropdownMenuTrigger asChild><Button disabled={!selected.length || exporting}><ArrowDownToLine className="size-4" />{exporting ? '正在导出' : '导出'}<ChevronDown className="size-3.5" /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end"><DropdownMenuLabel>导出 {selected.length} 条所选任务</DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => onExport('draft')}>导出草稿<span className="menu-hint">任意状态</span></DropdownMenuItem>
            <DropdownMenuSeparator /><DropdownMenuItem disabled={!deliveryReady} onSelect={() => onExport('delivery')}>导出交付<span className="menu-hint">仅已确认版本</span></DropdownMenuItem>
          </DropdownMenuContent></DropdownMenu>
      </div>
    </footer>
  </section>;
}
