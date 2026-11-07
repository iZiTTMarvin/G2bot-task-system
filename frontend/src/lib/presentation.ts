import type { ChatMessage, Conversation, ErrorInfo, ValidationIssue } from '../api/types.ts';

export function isEmptyDefaultConversation(conversation: Conversation): boolean {
  return conversation.message_count === 0 && conversation.task_count === 0 &&
    conversation.attachment_ids.length === 0 &&
    ['新的生成会话', '新的审核会话', '新的会话'].includes(conversation.title);
}

export function visibleMessages(messages: ChatMessage[]): ChatMessage[] {
  const lastAgent = new Map<string, string>();
  for (const message of messages) {
    if (message.role === 'agent' && message.run_id) lastAgent.set(message.run_id, message.id);
  }
  return messages.filter((message) => message.role !== 'agent' || !message.run_id ||
    lastAgent.get(message.run_id) === message.id);
}

export function needsRunResult(message: ChatMessage, messages: ChatMessage[]): boolean {
  return message.role === 'user' && Boolean(message.run) &&
    !messages.some((other) => other.role === 'agent' && other.run_id === message.run_id);
}

export function errorHint(error: Pick<ErrorInfo, 'code' | 'message'>): string {
  if (/404/.test(error.message)) return '模型接口未找到，请检查服务地址与 API 格式。';
  if (error.code === 'MODEL_TIMEOUT') return '模型响应超时。原要求与资料已保留，可以重试。';
  if (error.code === 'MODEL_AUTH_ERROR') return '模型服务未接受认证，请检查 API Key 与访问权限。';
  if (error.code === 'MODEL_RATE_LIMIT') return '模型服务请求过于频繁，请稍后重试。';
  if (error.code === 'REVISION_CONFLICT') return '任务已被更新。你的修改仍在，请先查看最新版本。';
  return error.message;
}

export function effectiveAttachments(current: string[], selected: string[], mode = 'inherit'): string[] {
  if (mode === 'clear') return [];
  if (mode === 'append') return [...new Set([...current, ...selected])];
  if (mode === 'replace' || selected.length) return selected;
  return current;
}

export function collectResolutions(required: ValidationIssue[], checked: Record<string, boolean>,
  commonNote: string, individual: Record<string, string>): Record<string, string> {
  const result: Record<string, string> = {};
  for (const issue of required) {
    const note = (individual[issue.code] || commonNote).trim();
    if (checked[issue.code] && note) result[issue.code] = note;
  }
  return result;
}

export function shortTime(value: string): string {
  return new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

export function taskCategory(code: string): string {
  if (code.startsWith('INVENTORY_')) return `库存：${code.slice('INVENTORY_'.length)}`;
  if (code.startsWith('MATERIAL_EVIDENCE_')) return `物料：${code.slice('MATERIAL_EVIDENCE_'.length)}`;
  return { PURPOSE: '真实用途', INITIAL_STATE: '初始条件', TERMINAL_STATE: '任务终态',
    SITE: '现场条件', WORKLOAD: '实际工作量', CLEANING: '清洁依据' }[code] ?? '核验项';
}
