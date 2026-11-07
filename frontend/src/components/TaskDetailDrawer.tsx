import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, CheckCheck, ChevronDown, ChevronLeft, ChevronRight, CircleAlert, ClipboardCheck, FileClock, GripVertical, Pencil, Plus, RotateCcw, ShieldCheck, Sparkles, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import type { ApiClient } from '@/api/client';
import { newIdempotencyKey } from '@/api/client';
import type { ChangeCategory, Run, TaskContent, TaskDetail, TaskVersion } from '@/api/types';
import { collectResolutions, errorHint, taskCategory } from '@/lib/presentation';
import { diffLines } from '@/utils/diff';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Skeleton } from '@/components/ui/skeleton';
import { Busy, ConfirmDialog, IconButton, InlineError, type ConfirmState } from '@/components/shared';
import StatusChip from '@/components/StatusChip';

interface Props { api: ApiClient; taskId: string; activeRun: Run | null; onClose: () => void; onChanged: () => void;
  previous?: string; next?: string; onNavigate: (id: string) => void }
const categories: Record<ChangeCategory, string> = { capability: '能力', purpose: '用途', terminal_state: '终态', wording: '措辞', materials: '物料', duplicate: '重复', other: '其他' };

function evidenceState(value: TaskDetail) {
  const saved = value.latest_decision?.task_version_id === value.current_version.id ? value.latest_decision.resolutions : {};
  const notes = Object.values(saved);
  const common = notes.length && new Set(notes).size === 1 ? notes[0] : '';
  const required = value.current_version.validation.issues.filter((i) => i.severity === 'review_required');
  return { common, checked: Object.fromEntries(required.map((i) => [i.code, Boolean(saved[i.code])])), individual: common ? {} : saved };
}

