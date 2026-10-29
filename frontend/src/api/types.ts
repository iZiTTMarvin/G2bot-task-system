// 与 docs/openapi.json 0.1.0 对齐的契约类型

export type TaskStatus =
  | 'pending_review'
  | 'ai_reviewing'
  | 'human_pending'
  | 'ai_rejected'
  | 'review_failed'
  | 'approved'
  | 'rejected';

export type TaskMode = 'standard' | 'long';

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
  severity: 'error' | 'warning';
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
  created_at: string;
}

export interface TaskSummary {
  id: string;
  batch_id: string;
  seq: number;
  name: string;
  step_count: number;
  version_no: number;
  status: TaskStatus;
  revision: number;
  human_edited: boolean;
  busy_run_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskDetail {
  summary: TaskSummary;
  current_version: TaskVersion;
  latest_review: Review | null;
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

export interface Run {
  id: string;
  batch_id: string;
  task_id: string | null;
  task_ids: string[];
  kind: 'generate_batch' | 'review_task' | 'revise_task';
  stage: 'queued' | 'generating' | 'validating' | 'reviewing' | 'done';
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'interrupted';
  progress: RunProgress;
  error: ErrorInfo | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
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
  human_pending: '待人工审核',
  ai_rejected: '需人工处理',
  review_failed: '审核失败',
  approved: '已通过',
  rejected: '人工驳回',
};
