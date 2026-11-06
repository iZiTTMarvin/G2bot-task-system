import { ApiError } from './errors';
import type {
  AgentRole,
  Attachment,
  AttachmentPage,
  Batch,
  BatchPage,
  ChatMessage,
  ChangeCategory,
  Conversation,
  ConversationPage,
  ConversationTasks,
  DecisionList,
  DecisionResult,
  ExportRecord,
  Health,
  MessageList,
  ReviewList,
  Run,
  Settings,
  TaskContent,
  TaskDetail,
  TaskPage,
  VersionList,
} from './types';

export interface BatchCreateInput {
  name?: string;
  goal: string;
  task_count: number;
  task_mode: string;
  reference_text: string;
  attachment_ids: string[];
  conversation_id?: string;
}

export interface SendMessageInput {
  content?: string;
  attachment_ids?: string[];
  attachment_mode?: 'inherit' | 'replace' | 'append' | 'clear';
  task_ids?: string[];
  pasted_text?: string;
}

export interface SendMessageResult {
  message: ChatMessage;
  run: Run;
  conversation: Conversation;
  task_ids?: string[];
}

export interface ApiClient {
  getHealth(): Promise<Health>;
  getSettings(): Promise<Settings>;
  updateSettings(payload: {
    api_format?: 'openai' | 'anthropic';
    base_url: string;
    generation_model: string;
    review_model?: string;
    api_key?: string;
  }): Promise<Settings>;

  uploadAttachment(file: File): Promise<Attachment>;
  listAttachments(page?: number, pageSize?: number): Promise<AttachmentPage>;
  getAttachment(id: string): Promise<Attachment>;

  createBatch(input: BatchCreateInput, key: string): Promise<Batch>;
  listBatches(page?: number, pageSize?: number): Promise<BatchPage>;
  getBatch(id: string): Promise<Batch>;
  generateBatch(batchId: string, key: string): Promise<Run>;

  getRun(runId: string): Promise<Run>;

  createConversation(agentRole: AgentRole, title?: string): Promise<Conversation>;
  listConversations(agentRole?: AgentRole): Promise<ConversationPage>;
  getConversation(id: string): Promise<Conversation>;
  renameConversation(id: string, title: string): Promise<Conversation>;
  deleteConversation(id: string): Promise<void>;
  listMessages(conversationId: string): Promise<MessageList>;
  conversationTasks(conversationId: string): Promise<ConversationTasks>;
  sendMessage(conversationId: string, input: SendMessageInput, key: string): Promise<SendMessageResult>;
  submitTasks(taskIds: string[], key: string): Promise<Run>;

  listTasks(params: {
    batch_id?: string;
    status?: string;
    q?: string;
    page?: number;
    page_size?: number;
  }): Promise<TaskPage>;
  getTask(taskId: string): Promise<TaskDetail>;
  listVersions(taskId: string): Promise<VersionList>;
  saveVersion(
    taskId: string,
    payload: { expected_revision: number; content: TaskContent; change_note?: string; change_category?: ChangeCategory },
    key: string
  ): Promise<TaskDetail>;
  listReviews(taskId: string): Promise<ReviewList>;
  listDecisions(taskId: string): Promise<DecisionList>;
  decide(
    taskId: string,
    payload: {
      expected_revision: number;
      version_id: string;
      decision: 'approve' | 'reject';
      reason?: string;
      resolutions?: Record<string, string>;
      change_category?: ChangeCategory;
    },
    key: string
  ): Promise<DecisionResult>;
  reviewTask(
    taskId: string,
    payload: { expected_revision: number; version_id: string },
    key: string
  ): Promise<Run>;
  reviseTask(
    taskId: string,
    payload: { expected_revision: number; version_id: string; feedback: string },
    key: string
  ): Promise<Run>;

  createExport(
    payload: { batch_id: string; task_ids: string[]; intent?: 'draft' | 'delivery' },
    key: string
  ): Promise<ExportRecord>;
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
