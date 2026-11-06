import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import type { ApiClient, SendMessageInput } from '@/api/client';
import { newIdempotencyKey } from '@/api/client';
import type { AgentRole, AttachmentSummary, ChatMessage, Conversation, TaskSummary } from '@/api/types';
import { effectiveAttachments, errorHint } from '@/lib/presentation';
import { ApiError } from '@/api/errors';

export interface WorkspaceDraft {
  text: string;
  attachmentIds: string[];
  attachmentMode: NonNullable<SendMessageInput['attachment_mode']>;
}
const EMPTY_DRAFT: WorkspaceDraft = { text: '', attachmentIds: [], attachmentMode: 'inherit' };

export function useWorkspace(api: ApiClient) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [attachments, setAttachments] = useState<AttachmentSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [role, setRole] = useState<AgentRole>('generator');
  const [initializing, setInitializing] = useState(true);
  const [indexError, setIndexError] = useState('');
  const [viewError, setViewError] = useState('');
  const [view, setView] = useState<{ id: string; messages: ChatMessage[]; tasks: TaskSummary[] } | null>(null);
  const [drafts, setDrafts] = useState<Record<string, WorkspaceDraft>>({});
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [tick, setTick] = useState(0);
  const lock = useRef(false);
  const pending = useRef<{ digest: string; key: string } | null>(null);
  const draftKey = activeId ?? `new-${role}`;
  const draft = drafts[draftKey] ?? EMPTY_DRAFT;
  const conversation = conversations.find((item) => item.id === activeId) ?? null;
  const messages = view?.id === activeId ? view.messages : [];
  const tasks = view?.id === activeId ? view.tasks : [];
  const busy = messages.some((m) => m.run && ['queued', 'running'].includes(m.run.status)) ||
    tasks.some((task) => Boolean(task.busy_run_id));
  const interactionBusy = initializing || sending || uploading || switching;
  const hasDrafts = Object.values(drafts).some((value) => Boolean(value.text.trim()) || value.attachmentIds.length > 0 || value.attachmentMode !== 'inherit');
  const refresh = useCallback(() => setTick((value) => value + 1), []);

  const refreshIndex = useCallback(async () => {
    const [index, library] = await Promise.all([api.listConversations(), api.listAttachments(1, 100)]);
    setConversations(index.items);
    setAttachments(library.items);
    setIndexError('');
    return index.items;
  }, [api]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listConversations(), api.listAttachments(1, 100)])
      .then(([index, library]) => {
        if (cancelled) return;
        setConversations(index.items);
        setAttachments(library.items);
        const first = index.items[0];
        if (first) { setActiveId(first.id); setRole(first.agent_role); }
      }).catch((cause: unknown) => { if (!cancelled) setIndexError((cause as Error).message); })
      .finally(() => { if (!cancelled) setInitializing(false); });
    return () => { cancelled = true; };
  }, [api]);

  useEffect(() => {
    if (!activeId) return;
    let cancelled = false;
    Promise.all([api.listMessages(activeId), api.conversationTasks(activeId)])
      .then(([messageList, taskList]) => {
        if (cancelled) return;
        setView({ id: activeId, messages: messageList.items, tasks: taskList.items });
        setSelected((current) => current.filter((id) => taskList.items.some((t) => t.id === id)));
        setViewError('');
      }).catch((cause: unknown) => { if (!cancelled) setViewError((cause as Error).message); });
    return () => { cancelled = true; };
  }, [activeId, api, tick]);

  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(refresh, 1500);
    return () => window.clearInterval(timer);
  }, [busy, refresh]);

  const updateDraft = (update: Partial<WorkspaceDraft>) => {
    setDrafts((current) => ({ ...current, [draftKey]: { ...(current[draftKey] ?? EMPTY_DRAFT), ...update } }));
  };

  const choose = (target: Conversation) => {
    if (interactionBusy) return;
    setActiveId(target.id); setRole(target.agent_role); setSelected([]); setViewError('');
  };

  const create = async (nextRole: AgentRole = 'generator') => {
    if (interactionBusy || lock.current) return;
    lock.current = true; setSwitching(true);
    try {
      const created = await api.createConversation(nextRole);
      setConversations((current) => [created, ...current]);
      setActiveId(created.id); setRole(nextRole); setSelected([]); setViewError('');
    } catch (cause) { toast.error((cause as Error).message); }
    finally { lock.current = false; setSwitching(false); }
  };

  const send = async (override?: SendMessageInput, targetId?: string) => {
    if (interactionBusy || lock.current) return false;
    lock.current = true; setSending(true);
    const sourceDraft = draft;
    let id = targetId ?? activeId;
    try {
      if (!id) {
        const created = await api.createConversation(role);
        id = created.id;
        setConversations((current) => [created, ...current]);
        setDrafts((current) => ({ ...current, [created.id]: sourceDraft }));
        setActiveId(created.id);
      }
      const input: SendMessageInput = override ?? (role === 'generator' ? {
        content: sourceDraft.text.trim(), attachment_ids: sourceDraft.attachmentIds,
        attachment_mode: sourceDraft.attachmentMode,
      } : { content: '审核并优化任务', pasted_text: sourceDraft.text.trim(), attachment_ids: sourceDraft.attachmentIds });
      const digest = JSON.stringify([id, input]);
      if (pending.current?.digest !== digest) pending.current = { digest, key: newIdempotencyKey() };
      const result = await api.sendMessage(id, input, pending.current.key);
      pending.current = null;
      setConversations((current) => current.map((item) => item.id === result.conversation.id ? result.conversation : item));
      if (!override) setDrafts((current) => ({ ...current, [draftKey]: EMPTY_DRAFT, [result.conversation.id]: EMPTY_DRAFT }));
      refresh();
      return true;
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : new ApiError('NETWORK_ERROR', (cause as Error).message);
      toast.error(errorHint(error));
      return false;
    } finally { lock.current = false; setSending(false); }
  };

  const upload = async (file: File) => {
    if (interactionBusy) return;
    if (file.size > 5 * 1024 * 1024) { toast.error('单个文件不能超过 5 MB'); return; }
    if (!/\.(txt|md|csv|xlsx)$/i.test(file.name)) { toast.error('支持 TXT、MD、CSV、XLSX 文件'); return; }
    setUploading(true);
    try {
      const attachment = await api.uploadAttachment(file);
      setAttachments((current) => [attachment, ...current.filter((a) => a.id !== attachment.id)]);
      setDrafts((current) => {
        const source = current[draftKey] ?? EMPTY_DRAFT;
        const ids = effectiveAttachments(conversation?.attachment_ids ?? [], source.attachmentIds, source.attachmentMode);
        return { ...current, [draftKey]: { ...source, attachmentMode: 'replace', attachmentIds: [...ids, attachment.id] } };
      });
      toast.success(`已添加 ${attachment.filename}`);
    } catch (cause) { toast.error((cause as Error).message); }
    finally { setUploading(false); }
  };

  const retry = async (message: ChatMessage) => {
    const source = messages.find((m) => m.role === 'user' && m.run_id === message.run_id);
    if (!source) { toast.error('找不到原请求，请重新输入要求'); return; }
    const input: SendMessageInput = role === 'generator'
      ? { content: source.content, attachment_ids: source.attachments, attachment_mode: 'replace' }
      : { content: source.content, task_ids: source.task_ids.length ? source.task_ids : message.run?.task_ids ?? [] };
    await send(input);
  };

  const rename = async (id: string, title: string) => {
    const next = await api.renameConversation(id, title);
    setConversations((current) => current.map((c) => c.id === id ? next : c));
  };

  return { api, conversations, attachments, activeId, role, conversation, messages, tasks, draft,
    initializing, indexError, viewError, hasDrafts, loading: Boolean(activeId && view?.id !== activeId),
    busy, sending, uploading, switching, interactionBusy, selected, setSelected,
    refresh, refreshIndex, choose, create, updateDraft, send, upload, retry, rename };
}

export type Workspace = ReturnType<typeof useWorkspace>;
