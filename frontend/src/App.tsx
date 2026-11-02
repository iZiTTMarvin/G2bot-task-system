import { App as AntApp, Button, ConfigProvider, Modal, Typography, message } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { realClient as api } from './api';
import { newIdempotencyKey } from './api/client';
import type { SendMessageInput } from './api/client';
import type { ApiError } from './api/errors';
import type {
  AgentRole,
  AttachmentSummary,
  ChatMessage,
  Conversation,
  TaskSummary,
} from './api/types';
import ChatPanel from './components/ChatPanel';
import TaskDetailDrawer from './components/TaskDetailDrawer';
import TaskPanel from './components/TaskPanel';
import SettingsPage from './pages/SettingsPage';
import './app.css';

const { Text } = Typography;

const ROLE_TITLE: Record<AgentRole, string> = {
  generator: '生成 Agent',
  reviewer: '审核 Agent',
};

export default function App() {
  const [role, setRole] = useState<AgentRole>('generator');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<Record<AgentRole, string | null>>({
    generator: null,
    reviewer: null,
  });
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [attachments, setAttachments] = useState<AttachmentSummary[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [openTaskId, setOpenTaskId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [tick, setTick] = useState(0);

  const activeId = active[role];
  const conversation = conversations.find((item) => item.id === activeId) ?? null;

  const loadConversations = useCallback(async () => {
    const page = await api.listConversations();
    setConversations(page.items);
    return page.items;
  }, []);

  const loadAttachments = useCallback(async () => {
    const page = await api.listAttachments(1, 60);
    setAttachments(page.items);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [items, attachmentPage] = await Promise.all([
          loadConversations(),
          api.listAttachments(1, 60),
        ]);
        if (cancelled) return;
        setAttachments(attachmentPage.items);
        const next: Record<AgentRole, string | null> = { generator: null, reviewer: null };
        for (const value of ['generator', 'reviewer'] as AgentRole[]) {
          const found = items.find((item) => item.agent_role === value);
          next[value] = found ? found.id : (await api.createConversation(value)).id;
        }
        if (cancelled) return;
        await loadConversations();
        setActive(next);
      } catch (cause) {
        if (!cancelled) message.error((cause as ApiError).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadConversations]);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      setTasks([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const [messageList, taskList] = await Promise.all([
          api.listMessages(activeId),
          api.conversationTasks(activeId),
        ]);
        if (cancelled) return;
        setMessages(messageList.items);
        setTasks(taskList.items);
      } catch (cause) {
        if (!cancelled) message.error((cause as ApiError).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId, tick]);

  const runActive = useMemo(
    () => messages.some((item) => item.run && ['queued', 'running'].includes(item.run.status)),
    [messages]
  );

  useEffect(() => {
    if (!runActive) return;
    const timer = setInterval(() => setTick((value) => value + 1), 1500);
    return () => clearInterval(timer);
  }, [runActive]);

  const refresh = () => setTick((value) => value + 1);

  const send = async (input: SendMessageInput) => {
    if (!activeId) return;
    setSending(true);
    try {
      await api.sendMessage(activeId, input, newIdempotencyKey());
      refresh();
    } catch (cause) {
      message.error((cause as ApiError).message);
    } finally {
      setSending(false);
    }
  };

  const submit = async () => {
    if (!selected.length) return;
    const reviewerId = active.reviewer;
    if (!reviewerId) {
      message.warning('审核会话还没准备好，稍等一下');
      return;
    }
    setSubmitting(true);
    try {
      await api.sendMessage(
        reviewerId,
        { content: `送审 ${selected.length} 条任务`, task_ids: selected },
        newIdempotencyKey()
      );
      setSelected([]);
      setRole('reviewer');
      refresh();
    } catch (cause) {
      message.error((cause as ApiError).message);
    } finally {
      setSubmitting(false);
    }
  };

  const exportSelected = async () => {
    if (!selected.length) return;
    const chosen = tasks.filter((task) => selected.includes(task.id));
    const batchId = chosen[0]?.batch_id;
    if (!batchId) return;
    const sameBatch = chosen.filter((task) => task.batch_id === batchId);
    if (sameBatch.length !== chosen.length) {
      message.info('导出一次只覆盖同一批任务，本次先导同批的那些');
    }
    setExporting(true);
    try {
      const record = await api.createExport(
        { batch_id: batchId, task_ids: sameBatch.map((task) => task.id) },
        newIdempotencyKey()
      );
      const blob = await api.downloadExport(record.download_url);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = record.filename;
      link.click();
      URL.revokeObjectURL(url);
      message.success(`已导出 ${sameBatch.length} 条`);
    } catch (cause) {
      message.error((cause as ApiError).message);
    } finally {
      setExporting(false);
    }
  };

  const newConversation = async (value: AgentRole) => {
    try {
      const created = await api.createConversation(value);
      await loadConversations();
      setActive((current) => ({ ...current, [value]: created.id }));
      setRole(value);
      setSelected([]);
    } catch (cause) {
      message.error((cause as ApiError).message);
    }
  };

  const switchConversation = (id: string, value: AgentRole) => {
    setActive((current) => ({ ...current, [value]: id }));
    setRole(value);
    setSelected([]);
  };

  const toggle = (id: string) =>
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
    );

  const toggleAll = () =>
    setSelected((current) => (current.length === tasks.length ? [] : tasks.map((task) => task.id)));

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          borderRadius: 8,
          colorPrimary: '#3157c8',
          colorBgLayout: '#f6f7f9',
          fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
        },
      }}
    >
      <AntApp>
        <div className="workbench">
          <aside className="sidebar">
            <div className="brand">
              <span className="brand-mark">G2</span>
              <div>
                <div className="brand-name">任务系统</div>
                <div className="brand-sub">双 Agent 工作台</div>
              </div>
            </div>

            {(['generator', 'reviewer'] as AgentRole[]).map((value) => (
              <section className="conv-group" key={value}>
                <div className="conv-head">
                  <span className={`conv-role role-${value}`}>{ROLE_TITLE[value]}</span>
                  <button
                    type="button"
                    className="conv-new"
                    onClick={() => void newConversation(value)}
                  >
                    + 新会话
                  </button>
                </div>
                {conversations
                  .filter((item) => item.agent_role === value)
                  .map((item) => (
                    <button
                      type="button"
                      key={item.id}
                      className={`conv-item${activeId === item.id ? ' is-active' : ''}`}
                      onClick={() => switchConversation(item.id, value)}
                    >
                      <span className="conv-title">{item.title}</span>
                      <span className="conv-meta">
                        {item.message_count} 条 · {item.task_count} 任务
                      </span>
                    </button>
                  ))}
                {!conversations.some((item) => item.agent_role === value) && (
                  <div className="conv-empty">还没有会话</div>
                )}
              </section>
            ))}

            <section className="library">
              <div className="conv-head">
                <span className="conv-role">物料库</span>
              </div>
              {attachments.slice(0, 6).map((item) => (
                <div className="library-item" key={item.id} title={item.filename}>
                  {item.filename}
                </div>
              ))}
              {!attachments.length && <div className="conv-empty">还没上传过</div>}
            </section>

            <div className="sidebar-foot">
              <Button size="small" block onClick={() => setSettingsOpen(true)}>
                API 设置
              </Button>
            </div>
          </aside>

          <ChatPanel
            key={activeId ?? 'none'}
            api={api}
            role={role}
            conversation={conversation}
            messages={messages}
            attachments={attachments}
            sending={sending}
            onSend={send}
            onAttachmentsChanged={() => void loadAttachments()}
          />

          <TaskPanel
            tasks={tasks}
            selected={selected}
            onToggle={toggle}
            onToggleAll={toggleAll}
            onOpen={setOpenTaskId}
            onSubmit={() => void submit()}
            onExport={() => void exportSelected()}
            exporting={exporting}
            submitting={submitting}
            reviewBusy={runActive}
          />

          <TaskDetailDrawer
            key={openTaskId ?? 'closed'}
            api={api}
            taskId={openTaskId}
            onClose={() => setOpenTaskId(null)}
            onChanged={refresh}
          />
        </div>

        <Modal
          open={settingsOpen}
          title="API 设置"
          footer={null}
          width={520}
          onCancel={() => setSettingsOpen(false)}
        >
          <SettingsPage api={api} />
          <Text type="secondary" className="settings-note">
            生成与审核默认使用同一模型；换模型不会影响已有任务和版本。
          </Text>
        </Modal>
      </AntApp>
    </ConfigProvider>
  );
}
