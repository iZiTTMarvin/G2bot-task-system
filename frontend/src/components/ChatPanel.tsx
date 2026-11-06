import { Fragment, useRef, useState } from 'react';
import { ArrowUp, Check, ChevronDown, Copy, FileText, FolderOpen, Loader2, Paperclip, RefreshCw, Settings2, Sparkles, X } from 'lucide-react';
import { toast } from 'sonner';
import type { Workspace } from '@/hooks/use-workspace';
import type { ChatMessage, Run } from '@/api/types';
import { effectiveAttachments, errorHint, needsRunResult, shortTime, visibleMessages } from '@/lib/presentation';
import { Conversation, ConversationContent, ConversationEmptyState, ConversationScrollButton } from '@/components/ai-elements/conversation';
import { Message, MessageContent, MessageAction, MessageActions } from '@/components/ai-elements/message';
import { PromptInput, PromptInputBody, PromptInputFooter, PromptInputTextarea, PromptInputTools, PromptInputSubmit } from '@/components/ai-elements/prompt-input';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { InlineError } from '@/components/shared';

function RunResult({ message, workspace: w, onSettings }: { message: ChatMessage; workspace: Workspace; onSettings: () => void }) {
  const run = message.run;
  if (!run) return null;
  const failed = run.status === 'failed' || run.status === 'interrupted';
  const active = run.status === 'queued' || run.status === 'running';
  if (!failed && !active) return <div className="run-result"><div className="run-result-heading"><Check className="size-4" /><strong>任务处理完成</strong></div><p>结果已保留，可在任务结果中查看。</p></div>;
  const stages: Record<Run['stage'], string> = { queued: '等待执行', generating: '正在设计任务', validating: '正在检查规则', reviewing: '正在审核任务', done: '处理完成' };
  return <div className={failed ? 'run-result is-error' : 'run-result'} role={failed ? 'status' : undefined}>
    <div className="run-result-heading">{active ? <Loader2 className="size-4 animate-spin" /> : <span className="error-dot" />}
      <strong>{failed ? '这次任务未完成' : stages[run.stage]}</strong>
      {active && run.progress.total > 0 && <span className="run-counter">{run.progress.completed} / {run.progress.total}</span>}</div>
    {failed ? <><p>{run.error ? errorHint(run.error) : '执行已中断，原要求和资料已保留。'}</p>
      <div className="run-actions"><Button variant="outline" size="sm" disabled={w.interactionBusy || w.busy} onClick={() => void w.retry(message)}><RefreshCw />重试本次任务</Button>
        <Button variant="ghost" size="sm" onClick={onSettings}><Settings2 />检查模型设置</Button></div>
      {run.error && <details className="error-diagnostics"><summary>诊断信息</summary><code>{run.error.code}</code><p>{run.error.message}</p></details>}
    </> : <p>{run.status === 'queued' ? '请求已保存，轮到后会自动开始。' : '可继续查看历史记录，结果会自动更新。'}</p>}
  </div>;
}

