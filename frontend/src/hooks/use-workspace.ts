import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import type { ApiClient, SendMessageInput } from '@/api/client';
import { newIdempotencyKey } from '@/api/client';
import type { ActiveRun, AgentRole, AttachmentSummary, ChatMessage, Conversation, RunActivity, TaskSummary } from '@/api/types';
import { effectiveAttachments, errorHint, isEmptyDefaultConversation } from '@/lib/presentation';
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
  const [selected, setSelected] = useState<string[]>([]);
  const [activeRun, setActiveRun] = useState<ActiveRun>({ run: null, conversation_id: null });
  const [activity, setActivity] = useState<RunActivity[]>([]);
  const [stopping, setStopping] = useState(false);
  const [tick, setTick] = useState(0);
  const lock = useRef(false);
  const pending = useRef<{ digest: string; key: string } | null>(null);
  const draftKey = activeId ?? `new-${role}`;
  const draft = drafts[draftKey] ?? EMPTY_DRAFT;
  const conversation = conversations.find((item) => item.id === activeId) ?? null;
  const messages = view?.id === activeId ? view.messages : [];
  const tasks = view?.id === activeId ? view.tasks : [];
  const activeInView = Boolean(activeId && activeRun.run && (activeRun.conversation_id === activeId ||
    tasks.some((task) => task.busy_run_id === activeRun.run?.id)));
  const busy = activeInView || messages.some((m) => m.run && ['queued', 'running'].includes(m.run.status)) ||
    tasks.some((task) => Boolean(task.busy_run_id));
  const globalBusy = Boolean(activeRun.run);
  const currentRun = (activeInView ? activeRun.run : null) ?? [...messages].reverse().find((m) => m.run)?.run ?? null;
  const interactionBusy = initializing || sending || uploading;
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
        const first = index.items.find((item) => !isEmptyDefaultConversation(item));
        if (first) { setActiveId(first.id); setRole(first.agent_role); }
      }).catch((cause: unknown) => { if (!cancelled) setIndexError((cause as Error).message); })
      .finally(() => { if (!cancelled) setInitializing(false); });
    return () => { cancelled = true; };
  }, [api]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      let nextDelay = 5000;
      try {
        const [global, messageList, taskList] = await Promise.all([
          api.getActiveRun(), activeId ? api.listMessages(activeId) : Promise.resolve(null),
          activeId ? api.conversationTasks(activeId) : Promise.resolve(null),
        ]);
        if (cancelled) return;
        setActiveRun(global);
        if (activeId && messageList && taskList) {
          setView({ id: activeId, messages: messageList.items, tasks: taskList.items });
          setSelected((current) => current.filter((id) => taskList.items.some((t) => t.id === id)));
        }
        setViewError('');
        const runInView = Boolean(activeId && global.run && (global.conversation_id === activeId ||
          taskList?.items.some((task) => task.busy_run_id === global.run?.id)));
        const run = (runInView ? global.run : null) ??
          [...(messageList?.items ?? [])].reverse().find((m) => m.run)?.run;
        if (run) {
          const events = await api.getRunActivity(run.id);
          if (!cancelled) setActivity(events.items);
        } else if (!cancelled) setActivity([]);
        nextDelay = global.run ? 1500 : 5000;
      } catch (cause) {
        if (!cancelled) setViewError((cause as Error).message);
        nextDelay = 3000;
      } finally {
        if (!cancelled) timer = window.setTimeout(() => void poll(), nextDelay);
      }
    };
    void poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [activeId, api, tick]);

  const updateDraft = (update: Partial<WorkspaceDraft>) => {
    setDrafts((current) => ({ ...current, [draftKey]: { ...(current[draftKey] ?? EMPTY_DRAFT), ...update } }));
  };

  const choose = (target: Conversation) => {
    if (interactionBusy) return;
    setActiveId(target.id); setRole(target.agent_role); setSelected([]); setViewError('');
  };

  const create = (nextRole: AgentRole = 'generator') => {
    if (interactionBusy || lock.current) return;
    setActiveId(null); setRole(nextRole); setSelected([]); setViewError(''); setActivity([]);
  };

  const send = async (override?: SendMessageInput, targetId?: string) => {
    if (interactionBusy || lock.current) return false;
    lock.current = true; setSending(true);
    const sourceDraft = draft;
    const id = targetId ?? activeId;
    try {
      const reviewText = sourceDraft.text.trim();
      const reviewFiles = sourceDraft.attachmentIds.map((fileId) => attachments.find((item) => item.id === fileId)?.filename ?? '任务文件');
      const input: SendMessageInput = override ?? (role === 'generator' ? {
        content: sourceDraft.text.trim(), attachment_ids: sourceDraft.attachmentIds,
        attachment_mode: sourceDraft.attachmentMode,
      } : { content: reviewText ? reviewText.slice(0, 20000) : `审核文件：${reviewFiles.join('、')}`.slice(0, 20000),
        pasted_text: reviewText, attachment_ids: sourceDraft.attachmentIds });
      const digest = JSON.stringify([id ?? `new-${role}`, input]);
      if (pending.current?.digest !== digest) pending.current = { digest, key: newIdempotencyKey() };
      const result = id ? await api.sendMessage(id, input, pending.current.key)
        : await api.startConversation(role, input, pending.current.key);
      if (!id) { setConversations((current) => [result.conversation, ...current]); setActiveId(result.conversation.id); }
      setActiveRun({ run: result.run, conversation_id: result.conversation.id });
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

  const stop = async () => {
    if (!activeRun.run || stopping) return;
    setStopping(true);
    try { const run = await api.cancelRun(activeRun.run.id); setActiveRun((current) => ({ ...current, run })); refresh(); }
    catch (cause) { toast.error((cause as Error).message); }
    finally { setStopping(false); }
  };

  return { api, conversations, attachments, activeId, role, conversation, messages, tasks, draft, drafts,
    initializing, indexError, viewError, hasDrafts, loading: Boolean(activeId && view?.id !== activeId),
    busy, globalBusy, activeRun, currentRun, activity, stopping, sending, uploading, interactionBusy, selected, setSelected,
    refresh, refreshIndex, choose, create, updateDraft, send, upload, retry, rename, stop };
}

export type Workspace = ReturnType<typeof useWorkspace>;
