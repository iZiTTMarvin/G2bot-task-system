// API 门面：mock 与真实服务实现同一接口；组件只依赖这里。
import { ApiError } from './errors';

export interface BatchCreateInput {
  name: string;
  goal: string;
  task_count: number;
  task_mode: string;
  reference_text: string;
  attachment_ids: string[];
}

export interface ApiClient {
  getHealth(): Promise<{ status: string; database: string; contract_version: string }>;
  getSettings(): Promise<import('./types').Settings>;
  updateSettings(payload: {
    base_url: string;
    generation_model: string;
    review_model: string;
    api_key?: string;
  }): Promise<import('./types').Settings>;

  uploadAttachment(file: File): Promise<import('./types').Attachment>;
  listAttachments(page?: number, pageSize?: number): Promise<import('./types').AttachmentPage>;
  getAttachment(id: string): Promise<import('./types').Attachment>;

  createBatch(input: BatchCreateInput, key: string): Promise<import('./types').Batch>;
  listBatches(page?: number, pageSize?: number): Promise<import('./types').BatchPage>;
  getBatch(id: string): Promise<import('./types').Batch>;
  generateBatch(batchId: string, key: string): Promise<import('./types').Run>;

  getRun(runId: string): Promise<import('./types').Run>;

  listTasks(params: {
    batch_id?: string;
    status?: string;
    q?: string;
    page?: number;
    page_size?: number;
  }): Promise<import('./types').TaskPage>;
  getTask(taskId: string): Promise<import('./types').TaskDetail>;
  listVersions(taskId: string): Promise<import('./types').VersionList>;
  saveVersion(
    taskId: string,
    payload: { expected_revision: number; content: import('./types').TaskContent; change_note?: string },
    key: string
  ): Promise<import('./types').TaskDetail>;
  listReviews(taskId: string): Promise<import('./types').ReviewList>;
  listDecisions(taskId: string): Promise<import('./types').DecisionList>;
  decide(
    taskId: string,
    payload: {
      expected_revision: number;
      version_id: string;
      decision: 'approve' | 'reject';
      reason?: string;
    },
    key: string
  ): Promise<import('./types').DecisionResult>;
  reviewTask(
    taskId: string,
    payload: { expected_revision: number; version_id: string },
    key: string
  ): Promise<import('./types').Run>;
  reviseTask(
    taskId: string,
    payload: { expected_revision: number; version_id: string; feedback: string },
    key: string
  ): Promise<import('./types').Run>;

  createExport(
    payload: { batch_id: string; task_ids: string[] },
    key: string
  ): Promise<import('./types').ExportRecord>;
  downloadExport(url: string): Promise<Blob>;
}

export function newIdempotencyKey(): string {
  const uuid =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return uuid;
}

export async function parseError(e: unknown): Promise<ApiError> {
  if (e instanceof ApiError) return e;
  return new ApiError('NETWORK_ERROR', '网络请求失败，请检查服务是否启动', {});
}

export { ApiError };
