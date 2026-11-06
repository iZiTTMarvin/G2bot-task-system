import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Download, Menu, Monitor, Moon, PanelLeftOpen, PanelRightClose, PanelRightOpen, Settings2, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';
import { toast } from 'sonner';
import { realClient as api } from '@/api/real';
import { newIdempotencyKey } from '@/api/client';
import type { Conversation } from '@/api/types';
import { useWorkspace } from '@/hooks/use-workspace';
import WorkspaceSidebar from '@/components/WorkspaceSidebar';
import ChatPanel from '@/components/ChatPanel';
import TaskPanel from '@/components/TaskPanel';
import { ConfirmDialog, IconButton, InlineError, type ConfirmState } from '@/components/shared';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet';
import { Input } from '@/components/ui/input';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import { Skeleton } from '@/components/ui/skeleton';
import './app.css';

const SettingsPage = lazy(() => import('@/pages/SettingsPage'));
const MaterialLibrary = lazy(() => import('@/components/MaterialLibrary'));
const TaskDetailDrawer = lazy(() => import('@/components/TaskDetailDrawer'));

export default function App() {
  const w = useWorkspace(api);
  const { theme, setTheme } = useTheme();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  useEffect(() => {
    if (sidebarCollapsed) document.querySelector<HTMLButtonElement>('.desktop-expand-trigger')?.focus();
  }, [sidebarCollapsed]);
  const [mobileSidebar, setMobileSidebar] = useState(false);
  const [resultsOpen, setResultsOpen] = useState(true);
  const [mobileTab, setMobileTab] = useState('chat');
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<Conversation | null>(null);
  const [renameText, setRenameText] = useState('');
  const [renameBusy, setRenameBusy] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [model, setModel] = useState('');
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const actionLock = useRef(false);
  const pendingAction = useRef<{ digest: string; key: string } | null>(null);
  const reviewerId = useRef<string | null>(null);
  const { hasDrafts, sending } = w;
  useEffect(() => {
    if (!hasDrafts && !settingsDirty && !sending) return;
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [hasDrafts, settingsDirty, sending]);
  const refreshModel = () => api.getSettings().then((settings) => setModel(settings.generation_model)).catch(() => setModel(''));
  useEffect(() => { let active = true; api.getSettings().then((settings) => { if (active) setModel(settings.generation_model); }).catch(() => { if (active) setModel(''); }); return () => { active = false; }; }, []);
  const startRename = (conversation: Conversation) => { setRenaming(conversation); setRenameText(conversation.title); };
  const keyFor = (input: unknown) => {
    const digest = JSON.stringify(input);
    if (pendingAction.current?.digest !== digest) pendingAction.current = { digest, key: newIdempotencyKey() };
    return pendingAction.current.key;
  };
  const submit = async () => {
    if (actionLock.current || !w.selected.length) return;
    actionLock.current = true; setSubmitting(true);
    try {
      let target = w.conversations.find((c) => c.agent_role === 'reviewer')?.id ?? reviewerId.current;
      if (!target) { const created = await api.createConversation('reviewer'); target = created.id; reviewerId.current = target; }
      const input = { content: `审核所选 ${w.selected.length} 条任务`, task_ids: w.selected };
      const result = await api.sendMessage(target, input, keyFor(['submit', target, input]));
      pendingAction.current = null; w.setSelected([]); w.choose(result.conversation); w.refresh(); setResultsOpen(true); setMobileTab('tasks');
      void w.refreshIndex().catch(() => toast.warning('已送审，导航更新失败，可稍后刷新'));
      toast.success(`已送审 ${input.task_ids.length} 条任务`);
    } catch (cause) { toast.error((cause as Error).message); }
    finally { actionLock.current = false; setSubmitting(false); }
  };
  const requestSubmit = () => {
    if (w.tasks.some((task) => w.selected.includes(task.id) && task.status === 'approved')) setConfirm({ title: '重新审核所选任务', description: '其中已确认的任务将撤回交付资格，审核后需要重新人工确认。', action: '送去审核', onConfirm: () => void submit() });
    else void submit();
  };
  const exportTasks = async (intent: 'draft' | 'delivery') => {
    if (actionLock.current || !w.selected.length) return;
    const chosen = w.tasks.filter((task) => w.selected.includes(task.id));
    if (new Set(chosen.map((task) => task.batch_id)).size !== 1) { toast.error('请只选择同一批次的任务，避免漏导'); return; }
    actionLock.current = true; setExporting(true);
    try {
      const input = { batch_id: chosen[0].batch_id, task_ids: chosen.map((task) => task.id), intent };
      const record = await api.createExport(input, keyFor(['export', input]));
      const blob = await api.downloadExport(record.download_url);
      const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = record.filename;
      document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url); pendingAction.current = null;
      toast.success(`已导出 ${chosen.length} 条${intent === 'delivery' ? '交付任务' : '任务草稿'}`);
    } catch (cause) { toast.error((cause as Error).message); }
    finally { actionLock.current = false; setExporting(false); }
  };
  const closeSettings = (open: boolean) => {
    if (!open && settingsDirty) setConfirm({ title: '放弃设置修改？', description: '修改尚未保存，关闭后会恢复原设置。', action: '放弃修改', destructive: true, onConfirm: () => { setSettingsOpen(false); setSettingsDirty(false); } });
    else setSettingsOpen(open);
  };
  const previousBusy = useRef(false);
  const { busy: workspaceBusy, refreshIndex, refresh: refreshWorkspace } = w;
  useEffect(() => {
    if (previousBusy.current && !workspaceBusy) {
      refreshWorkspace();
      void refreshIndex().catch(() => toast.warning('任务已处理，导航更新失败，可稍后刷新'));
    }
    previousBusy.current = workspaceBusy;
  }, [workspaceBusy, refreshIndex, refreshWorkspace]);
  const activeTaskIndex = w.tasks.findIndex((task) => task.id === taskId);
  const showResults = w.tasks.length > 0 && resultsOpen;
  const sidebar = (mobile: boolean) => <WorkspaceSidebar workspace={w} onLibrary={() => { setLibraryOpen(true); setMobileSidebar(false); }}
    onSettings={() => { setSettingsOpen(true); setMobileSidebar(false); }} onRename={startRename}
    onCollapse={() => mobile ? setMobileSidebar(false) : setSidebarCollapsed(true)} onNavigate={mobile ? () => setMobileSidebar(false) : undefined} />;
  return <TooltipProvider delayDuration={350}><div className={`app-shell${sidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
    <div className="desktop-sidebar">{sidebar(false)}</div>
    <div className="workspace-main"><header className="workspace-header"><div className="workspace-heading">
      <IconButton className="mobile-nav-trigger" label="打开导航" onClick={() => setMobileSidebar(true)}><Menu /></IconButton>
      {sidebarCollapsed && <IconButton className="desktop-expand-trigger" label="展开导航" onClick={() => setSidebarCollapsed(false)}><PanelLeftOpen /></IconButton>}
      <div><span className="header-eyebrow">{w.role === 'reviewer' ? '审核工作区' : '任务工作区'}</span><h1 title={w.conversation?.title}>{w.conversation?.title ?? '新建任务集'}</h1></div>
    </div><div className="header-actions">
      <span className="model-indicator" title={model}>{model ? <><i />{model}</> : <button onClick={() => setSettingsOpen(true)}>模型设置</button>}</span>
      <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" aria-label="切换主题">{theme === 'dark' ? <Moon className="size-4" /> : <Sun className="size-4" />}</Button></DropdownMenuTrigger>
        <DropdownMenuContent align="end"><DropdownMenuLabel>外观</DropdownMenuLabel>{[{ value: 'light', label: '浅色', Icon: Sun }, { value: 'dark', label: '深色', Icon: Moon }, { value: 'system', label: '跟随系统', Icon: Monitor }].map(({ value, label, Icon }) => <DropdownMenuItem key={value} onSelect={() => setTheme(value)}><Icon className="size-4" />{label}{theme === value && <span className="ml-auto">✓</span>}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu>
      <IconButton label="模型设置" onClick={() => setSettingsOpen(true)}><Settings2 /></IconButton>
      {w.tasks.length > 0 && <IconButton className="results-toggle" label={showResults ? '收起任务结果' : '展开任务结果'} onClick={() => setResultsOpen((value) => !value)}>{showResults ? <PanelRightClose /> : <PanelRightOpen />}</IconButton>}
    </div></header>
      {w.indexError && <InlineError message={w.indexError} action="重试" onAction={() => void w.refreshIndex().catch((e: Error) => toast.error(e.message))} />}
      {w.tasks.length > 0 && <div className="mobile-view-tabs" role="tablist" aria-label="工作区视图" onKeyDown={(event) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>('[role=tab]');
        const value = event.key === 'Home' ? 'chat' : event.key === 'End' ? 'tasks' : mobileTab === 'chat' ? 'tasks' : 'chat';
        setMobileTab(value); buttons[value === 'chat' ? 0 : 1]?.focus();
      }}><button id="view-chat-tab" role="tab" aria-controls="workspace-chat" tabIndex={mobileTab === 'chat' ? 0 : -1} aria-selected={mobileTab === 'chat'} onClick={() => setMobileTab('chat')}>对话</button><button id="view-tasks-tab" role="tab" aria-controls="workspace-results" tabIndex={mobileTab === 'tasks' ? 0 : -1} aria-selected={mobileTab === 'tasks'} onClick={() => setMobileTab('tasks')}>任务结果<span>{w.tasks.length}</span></button></div>}
      <div className={`workspace-body${showResults ? ' has-results' : ''} mobile-view-${w.tasks.length ? mobileTab : 'chat'}`}>
        <ChatPanel workspace={w} onLibrary={() => setLibraryOpen(true)} onSettings={() => setSettingsOpen(true)} />
        {w.tasks.length > 0 && <div id="workspace-results" role="tabpanel" aria-labelledby="view-tasks-tab" className={`results-container${!resultsOpen ? ' is-collapsed' : ''}`}><TaskPanel tasks={w.tasks} selected={w.selected} onSelection={w.setSelected} onOpen={setTaskId}
          onExport={(intent) => void exportTasks(intent)} onSubmit={requestSubmit} exporting={exporting} submitting={submitting} busy={w.busy || w.interactionBusy} /></div>}
      </div>
      {!showResults && w.tasks.length > 0 && <Button className="floating-results" variant="outline" onClick={() => { setResultsOpen(true); setMobileTab('tasks'); }}><Download className="size-4" />查看 {w.tasks.length} 条任务</Button>}
    </div>
    <Sheet open={mobileSidebar} onOpenChange={setMobileSidebar}><SheetContent side="left" className="mobile-sidebar-sheet" showCloseButton={false}><SheetTitle className="sr-only">任务集导航</SheetTitle><SheetDescription className="sr-only">查看历史任务集或创建新任务</SheetDescription>{sidebar(true)}</SheetContent></Sheet>
    <Dialog open={settingsOpen} onOpenChange={closeSettings}><DialogContent className="settings-dialog sm:max-w-xl"><DialogHeader><DialogTitle>模型设置</DialogTitle><DialogDescription>连接你自己的 OpenAI 或 Anthropic 兼容服务。</DialogDescription></DialogHeader>
      {settingsOpen && <Suspense fallback={<Skeleton className="h-64 w-full" />}><SettingsPage api={api} onDirtyChange={setSettingsDirty} onSaved={() => { void refreshModel(); }} /></Suspense>}
    </DialogContent></Dialog>
    <Suspense fallback={null}>{libraryOpen && <MaterialLibrary workspace={w} open={libraryOpen} onOpenChange={setLibraryOpen} />}</Suspense>
    <Suspense fallback={null}>{taskId && <TaskDetailDrawer key={taskId} api={api} taskId={taskId} onClose={() => setTaskId(null)} onChanged={w.refresh}
      previous={w.tasks[activeTaskIndex - 1]?.id} next={w.tasks[activeTaskIndex + 1]?.id} onNavigate={setTaskId} />}</Suspense>
    <Dialog open={Boolean(renaming)} onOpenChange={(open) => { if (!open && !renameBusy) setRenaming(null); }}><DialogContent><DialogHeader><DialogTitle>重命名任务集</DialogTitle><DialogDescription>名称用于在导航中查找，不会修改任务内容。</DialogDescription></DialogHeader>
      <form onSubmit={(event) => { event.preventDefault(); if (!renaming || !renameText.trim() || renameBusy) return; setRenameBusy(true); void w.rename(renaming.id, renameText.trim()).then(() => setRenaming(null)).catch((cause: Error) => toast.error(cause.message)).finally(() => setRenameBusy(false)); }}>
        <label htmlFor="conversation-title" className="sr-only">任务集名称</label><Input id="conversation-title" autoFocus required maxLength={100} value={renameText} disabled={renameBusy} onChange={(e) => setRenameText(e.target.value)} /><div className="mt-5 flex justify-end"><Button type="submit" disabled={renameBusy || !renameText.trim()}>{renameBusy ? '保存中' : '保存名称'}</Button></div>
      </form>
    </DialogContent></Dialog>
    <ConfirmDialog value={confirm} onClose={() => setConfirm(null)} />
    <a href="#main-composer" className="skip-link" onClick={(event) => { event.preventDefault(); document.querySelector<HTMLTextAreaElement>('textarea[aria-label="任务要求"]')?.focus(); }}>跳到任务输入</a>
  </div><Toaster position="top-center" closeButton /></TooltipProvider>;
}
