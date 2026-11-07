// 请求结构见 docs/openapi.json 0.3.0，业务语义见 docs/当前行为契约.md。

export type TaskStatus =
  | 'pending_review'
  | 'ai_reviewing'
  | 'human_pending'
  | 'ai_rejected'
  | 'review_failed'
  | 'approved'
  | 'rejected';

export type TaskMode = 'auto' | 'standard' | 'long';

// 界面上只露四态：生成中 / 审核中 / 待确认 / 已确认（其余折叠进对应阶段）
export type TaskStage = 'generating' | 'reviewing' | 'reviewed' | 'confirmed' | 'error';

export interface ErrorInfo {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string;
}

export interface ApiErrorShape {
  error: ErrorInfo;
}

export interface Material {
  name: string;
  quantity: number;
}

export interface TaskContent {
  name: string;
  steps: string[];
  materials: Material[];
}

export interface ValidationIssue {
  code: string;
  severity: 'error' | 'review_required' | 'warning';
  message: string;
  step_no: number | null;
  rule_id: string | null;
}

export interface ValidationReport {
  status: 'passed' | 'failed';
  issues: ValidationIssue[];
  checked_at: string;
  rule_snapshot_id: string;
}

export interface TaskVersion {
  id: string;
  task_id: string;
  version_no: number;
  parent_version_id: string | null;
  author_type: 'ai' | 'human' | 'ai_revision';
  content: TaskContent;
  change_note: string;
  change_category: ChangeCategory;
  validation: ValidationReport;
  run_id: string | null;
  created_at: string;
}

export interface ReviewIssue {
  severity: 'error' | 'warning';
  step_no: number | null;
  rule_id: string | null;
  quote: string;
  message: string;
  suggestion: string;
}

export interface Review {
  id: string;
  task_id: string;
  task_version_id: string;
  reviewer_id: string;
  run_id: string;
  verdict: 'pass' | 'needs_changes';
  issues: ReviewIssue[];
  summary: string;
  created_at: string;
}

export interface HumanDecision {
  id: string;
  task_id: string;
  task_version_id: string;
  decision: 'approve' | 'reject';
  reason: string;
  resolutions: Record<string, string>;
  change_category: ChangeCategory;
  created_at: string;
}

export interface TaskSummary {
  id: string;
  batch_id: string;
  batch_name?: string;
  batch_created_at?: string;
  seq: number;
  name: string;
  step_count: number;
  version_no: number;
  status: TaskStatus;
  stage?: TaskStage;
  revision: number;
  human_edited: boolean;
  batch_comparison?: 'similar' | 'duplicate' | null;
  busy_run_id: string | null;
  created_at: string;
  updated_at: string;
  review_verdict?: 'pass' | 'needs_changes' | null;
  review_summary?: string | null;
  issue_count?: number;
}

export interface TaskDetail {
  summary: TaskSummary;
  current_version: TaskVersion;
  latest_review: Review | null;
  latest_decision: HumanDecision | null;
  batch_issues: ValidationIssue[];
  last_error: ErrorInfo | null;
  can_decide: boolean;
  ai_review_matches_current_version: boolean;
}

export interface TaskCounts {
  pending_review: number;
  ai_reviewing: number;
  human_pending: number;
  ai_rejected: number;
  review_failed: number;
  approved: number;
  rejected: number;
}

export interface TaskPage {
  items: TaskSummary[];
  total: number;
  page: number;
  page_size: number;
  status_counts: TaskCounts;
}

export interface VersionList {
  items: TaskVersion[];
}

export interface ReviewList {
  items: Review[];
}

export interface DecisionList {
  items: HumanDecision[];
}

export interface DecisionResult {
  decision: HumanDecision;
  task: TaskDetail;
}

export interface AttachmentSummary {
  id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  text_length: number;
  content_hash: string;
  created_at: string;
}

export interface Attachment extends AttachmentSummary {
  parsed_text: string;
  inventory: InventoryItem[];
}

export type ChangeCategory = 'capability' | 'purpose' | 'terminal_state' | 'wording' | 'materials' | 'duplicate' | 'other';

