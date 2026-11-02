import { STAGE_LABEL, stageOf } from '../api/types';
import type { TaskStage, TaskStatus } from '../api/types';

interface Props {
  task: { status: TaskStatus; stage?: TaskStage };
  compact?: boolean;
}

export default function StatusChip({ task, compact }: Props) {
  const stage = stageOf(task);
  return (
    <span className={`chip chip-${stage}${compact ? ' chip-compact' : ''}`}>
      {STAGE_LABEL[stage]}
    </span>
  );
}
