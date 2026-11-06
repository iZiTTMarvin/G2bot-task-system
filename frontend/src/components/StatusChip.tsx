import { CheckCircle2, Circle, CircleAlert, Loader2, XCircle } from 'lucide-react';
import type { TaskSummary } from '@/api/types';

export default function StatusChip({ task, compact = false }: { task: Pick<TaskSummary, 'status'>; compact?: boolean }) {
  const states = {
    pending_review: { label: '待审核', Icon: Circle, tone: 'neutral' },
    ai_reviewing: { label: '审核中', Icon: Loader2, tone: 'active' },
    human_pending: { label: '待确认', Icon: Circle, tone: 'neutral' },
    ai_rejected: { label: '需修改', Icon: CircleAlert, tone: 'warning' },
    review_failed: { label: '审核失败', Icon: CircleAlert, tone: 'danger' },
    approved: { label: '已确认', Icon: CheckCircle2, tone: 'success' },
    rejected: { label: '已驳回', Icon: XCircle, tone: 'danger' },
  } as const;
  const { label, Icon, tone } = states[task.status];
  return <span className={`status-chip tone-${tone}${compact ? ' is-compact' : ''}`}><Icon className={`size-3.5${task.status === 'ai_reviewing' ? ' animate-spin' : ''}`} aria-hidden="true" />{label}</span>;
}
