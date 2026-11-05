import { Alert, Button, Input, Modal, Select, Spin, Upload, message } from 'antd';
import { useEffect, useRef, useState } from 'react';
import type { ApiClient, SendMessageInput } from '../api/client';
import type { ApiError } from '../api/errors';
import type { AgentRole, AttachmentSummary, ChatMessage, Conversation } from '../api/types';

interface Props {
  api: ApiClient;
  role: AgentRole;
  conversation: Conversation | null;
  messages: ChatMessage[];
  attachments: AttachmentSummary[];
  sending: boolean;
  onSend: (input: SendMessageInput) => Promise<void>;
  onAttachmentsChanged: () => void;
}

const ROLE_NAME: Record<AgentRole, string> = {
  generator: '生成 Agent',
  reviewer: '审核 Agent',
};

const STAGE_TEXT: Record<string, string> = {
  queued: '排队中',
  generating: '正在生成',
  validating: '正在校验',
  reviewing: '正在审核',
  done: '完成',
};

function runLine(message: ChatMessage): string | null {
  const run = message.run;
  if (!run) return null;
  if (run.status === 'queued' || run.status === 'running') {
    const total = Math.max(run.progress.total, 1);
    const done = run.progress.completed;
    return `${STAGE_TEXT[run.stage] ?? '处理中'} ${done}/${total}`;
  }
  if (run.status === 'failed' || run.status === 'interrupted') {
    return run.error?.message ?? '这次没跑完';
  }
  return null;
}

export default function ChatPanel({
  api,
  role,
  conversation,
  messages,
  attachments,
  sending,
  onSend,
  onAttachmentsChanged,
}: Props) {
  const [text, setText] = useState('');
  const [attachmentIds, setAttachmentIds] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pastedText, setPastedText] = useState('');
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [messages.length, sending]);

  const send = async () => {
    const value = text.trim();
    if (!value && !attachmentIds.length) return;
    await onSend({ content: value, attachment_ids: attachmentIds });
    setText('');
  };

  const sendPasted = async () => {
    const value = pastedText.trim();
    if (!value) return;
    await onSend({ content: '按 Skill 改一下这段任务', pasted_text: value });
    setPasteOpen(false);
    setPastedText('');
  };

  const upload = async (file: File) => {
    setUploading(true);
    try {
      const attachment = await api.uploadAttachment(file);
      setAttachmentIds((current) => [...current, attachment.id]);
      onAttachmentsChanged();
      message.success(`已加入物料库：${attachment.filename}`);
    } catch (cause) {
      message.error((cause as ApiError).message);
    } finally {
      setUploading(false);
    }
  };

  const placeholder =
    role === 'generator'
      ? '说清楚要做什么，例如：用「居家五套」生成餐桌清理类任务，注意轻拿轻放'
      : '把要审的任务贴进来，或者说「审一下选中的 5 条」';

  return (
    <section className="chat">
      <header className="chat-head">
        <div>
          <div className="chat-title">{conversation?.title ?? '新会话'}</div>
          <div className="chat-sub">
            {ROLE_NAME[role]} · 每次回复对应一次作业，当前会话的对话会作为下文
          </div>
        </div>
        <div className="chat-count">{messages.length} 条消息</div>
      </header>

      <div className="chat-body">
        {!conversation && <div className="chat-empty">正在准备会话…</div>}
        {conversation && messages.length === 0 && (
          <div className="chat-hint">
            {role === 'generator'
              ? '说说想做什么，也可以上传物料库或附件。'
              : '选右侧任务送审，或粘贴一段任务文本让它按 Skill 改。'}
          </div>
        )}
        {messages.map((item) => {
          const line = runLine(item);
          const active = item.run && (item.run.status === 'queued' || item.run.status === 'running');
          return (
            <div
              key={item.id}
              className={`bubble-row${item.role === 'user' ? ' is-user' : ''}`}
            >
              <div className={`bubble-card${item.role === 'user' ? ' is-user' : ''}`}>
                <div className="bubble-meta">
                  {item.role === 'user' ? '你' : ROLE_NAME[role]}
                  <span className="bubble-time">
                    {new Date(item.created_at).toLocaleTimeString('zh-CN', {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                </div>
                <div className="bubble-text">{item.content || '（空）'}</div>
                {item.attachments.length > 0 && (
                  <div className="bubble-chips">
                    {item.attachments.map((id) => (
                      <span className="mini-chip" key={id}>
                        {attachments.find((a) => a.id === id)?.filename ?? id.slice(-6)}
                      </span>
                    ))}
                  </div>
                )}
                {line && (
                  <div className={`run-line${active ? ' is-active' : ''}`}>
                    {active && <Spin size="small" />}
                    <span>{line}</span>
                  </div>
                )}
                {item.run?.error && (
                  <Alert
                    className="bubble-alert"
                    type="error"
                    showIcon
                    message={item.run.error.message}
                  />
                )}
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <div className="composer">
        <Input.TextArea
          className="composer-input"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={placeholder}
          autoSize={{ minRows: 2, maxRows: 6 }}
          maxLength={20000}
          onPressEnter={(event) => {
            if (!event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
          disabled={sending}
        />
        <div className="composer-bar">
          <Upload
            accept=".txt,.md,.csv,.xlsx"
            showUploadList={false}
            beforeUpload={(file) => {
              void upload(file);
              return false;
            }}
            disabled={uploading}
          >
            <Button size="small" loading={uploading}>
              上传物料库 / 附件
            </Button>
          </Upload>
          <Select
            className="composer-select"
            mode="multiple"
            allowClear
            size="small"
            value={attachmentIds}
            onChange={setAttachmentIds}
            placeholder="选择已上传的物料库"
            options={attachments.map((attachment) => ({
              value: attachment.id,
              label: attachment.filename,
            }))}
          />
          {role === 'reviewer' && (
            <Button size="small" onClick={() => setPasteOpen(true)}>
              粘贴任务
            </Button>
          )}
          <Button
            className="composer-send"
            type="primary"
            size="small"
            loading={sending}
            disabled={!text.trim() && !attachmentIds.length}
            onClick={() => void send()}
          >
            发送
          </Button>
        </div>
      </div>

      <Modal
        open={pasteOpen}
        title="粘贴一段任务"
        okText="交给审核 Agent"
        cancelText="取消"
        okButtonProps={{ disabled: !pastedText.trim() }}
        onOk={() => void sendPasted()}
        onCancel={() => setPasteOpen(false)}
      >
        <p className="modal-hint">
          每行一步，可直接带编号；物料从步骤里的【物料名】自动推导，不用手写。
        </p>
        <Input.TextArea
          value={pastedText}
          onChange={(event) => setPastedText(event.target.value)}
          autoSize={{ minRows: 8, maxRows: 18 }}
          placeholder={'任务名：餐桌清理\n1.把【抹布】从挂架上拿起\n2.把【抹布】放到餐桌上\n…'}
        />
      </Modal>
    </section>
  );
}
