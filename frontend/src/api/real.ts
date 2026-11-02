// 真实 API 客户端：只使用相对路径 /api/v1，开发时由 Vite 代理转发。
import type { ApiClient } from './client';
import { ApiError, throwFromResponse } from './errors';
import type {
  Attachment,
  AttachmentPage,
  Batch,
  BatchPage,
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
  TaskDetail,
  TaskPage,
  VersionList,
} from './types';

async function request<T>(
  method: string,
  path: string,
  options: { json?: unknown; key?: string; form?: FormData } = {}
): Promise<T> {
  const headers: Record<string, string> = {};
  if (options.key) headers['Idempotency-Key'] = options.key;
  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form;
  } else if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.json);
  }
  let resp: Response;
  try {
    resp = await fetch(`/api/v1${path}`, { method, headers, body });
  } catch {
    throw new ApiError('NETWORK_ERROR', '网络请求失败：服务未启动或已断开', {});
  }
  if (resp.status === 204) return undefined as T;
  const text = await resp.text();
  let parsed: unknown;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      if (!resp.ok) throwFromResponse(resp.status, undefined);
      throw new ApiError('NETWORK_ERROR', `服务返回了非 JSON 内容（HTTP ${resp.status}）`, {});
    }
  }
  if (!resp.ok) throwFromResponse(resp.status, parsed);
  return parsed as T;
}

export const realClient: ApiClient = {
  getHealth: () => request<Health>('GET', '/health'),
  getSettings: () => request<Settings>('GET', '/settings'),
  updateSettings: (payload) => request<Settings>('PUT', '/settings', { json: payload }),

  uploadAttachment: async (file) => {
    const form = new FormData();
    form.append('file', file);
    return request<Attachment>('POST', '/attachments', { form });
  },
  listAttachments: (page = 1, pageSize = 40) =>
    request<AttachmentPage>('GET', `/attachments?page=${page}&page_size=${pageSize}`),
  getAttachment: (id) => request<Attachment>('GET', `/attachments/${id}`),

  createBatch: (input, key) => request<Batch>('POST', '/batches', { json: input, key }),
  listBatches: (page = 1, pageSize = 20) =>
    request<BatchPage>('GET', `/batches?page=${page}&page_size=${pageSize}`),
  getBatch: (id) => request<Batch>('GET', `/batches/${id}`),
  generateBatch: (batchId, key) =>
    request<Run>('POST', `/batches/${batchId}/generate`, { json: {}, key }),

  getRun: (runId) => request<Run>('GET', `/runs/${runId}`),

  createConversation: (agentRole, title) =>
    request<Conversation>('POST', '/conversations', {
      json: { agent_role: agentRole, title: title ?? null },
    }),
  listConversations: (agentRole) =>
    request<ConversationPage>(
      'GET',
      `/conversations?page_size=100${agentRole ? `&agent_role=${agentRole}` : ''}`
    ),
  getConversation: (id) => request<Conversation>('GET', `/conversations/${id}`),
  renameConversation: (id, title) =>
    request<Conversation>('PATCH', `/conversations/${id}`, { json: { title } }),
  deleteConversation: (id) => request<void>('DELETE', `/conversations/${id}`),
  listMessages: (id) => request<MessageList>('GET', `/conversations/${id}/messages`),
  conversationTasks: (id) => request<ConversationTasks>('GET', `/conversations/${id}/tasks`),
  sendMessage: (id, input, key) =>
    request('POST', `/conversations/${id}/messages`, { json: input, key }),
  submitTasks: (taskIds, key) =>
    request<Run>('POST', '/tasks/submit', { json: { task_ids: taskIds }, key }),

  listTasks: (params) => {
    const qs = new URLSearchParams();
    if (params.batch_id) qs.set('batch_id', params.batch_id);
    if (params.status) qs.set('status', params.status);
    if (params.q) qs.set('q', params.q);
    qs.set('page', String(params.page ?? 1));
    qs.set('page_size', String(params.page_size ?? 20));
    return request<TaskPage>('GET', `/tasks?${qs.toString()}`);
  },
  getTask: (taskId) => request<TaskDetail>('GET', `/tasks/${taskId}`),
  listVersions: (taskId) => request<VersionList>('GET', `/tasks/${taskId}/versions`),
  saveVersion: (taskId, payload, key) =>
    request<TaskDetail>('POST', `/tasks/${taskId}/versions`, { json: payload, key }),
  listReviews: (taskId) => request<ReviewList>('GET', `/tasks/${taskId}/reviews`),
  listDecisions: (taskId) => request<DecisionList>('GET', `/tasks/${taskId}/decisions`),
  decide: (taskId, payload, key) =>
    request<DecisionResult>('POST', `/tasks/${taskId}/decisions`, { json: payload, key }),
  reviewTask: (taskId, payload, key) =>
    request<Run>('POST', `/tasks/${taskId}/review`, { json: payload, key }),
  reviseTask: (taskId, payload, key) =>
    request<Run>('POST', `/tasks/${taskId}/revise`, { json: payload, key }),

  createExport: (payload, key) => request<ExportRecord>('POST', '/exports', { json: payload, key }),
  downloadExport: async (url) => {
    let resp: Response;
    try {
      resp = await fetch(url);
    } catch {
      throw new ApiError('NETWORK_ERROR', '下载请求失败：服务未启动或已断开', {});
    }
    if (!resp.ok) {
      const text = await resp.text();
      let body: unknown;
      try {
        body = text ? JSON.parse(text) : undefined;
      } catch {
        body = undefined;
      }
      throwFromResponse(resp.status, body);
    }
    return resp.blob();
  },
};