function CopyAction({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return <MessageAction tooltip={copied ? '已复制' : '复制内容'} onClick={() => {
    navigator.clipboard.writeText(text).then(() => setCopied(true)).catch(() => toast.error('复制失败，请手动选择文本'));
  }}>{copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}</MessageAction>;
}

export default function ChatPanel({ workspace: w, onLibrary, onSettings }: {
  workspace: Workspace; onLibrary: () => void; onSettings: () => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const compositionEnd = useRef(0);
  const currentFiles = effectiveAttachments(w.conversation?.attachment_ids ?? [], w.draft.attachmentIds, w.draft.attachmentMode);
  const timeline = visibleMessages(w.messages);
  const examples = w.role === 'generator' ? [
    { title: '折叠与收纳', text: '设计五条折叠衣物的高质量长任务，围绕真实收纳活动，明确初态与终态。' },
    { title: '餐桌准备', text: '使用现有物料设计餐桌准备任务，摆好的待用物品保留在取用位置。' },
    { title: '整理办公桌', text: '设计办公桌整理任务，步骤简洁、物品可抓取，不通过重复擦拭凑步数。' },
  ] : [];
  const submit = async () => {
    if (w.interactionBusy || w.busy || (!w.draft.text.trim() && (w.role === 'generator' || !currentFiles.length))) return;
    const accepted = await w.send();
    if (!accepted) throw new Error('请求未被接受，保留输入');
    textarea.current?.focus();
  };
  return <section id="workspace-chat" role={w.tasks.length ? 'tabpanel' : undefined} aria-labelledby={w.tasks.length ? 'view-chat-tab' : undefined} className="chat-panel" aria-label={w.role === 'generator' ? '任务生成' : '任务审核'}>
    {w.viewError && <InlineError message={w.viewError} action="重新加载" onAction={w.refresh} />}
    <Conversation key={w.activeId ?? 'new'} className="chat-conversation" initial="instant" resize="instant" aria-label="任务对话记录">
      <ConversationContent className={timeline.length ? 'conversation-content' : 'conversation-content is-empty'}>
        {w.loading || w.initializing ? <div className="conversation-loading" role="status" aria-label="正在加载对话"><Skeleton className="h-5 w-36" /><Skeleton className="mt-5 h-20 w-4/5" /><Skeleton className="ml-auto mt-8 h-14 w-1/2" /></div>
          : !timeline.length ? <ConversationEmptyState className="workspace-empty">
            <div className="empty-symbol"><Sparkles className="size-6" /></div>
            <div className="eyebrow">G2 TASK WORKSPACE</div>
            <h1>{w.role === 'generator' ? '从一个想法，开始一组好任务' : '让已有任务，经得起审核'}</h1>
            <p>{w.role === 'generator' ? '描述场景、物料和采集目标。生成后，在这里查看、修改与交付。' : '粘贴任务步骤或上传文件，审核结果与修改版本会保留。'}</p>
            {examples.length > 0 && <div className="starter-prompts">{examples.map((item) => <button key={item.title}
              onClick={() => { w.updateDraft({ text: item.text }); textarea.current?.focus(); }}><span>{item.title}</span><ArrowUp className="size-3.5 rotate-45" /></button>)}</div>}
          </ConversationEmptyState> : timeline.map((message) => <Fragment key={message.id}>
            <Message from={message.role === 'user' ? 'user' : 'assistant'} className={message.role === 'user' ? 'user-message' : 'assistant-message'}>
              {message.role === 'agent' && <div className="message-author"><span className="assistant-mark">G2</span>{w.role === 'generator' ? '任务助手' : '审核助手'}<time>{shortTime(message.created_at)}</time></div>}
              {message.role === 'agent' && message.run && ['failed', 'interrupted', 'queued', 'running'].includes(message.run.status)
                ? <RunResult message={message} workspace={w} onSettings={onSettings} />
                : <MessageContent className="message-copy">{message.content}</MessageContent>}
              {message.role === 'user' && message.attachments.length > 0 && <div className="message-files">{message.attachments.map((id) => <span key={id}><FileText className="size-3" />{w.attachments.find((a) => a.id === id)?.filename ?? '附件资料'}</span>)}</div>}
              {message.role === 'agent' && !['failed', 'interrupted', 'queued', 'running'].includes(message.run?.status ?? '') && <MessageActions className="assistant-actions"><CopyAction text={message.content} /></MessageActions>}
            </Message>
            {needsRunResult(message, w.messages) && <Message from="assistant" className="assistant-message"><div className="message-author"><span className="assistant-mark">G2</span>任务助手</div><RunResult message={message} workspace={w} onSettings={onSettings} /></Message>}
          </Fragment>)}
      </ConversationContent>
      <ConversationScrollButton aria-label="回到最新消息" />
    </Conversation>
    <div className="composer-wrap">
      <PromptInput className="task-composer" onSubmit={submit} onDropCapture={(event) => {
        if (event.dataTransfer.files.length) { event.preventDefault(); event.stopPropagation(); const file = event.dataTransfer.files[0]; if (!w.interactionBusy) void w.upload(file); }
      }}>
        {currentFiles.length > 0 && <div className="composer-files">{currentFiles.map((id) => <span className="attachment-chip" key={id}><FileText className="size-3.5" />
          <span>{w.attachments.find((a) => a.id === id)?.filename ?? '附件资料'}</span>
          <button type="button" aria-label={`移除 ${w.attachments.find((a) => a.id === id)?.filename ?? '附件'}`} disabled={w.interactionBusy}
            onClick={() => w.updateDraft({ attachmentMode: 'replace', attachmentIds: currentFiles.filter((item) => item !== id) })}><X className="size-3" /></button></span>)}</div>}
        <PromptInputBody><PromptInputTextarea id="main-composer" ref={textarea} aria-label="任务要求" value={w.draft.text}
          onChange={(e) => w.updateDraft({ text: e.target.value })} disabled={w.interactionBusy}
          maxLength={w.role === 'generator' ? 20000 : 80000}
          placeholder={w.role === 'generator' ? '描述你想采集的任务，或补充这组任务的要求…' : '粘贴任务文本，每行一步，物料使用【物料名】标注…'}
          onCompositionEndCapture={() => { compositionEnd.current = Date.now(); }}
          onKeyDown={(event) => { if (event.key === 'Enter' && (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229 || Date.now() - compositionEnd.current < 500)) event.preventDefault(); }}
          onPaste={(event) => { if (event.clipboardData.files.length) { event.preventDefault(); void w.upload(event.clipboardData.files[0]); } }} />
        </PromptInputBody>
        <PromptInputFooter><PromptInputTools>
          <input type="file" ref={fileInput} className="sr-only" tabIndex={-1} aria-label="添加附件" accept=".txt,.md,.csv,.xlsx"
            onChange={(event) => { const file = event.target.files?.[0]; if (file) void w.upload(file); event.target.value = ''; }} />
          <Button variant="ghost" size="sm" type="button" disabled={w.interactionBusy} onClick={() => fileInput.current?.click()}>
            {w.uploading ? <Loader2 className="size-4 animate-spin" /> : <Paperclip className="size-4" />}<span className="attachment-button-label">添加资料</span></Button>
          <Button variant="ghost" size="sm" type="button" disabled={w.interactionBusy} onClick={onLibrary}><FolderOpen className="size-4" /><span>资料库{currentFiles.length > 0 ? ` ${currentFiles.length}` : ''}</span></Button>
        </PromptInputTools>
          <div className="composer-end"><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="sm" type="button" disabled={w.interactionBusy || w.busy} className="composer-mode">{w.role === 'generator' ? '生成任务' : '审核任务'}<ChevronDown className="size-3" /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end"><DropdownMenuItem onSelect={() => void w.create('generator')}>新建生成任务集</DropdownMenuItem><DropdownMenuItem onSelect={() => void w.create('reviewer')}>新建审核记录</DropdownMenuItem></DropdownMenuContent></DropdownMenu>
            <PromptInputSubmit aria-label={w.sending ? '正在发送' : '发送要求'} disabled={w.interactionBusy || w.busy || (!w.draft.text.trim() && (w.role === 'generator' || !currentFiles.length))}>
              {w.sending || w.busy ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
            </PromptInputSubmit>
          </div>
        </PromptInputFooter>
      </PromptInput>
      <p className="composer-caption">{w.busy ? '任务正在处理中，完成后可继续补充要求。' : <><span>Enter 发送</span><i /><span>Shift + Enter 换行</span><i className="caption-optional" /><span className="caption-optional">现场条件需人工核验</span></>}</p>
    </div>
  </section>;
}