export default function TaskDetailDrawer({ api, taskId, activeRun, onClose, onChanged, previous, next, onNavigate }: Props) {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [versions, setVersions] = useState<TaskVersion[]>([]);
  const [content, setContent] = useState<TaskContent | null>(null);
  const [editing, setEditing] = useState(false);
  const [tab, setTab] = useState('content');
  const [category, setCategory] = useState<ChangeCategory>('other');
  const [changeNote, setChangeNote] = useState('');
  const [commonNote, setCommonNote] = useState('');
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [individual, setIndividual] = useState<Record<string, string>>({});
  const [selectedVersion, setSelectedVersion] = useState<string | null>(null);
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [reviseOpen, setReviseOpen] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [stoppingRunId, setStoppingRunId] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const actionLock = useRef(false);
  const checksRef = useRef<HTMLElement>(null);
  const baseline = detail ? evidenceState(detail) : { common: '', checked: {}, individual: {} };
  const dirtyContent = Boolean(detail && content) && (JSON.stringify(content) !== JSON.stringify(detail?.current_version.content) || Boolean(changeNote));
  const dirtyEvidence = commonNote !== baseline.common || JSON.stringify(checked) !== JSON.stringify(baseline.checked) || JSON.stringify(individual) !== JSON.stringify(baseline.individual);
  const dirty = dirtyContent || dirtyEvidence;
  const busy = Boolean(detail?.summary.busy_run_id) || Boolean(pending);
  const required = detail?.current_version.validation.issues.filter((i) => i.severity === 'review_required') ?? [];
  const errors = detail?.current_version.validation.issues.filter((i) => i.severity === 'error') ?? [];
  const warnings = detail?.current_version.validation.issues.filter((i) => i.severity === 'warning') ?? [];
  const resolutions = collectResolutions(required, checked, commonNote, individual);
  const remaining = required.length - Object.keys(resolutions).length;
  const duplicate = detail?.batch_issues.some((i) => i.severity === 'error') ?? false;

  const apply = useCallback((value: TaskDetail) => {
    setDetail(value); setContent(structuredClone(value.current_version.content)); setEditing(false); setChangeNote(''); setCategory('other');
    const evidence = evidenceState(value); setCommonNote(evidence.common); setChecked(evidence.checked); setIndividual(evidence.individual);
  }, []);
  const load = useCallback(() => Promise.all([api.getTask(taskId), api.listVersions(taskId)])
    .then(([value, history]) => { apply(value); setVersions(history.items); setError(''); })
    .catch((cause: unknown) => { setError((cause as Error).message); }), [api, taskId, apply]);
  useEffect(() => { let mounted = true; Promise.all([api.getTask(taskId), api.listVersions(taskId)]).then(([value, history]) => {
    if (mounted) { apply(value); setVersions(history.items); }
  }).catch((cause: unknown) => { if (mounted) setError((cause as Error).message); }); return () => { mounted = false; }; }, [api, taskId, apply]);
  const reviewRunning = Boolean(detail?.summary.busy_run_id);
  const globalBusy = Boolean(activeRun);
  const stopRequested = Boolean(detail?.summary.busy_run_id && (detail.summary.busy_run_id === stoppingRunId ||
    (detail.summary.busy_run_id === activeRun?.id && activeRun.cancel_requested_at)));
  useEffect(() => { if (!reviewRunning) return; const timer = window.setInterval(() => { void load(); onChanged(); }, 1500); return () => window.clearInterval(timer); }, [reviewRunning, load, onChanged]);
  useEffect(() => {
    if (!dirty && !pending) return;
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', guard); return () => window.removeEventListener('beforeunload', guard);
  }, [dirty, pending]);
  const guard = (action: () => void) => {
    if (pending) { toast.info('正在保存，请稍候'); return; }
    if (dirty) setConfirm({ title: '保留未完成的修改？', description: '任务编辑或核验依据尚未提交。离开会放弃这部分修改。', action: '放弃并离开', destructive: true, onConfirm: action });
    else action();
  };
  const perform = async (label: string, action: () => Promise<void>) => {
    if (actionLock.current) return;
    actionLock.current = true; setPending(label); setError('');
    try { await action(); } catch (cause) { const error = cause as { code?: string; message: string }; setError(errorHint({ code: error.code ?? '', message: error.message })); }
    finally { actionLock.current = false; setPending(''); }
  };
  const save = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!detail || !content) return;
    void perform('save', async () => {
      const value = await api.saveVersion(taskId, { expected_revision: detail.summary.revision,
        content: { name: content.name.trim(), steps: content.steps.map((s) => s.trim()), materials: content.materials.map((m) => ({ name: m.name.trim(), quantity: m.quantity })) },
        change_note: changeNote, change_category: category }, newIdempotencyKey());
      apply(value); onChanged(); await load(); toast.success('修改已保存为新版本');
    });
  };
  const decide = (decision: 'approve' | 'reject') => {
    if (!detail) return;
    if (decision === 'approve' && (remaining || dirtyContent || errors.length || duplicate)) { checksRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }); return; }
    void perform(decision, async () => {
      const result = await api.decide(taskId, { expected_revision: detail.summary.revision, version_id: detail.current_version.id,
        decision, reason: decision === 'reject' ? reason : '', resolutions: decision === 'approve' ? resolutions : {}, change_category: category }, newIdempotencyKey());
      apply(result.task); setRejectOpen(false); setReason(''); onChanged(); toast.success(decision === 'approve' ? '当前版本已确认，可以交付' : '任务已驳回，理由已留档');
    });
  };
  const review = () => {
    if (!detail) return;
    const start = () => void perform('review', async () => { await api.reviewTask(taskId, { expected_revision: detail.summary.revision, version_id: detail.current_version.id }, newIdempotencyKey()); await load(); onChanged(); toast.success('已送去重新审核'); });
    if (detail.summary.status === 'approved') setConfirm({ title: '重新审核已确认任务', description: '当前版本将撤回交付资格，审核后需重新人工确认。历史记录保留。', action: '重新审核', onConfirm: start });
    else guard(start);
  };
  const revise = () => {
    if (!detail || !feedback.trim()) return;
    const start = () => void perform('revise', async () => {
      await api.reviseTask(taskId, { expected_revision: detail.summary.revision, version_id: detail.current_version.id, feedback: feedback.trim() }, newIdempotencyKey());
      setReviseOpen(false); setFeedback(''); await load(); onChanged(); toast.success('已开始修改这条任务');
    });
    if (detail.summary.status === 'approved') setConfirm({ title: '修改已确认任务', description: '当前版本将撤回交付资格，修改和审核后需重新人工确认。', action: '开始修改', onConfirm: start });
    else start();
  };
  const restore = (version: TaskVersion) => {
    if (!detail) return;
    setConfirm({ title: `从版本 ${version.version_no} 恢复`, description: '旧内容将复制为一个新的人工版本，当前未提交修改会被放弃，全部历史记录保留。', action: '复制为新版本', onConfirm: () => void perform('restore', async () => {
      const value = await api.saveVersion(taskId, { expected_revision: detail.summary.revision, content: version.content, change_note: `从 v${version.version_no} 恢复`, change_category: 'other' }, newIdempotencyKey());
      apply(value); setSelectedVersion(null); onChanged(); await load(); toast.success('已恢复为新人工版本');
    }) });
  };
  const history = versions.find((v) => v.id === selectedVersion) ?? versions[0];
  const parent = versions.find((v) => v.id === history?.parent_version_id);
  const lines = (value: TaskContent) => [`任务名：${value.name}`, ...value.steps, ...value.materials.map((m) => `物料：${m.name} × ${m.quantity}`)];
  const diff = history && parent ? diffLines(lines(parent.content), lines(history.content)).filter((line) => line.kind !== 'same') : [];
  const checkedCount = required.filter((i) => checked[i.code]).length;
  const setStep = (index: number, value: string) => setContent((current) => current ? { ...current, steps: current.steps.map((s, i) => i === index ? value : s) } : current);
  return <Sheet open onOpenChange={(open) => { if (!open) guard(onClose); }}><SheetContent className="task-detail-sheet" showCloseButton={false}>
    <SheetHeader className="task-detail-header"><div className="detail-heading-row"><span className="eyebrow">任务详情</span><div className="detail-navigation">
      <IconButton label="上一个任务" disabled={!previous || busy} onClick={() => previous && guard(() => onNavigate(previous))}><ChevronLeft /></IconButton>
      <IconButton label="下一个任务" disabled={!next || busy} onClick={() => next && guard(() => onNavigate(next))}><ChevronRight /></IconButton>
      <IconButton label="关闭任务详情" onClick={() => guard(onClose)}><X /></IconButton></div></div>
      <SheetTitle>{detail?.current_version.content.name ?? '正在加载任务'}</SheetTitle>
      <SheetDescription className="detail-meta">{detail ? <><StatusChip task={detail.summary} /><span>{detail.current_version.content.steps.length} 步</span><span>当前版本 {detail.current_version.version_no}</span>{dirty && <span className="unsaved-indicator">未提交修改</span>}</> : '读取任务正文、版本和审核记录。'}</SheetDescription>
    </SheetHeader>
    {!detail || !content ? <div className="detail-initial">{error ? <InlineError message={error} action="重试" onAction={() => void load()} /> : <><Skeleton className="h-5 w-1/3" /><Skeleton className="mt-5 h-72 w-full" /></>}</div> : <>
      {error && <div className="detail-error"><InlineError message={error} />{error.includes('已被更新') && <Button variant="outline" size="sm" onClick={() => setConfirm({ title: '加载最新版本', description: '你的未保存编辑将被替换，请先复制需要保留的内容。', action: '加载最新版本', onConfirm: () => void load() })}>查看最新版本</Button>}</div>}
      {globalBusy && !reviewRunning && <p className="detail-error muted-copy">其他任务正在处理，结束后可开始 AI 修改或重新审核。</p>}
      <Tabs value={tab} onValueChange={setTab} className="detail-tabs"><div className="detail-tabbar"><TabsList><TabsTrigger value="content">任务内容</TabsTrigger><TabsTrigger value="review">AI 审核</TabsTrigger><TabsTrigger value="history">版本历史</TabsTrigger></TabsList>
        <div className="detail-tab-actions">{reviewRunning && <Button variant="outline" size="sm" disabled={Boolean(pending) || stopRequested} onClick={() => void perform('stop', async () => {
          if (!detail.summary.busy_run_id) return;
          await api.cancelRun(detail.summary.busy_run_id); setStoppingRunId(detail.summary.busy_run_id); onChanged(); toast.info('已请求停止，等待当前模型调用结束');
        })}>{stopRequested ? '正在停止' : '停止执行'}</Button>}<Button variant="ghost" size="sm" disabled={busy || globalBusy || editing} onClick={() => guard(() => setReviseOpen(true))}><Sparkles className="size-3.5" />AI 修改</Button><Button variant="ghost" size="sm" disabled={busy || globalBusy || editing} onClick={review}><RotateCcw className="size-3.5" />重新审核</Button>
          {!editing && <Button variant="outline" size="sm" disabled={busy} onClick={() => { setEditing(true); setTab('content'); }}><Pencil className="size-3.5" />编辑任务</Button>}</div></div>
      <div className="detail-scroll"><div className="detail-columns"><main className="detail-document">
        <TabsContent value="content" className="detail-tab-content">
          {editing ? <form id="task-edit" onSubmit={save}><fieldset disabled={Boolean(pending)}>
            <div className="field"><label htmlFor="task-name">任务名称</label><Input id="task-name" required maxLength={200} value={content.name} onChange={(e) => setContent({ ...content, name: e.target.value })} /></div>
            <div className="section-heading"><h3>任务步骤</h3><span>{content.steps.length} 步</span></div>
            <div className="editable-steps">{content.steps.map((step, index) => <div className="step-edit" key={index}><span>{index + 1}</span><Textarea required aria-label={`步骤 ${index + 1}`} value={step} onChange={(e) => setStep(index, e.target.value)} />
              <DropdownMenu><DropdownMenuTrigger asChild><Button type="button" variant="ghost" size="icon-sm" aria-label={`调整步骤 ${index + 1}`}><GripVertical className="size-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">
                <DropdownMenuItem disabled={index === 0} onSelect={() => setContent((current) => { if (!current) return current; const steps = [...current.steps]; [steps[index - 1], steps[index]] = [steps[index], steps[index - 1]]; return { ...current, steps }; })}>向上移动</DropdownMenuItem>
                <DropdownMenuItem disabled={index === content.steps.length - 1} onSelect={() => setContent((current) => { if (!current) return current; const steps = [...current.steps]; [steps[index], steps[index + 1]] = [steps[index + 1], steps[index]]; return { ...current, steps }; })}>向下移动</DropdownMenuItem>
                <DropdownMenuItem disabled={content.steps.length === 1} onSelect={() => setContent({ ...content, steps: content.steps.filter((_, i) => i !== index) })}>删除步骤</DropdownMenuItem>
              </DropdownMenuContent></DropdownMenu></div>)}</div>
            <Button type="button" variant="outline" size="sm" onClick={() => setContent({ ...content, steps: [...content.steps, ''] })}><Plus />添加步骤</Button>
            <div className="section-heading"><h3>单套物料</h3></div><div className="editable-materials">{content.materials.map((material, index) => <div key={index}><Input aria-label={`物料 ${index + 1} 名称`} required value={material.name} onChange={(e) => setContent({ ...content, materials: content.materials.map((m, i) => i === index ? { ...m, name: e.target.value } : m) })} />
              <Input aria-label={`物料 ${index + 1} 数量`} required type="number" min={1} max={1000} value={material.quantity || ''} onChange={(e) => setContent({ ...content, materials: content.materials.map((m, i) => i === index ? { ...m, quantity: Number(e.target.value) } : m) })} />
              <IconButton type="button" label={`删除物料 ${index + 1}`} disabled={content.materials.length === 1} onClick={() => setContent({ ...content, materials: content.materials.filter((_, i) => i !== index) })}><Trash2 className="size-4" /></IconButton></div>)}</div>
            <Button type="button" variant="outline" size="sm" onClick={() => setContent({ ...content, materials: [...content.materials, { name: '', quantity: 1 }] })}><Plus />添加物料</Button>
            <div className="field mt-6"><label htmlFor="change-note">修改说明<span>选填</span></label><Textarea id="change-note" value={changeNote} maxLength={2000} onChange={(e) => setChangeNote(e.target.value)} placeholder="说明本次调整的原因，保留到版本历史" /></div>
          </fieldset></form> : <><div className="section-heading"><h3>执行步骤</h3><span>{content.steps.length} 步</span></div><ol className="readable-steps">{content.steps.map((step, index) => <li key={index}><span className="step-number">{String(index + 1).padStart(2, '0')}</span><p>{step}</p></li>)}</ol>
            <div className="section-heading"><h3>单套所需物料</h3><span>{content.materials.reduce((sum, m) => sum + m.quantity, 0)} 件</span></div><div className="readable-materials">{content.materials.map((material) => <span key={material.name}>{material.name}<strong>× {material.quantity}</strong></span>)}</div></>}
        </TabsContent>
        <TabsContent value="review" className="detail-tab-content"><div className="section-heading"><h3>AI 审核意见</h3>{detail.latest_review && <span>{detail.ai_review_matches_current_version ? '对应当前版本' : '历史版本意见'}</span>}</div>
          {detail.latest_review ? <><div className="review-verdict"><ShieldCheck className="size-5" /><strong>{detail.latest_review.verdict === 'pass' ? 'AI 审核通过，仍需人工核验' : '需要人工处理'}</strong></div><p className="review-summary">{detail.latest_review.summary}</p>
            {!detail.ai_review_matches_current_version && <InlineError message="这些意见针对旧版本，请结合当前正文复核。" />}
            <div className="review-findings">{detail.latest_review.issues.filter((i) => !i.rule_id?.startsWith('SYSTEM_BATCH_')).map((issue, index) => <article key={index}><div><span className={issue.severity === 'error' ? 'finding-error' : 'muted-copy'}>{issue.severity === 'error' ? '需处理' : '建议'}</span>{issue.step_no && <span>第 {issue.step_no} 步</span>}</div><p>{issue.message}</p>{issue.quote && <blockquote>{issue.quote}</blockquote>}{issue.suggestion && <p className="muted-copy">{issue.suggestion}</p>}</article>)}</div>
          </> : <p className="muted-copy">暂无 AI 审核意见。可以重新审核当前任务。</p>}
        </TabsContent>
        <TabsContent value="history" className="detail-tab-content"><div className="section-heading"><h3>不可变版本记录</h3><FileClock className="size-4 text-muted-foreground" /></div>
          <Select value={selectedVersion ?? detail.current_version.id} onValueChange={setSelectedVersion}><SelectTrigger aria-label="查看历史版本"><SelectValue /></SelectTrigger><SelectContent>{versions.map((v) => <SelectItem key={v.id} value={v.id}>版本 {v.version_no} / {v.author_type === 'human' ? '人工编辑' : v.author_type === 'ai_revision' ? 'AI 修订' : 'AI 原稿'}</SelectItem>)}</SelectContent></Select>
          {history && <><p className="history-note">{history.change_note || '没有修改说明'}<span>{new Date(history.created_at).toLocaleString('zh-CN')}</span></p>
            {history.id !== detail.current_version.id && <Button variant="outline" size="sm" disabled={busy} onClick={() => restore(history)}><RotateCcw />复制为新人工版本</Button>}
            {parent && <details className="plain-details" open><summary>与版本 {parent.version_no} 的差异</summary><div className="version-diff">{diff.length ? diff.map((line, index) => <div key={index} className={line.kind === 'added' ? 'diff-added' : 'diff-removed'}><span>{line.kind === 'added' ? '+' : '−'}</span>{line.text}</div>) : <p>正文没有差异</p>}</div></details>}
            <h3 className="mt-6 font-medium">{history.content.name}</h3><ol className="history-steps">{history.content.steps.map((step, index) => <li key={index}>{step}</li>)}</ol><div className="readable-materials">{history.content.materials.map((m) => <span key={m.name}>{m.name}<strong>× {m.quantity}</strong></span>)}</div>
          </>}
        </TabsContent>
      </main><aside className="detail-verification" ref={checksRef} aria-label="确认前核验">
        <div className="verification-title"><ClipboardCheck className="size-4" /><h3>确认前核验</h3><span>{checkedCount}/{required.length}</span></div>
        {detail.summary.status === 'approved' ? <div className="confirmed-note"><CheckCheck className="size-5" /><strong>当前版本已确认</strong><p>编辑或重新审核后，需要再次确认。</p></div> : <p className="verification-intro">核对现场事实，再填写依据。一次说明可用于多个核验项。</p>}
        {(errors.length > 0 || duplicate) && <div className="blocking-findings"><h4><CircleAlert className="size-4" />先处理规则问题</h4>{errors.map((issue, index) => <p key={index}>{issue.message}</p>)}{duplicate && <p>与同批任务步骤完全相同，需要先调整。</p>}</div>}
        <div className="verification-checklist">{required.map((issue) => <div className="verification-item" key={issue.code}>
          <label><Checkbox checked={Boolean(checked[issue.code])} disabled={busy || editing || !detail.can_decide} onCheckedChange={(value) => setChecked((current) => ({ ...current, [issue.code]: value === true }))} /><span>{taskCategory(issue.code)}</span></label>
          <details><summary>核验内容<ChevronDown className="size-3" /></summary><p>{issue.message}</p>
            <Textarea aria-label={`${taskCategory(issue.code)}单项依据`} maxLength={2000} disabled={busy || editing || !detail.can_decide} placeholder="单项说明（选填，优先于共用说明）" value={individual[issue.code] ?? ''} onChange={(e) => setIndividual((current) => ({ ...current, [issue.code]: e.target.value }))} /></details>
        </div>)}</div>
        {required.length > 0 && <div className="field evidence-note"><label htmlFor="verification-note">核验说明</label><Textarea id="verification-note" value={commonNote} maxLength={2000} disabled={busy || editing || !detail.can_decide} onChange={(e) => setCommonNote(e.target.value)} placeholder="记录现场核验结果或依据，适用于已勾选项" /><p>{remaining ? `还有 ${remaining} 项缺少勾选或依据` : '核验依据已完整，可确认当前版本'}</p></div>}
        <details className="plain-details feedback-category"><summary>反馈分类</summary><Select value={category} disabled={busy || (!editing && !detail.can_decide)} onValueChange={(value) => setCategory(value as ChangeCategory)}><SelectTrigger aria-label="反馈分类"><SelectValue /></SelectTrigger><SelectContent>{Object.entries(categories).map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent></Select></details>
        {(warnings.length > 0 || detail.batch_issues.some((i) => i.severity === 'warning')) && <details className="plain-details verification-warnings"><summary>查看非阻断提示</summary>{[...warnings, ...detail.batch_issues.filter((i) => i.severity === 'warning')].map((issue, index) => <p key={index}>{issue.message}</p>)}</details>}
      </aside></div></div></Tabs>
      <footer className="detail-footer"><div>{editing ? <span className="muted-copy">修改后会创建新版本</span> : <span className="muted-copy">{detail.summary.status === 'approved' ? '可交付当前确认版本' : errors.length || duplicate ? '规则问题需先修正' : remaining ? `还需完成 ${remaining} 项核验` : '核验依据已完整'}</span>}</div><div className="detail-footer-actions">
        {editing ? <><Button variant="outline" disabled={busy} onClick={() => guard(() => { apply(detail); })}>取消编辑</Button><Button type="submit" form="task-edit" disabled={busy || !dirtyContent}>{pending === 'save' ? <Busy>保存中</Busy> : <><Check />保存修改</>}</Button></> : <>
          <Button variant="outline" disabled={busy || !detail.can_decide} onClick={() => setRejectOpen(true)}>驳回</Button>
          {remaining && detail.can_decide ? <Button variant="secondary" onClick={() => checksRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })}><ClipboardCheck />去核验</Button> : null}
          <Button disabled={busy || !detail.can_decide || Boolean(remaining) || errors.length > 0 || duplicate} onClick={() => decide('approve')}>
            {pending === 'approve' ? <Busy>提交中</Busy> : <><ShieldCheck />{detail.summary.status === 'approved' ? '已确认' : '确认通过'}</>}</Button>
        </>}
      </div></footer>
    </>}
    <ConfirmDialog value={confirm} onClose={() => setConfirm(null)} />
    <Dialog open={reviseOpen} onOpenChange={(open) => { if (!pending) setReviseOpen(open); }}><DialogContent><DialogHeader><DialogTitle>AI 修改当前任务</DialogTitle><DialogDescription>只修改这条任务，完成后会重新审核并保留版本记录。</DialogDescription></DialogHeader>
      <form onSubmit={(event) => { event.preventDefault(); revise(); }}><label className="sr-only" htmlFor="revision-feedback">修改要求</label><Textarea id="revision-feedback" required maxLength={5000} value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="例如：缩短步骤，并保留最后的收纳状态" /><div className="mt-5 flex justify-end"><Button type="submit" disabled={Boolean(pending) || !feedback.trim()}>开始修改</Button></div></form>
    </DialogContent></Dialog>
    <Dialog open={rejectOpen} onOpenChange={(open) => { if (!pending) setRejectOpen(open); }}><DialogContent><DialogHeader><DialogTitle>驳回当前版本</DialogTitle><DialogDescription>说明具体问题，理由会与当前版本一同留档。</DialogDescription></DialogHeader><form onSubmit={(event) => { event.preventDefault(); decide('reject'); }}>
      <label className="sr-only" htmlFor="reject-reason">驳回理由</label><Textarea id="reject-reason" required maxLength={5000} value={reason} disabled={Boolean(pending)} onChange={(e) => setReason(e.target.value)} placeholder="例如：终态收回了仍需使用的物品" />{error && <InlineError message={error} />}<div className="mt-5 flex justify-end"><Button type="submit" variant="destructive" disabled={Boolean(pending) || !reason.trim()}>{pending === 'reject' ? <Busy>提交中</Busy> : '确认驳回'}</Button></div></form></DialogContent></Dialog>
  </SheetContent></Sheet>;
}