export interface InventoryItem {
  name: string;
  category: string;
  quantity: number | null;
  available_sets: number | null;
  color: string;
  scene: string;
  initial_position: string;
  grippable: boolean | null;
  moving_container: boolean | null;
  source_attachment_id: string;
  source_row: number;
  verification_status: string;
}

export interface AttachmentPage {
  items: AttachmentSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface Batch {
  id: string;
  name: string | null;
  goal: string;
  task_count: number;
  task_mode: TaskMode;
  reference_text: string;
  attachment_ids: string[];
  material_snapshot: InventoryItem[];
  rule_snapshot_id: string;
  task_counts: TaskCounts;
  latest_run_id: string | null;
  can_generate: boolean;
  created_at: string;
}

export interface BatchPage {
  items: Batch[];
  total: number;
  page: number;
  page_size: number;
}

export interface RunProgress {
  total: number;
  completed: number;
  failed: number;
}

export type RunKind = 'generate_batch' | 'review_task' | 'revise_task' | 'review_batch';

export interface Run {
  id: string;
  batch_id: string;
  task_id: string | null;
  task_ids: string[];
  kind: RunKind;
  stage: 'queued' | 'generating' | 'validating' | 'reviewing' | 'done';
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'interrupted' | 'cancelled';
  progress: RunProgress;
  error: ErrorInfo | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  cancel_requested_at?: string | null;
}

export interface RunActivity { id: string; time: string; label: string }
export interface ActiveRun { run: Run | null; conversation_id: string | null }

export type AgentRole = 'generator' | 'reviewer';

export interface Conversation {
  id: string;
  agent_role: AgentRole;
  title: string;
  attachment_ids: string[];
  message_count: number;
  task_count: number;
  created_at: string;
  updated_at: string;
}

export interface ConversationPage {
  items: Conversation[];
  total: number;
  page: number;
  page_size: number;
}

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: 'user' | 'agent';
  content: string;
  batch_id: string | null;
  run_id: string | null;
  attachments: string[];
  task_ids: string[];
  run: Run | null;
  created_at: string;
}

export interface MessageList {
  items: ChatMessage[];
}

export interface ConversationTasks {
  items: TaskSummary[];
  batch_ids: string[];
}

export interface Settings {
  api_format: 'openai' | 'anthropic';
  base_url: string;
  generation_model: string;
  review_model: string;
  api_key_set: boolean;
}

export interface ExportRecord {
  id: string;
  intent: 'draft' | 'delivery';
  batch_id: string;
  versions: { task_id: string; version_id: string }[];
  filename: string;
  download_url: string;
  created_at: string;
}

export interface Health {
  status: string;
  database: string;
  contract_version: string;
}

export const STATUS_ORDER: TaskStatus[] = [
  'human_pending',
  'ai_rejected',
  'review_failed',
  'pending_review',
  'ai_reviewing',
  'approved',
  'rejected',
];

export const STATUS_LABEL: Record<TaskStatus, string> = {
  pending_review: '待 AI 审核',
  ai_reviewing: 'AI 审核中',
  human_pending: '待确认',
  ai_rejected: '需人工处理',
  review_failed: '审核失败',
  approved: '已确认',
  rejected: '已驳回',
};

export const STAGE_ORDER: TaskStage[] = ['generating', 'reviewing', 'reviewed', 'confirmed', 'error'];

export const STAGE_LABEL: Record<TaskStage, string> = {
  generating: '生成中',
  reviewing: '审核中',
  reviewed: '待确认',
  confirmed: '已确认',
  error: '需处理',
};

const STATUS_TO_STAGE: Record<TaskStatus, TaskStage> = {
  pending_review: 'generating',
  ai_reviewing: 'reviewing',
  human_pending: 'reviewed',
  ai_rejected: 'reviewed',
  review_failed: 'error',
  approved: 'confirmed',
  rejected: 'error',
};

export function stageOf(task: { status: TaskStatus; stage?: TaskStage }): TaskStage {
  return task.stage ?? STATUS_TO_STAGE[task.status];
}
