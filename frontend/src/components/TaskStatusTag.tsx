import { Tag } from 'antd';
import type { TaskStatus } from '../api/types';
import { STATUS_LABEL } from '../api/types';

const COLORS: Partial<Record<TaskStatus, string>> = {
  ai_reviewing: 'processing', human_pending: 'blue', ai_rejected: 'orange',
  review_failed: 'red', approved: 'green', rejected: 'red',
};

export default function TaskStatusTag({ status }: { status: TaskStatus }) {
  return <Tag color={COLORS[status]}>{STATUS_LABEL[status]}</Tag>;
}
