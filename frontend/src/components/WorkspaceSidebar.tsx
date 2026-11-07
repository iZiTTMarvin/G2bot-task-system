import { FolderOpen, MessageSquare, MoreHorizontal, PanelLeftClose, Plus, Search, Settings2, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import type { Workspace } from '@/hooks/use-workspace';
import type { AgentRole, Conversation } from '@/api/types';
import { Brand, IconButton } from '@/components/shared';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { isEmptyDefaultConversation } from '@/lib/presentation';

interface Props { workspace: Workspace; onLibrary: () => void; onSettings: () => void;
  onRename: (conversation: Conversation) => void; onCollapse: () => void; onNavigate?: () => void }

export default function WorkspaceSidebar({ workspace: w, onLibrary, onSettings, onRename, onCollapse, onNavigate }: Props) {
  const [search, setSearch] = useState('');
  const hasDraft = (key: string) => {
    const draft = w.drafts[key];
    return Boolean(draft && (draft.text.trim() || draft.attachmentIds.length || draft.attachmentMode !== 'inherit'));
  };
  const isLegacyEmpty = (item: Conversation) => isEmptyDefaultConversation(item) && item.id !== w.activeId && !hasDraft(item.id);
  const recent = w.conversations.filter((item) => !isLegacyEmpty(item));
  const matches = (text: string) => text.toLocaleLowerCase().includes(search.toLocaleLowerCase());
  const filtered = recent.filter((item) => matches(item.title));
  const empty = w.conversations.filter((item) => isLegacyEmpty(item) && matches(item.title));
  const draftRoles = (['generator', 'reviewer'] as AgentRole[]).filter((role) =>
    ((!w.activeId && w.role === role) || hasDraft(`new-${role}`)) &&
    (matches(role === 'generator' ? '新建任务集' : '审核已有任务') || matches(w.drafts[`new-${role}`]?.text ?? '')));
  const renderConversation = (item: Conversation) => <div key={item.id} className={cn('conversation-item', w.activeId === item.id && 'is-active')}>
    <button className="conversation-link" disabled={w.interactionBusy} onClick={() => { w.choose(item); onNavigate?.(); }}
      aria-current={w.activeId === item.id ? 'page' : undefined}>
      {item.agent_role === 'generator' ? <MessageSquare className="size-4" /> : <ShieldCheck className="size-4" />}
      <span><strong>{item.title}</strong><small>{item.agent_role === 'reviewer' ? '审核任务' : '生成任务'}{item.task_count > 0 && ` / ${item.task_count} 条任务`}{hasDraft(item.id) && ' / 有未发送内容'}</small></span>
    </button>
    <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" className="conversation-menu"
      aria-label={`管理会话 ${item.title}`}><MoreHorizontal /></Button></DropdownMenuTrigger>
      <DropdownMenuContent align="start"><DropdownMenuItem onSelect={() => onRename(item)}>重命名</DropdownMenuItem></DropdownMenuContent>
    </DropdownMenu>
  </div>;
  return <aside className="workspace-sidebar" aria-label="任务集导航">
    <div className="sidebar-brand"><Brand /><IconButton label="收起导航" onClick={onCollapse}><PanelLeftClose /></IconButton></div>
    <div className="sidebar-create"><Button className="w-full justify-start" disabled={w.interactionBusy}
      onClick={() => { void w.create('generator'); onNavigate?.(); }}><Plus />新建任务集</Button></div>
    <div className="sidebar-search"><Search className="size-3.5" aria-hidden="true" /><Input aria-label="搜索任务集"
      placeholder="搜索任务集" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
    <div className="sidebar-section-title">历史记录 <span>{recent.length}</span></div>
    <nav className="conversation-list">
      {draftRoles.map((role) => <div key={role} className={cn('conversation-item', !w.activeId && w.role === role && 'is-active')}>
        <button className="conversation-link" disabled={w.interactionBusy} onClick={() => { w.create(role); onNavigate?.(); }}
          aria-current={!w.activeId && w.role === role ? 'page' : undefined}>
          {role === 'generator' ? <MessageSquare className="size-4" /> : <ShieldCheck className="size-4" />}
          <span><strong>{role === 'generator' ? '新建任务集' : '审核已有任务'}</strong><small>{hasDraft(`new-${role}`) ? '未发送的草稿' : '草稿'}</small></span>
        </button>
      </div>)}
      {filtered.map(renderConversation)}
      {empty.length > 0 && <details className="sidebar-legacy"><summary>以前的空会话 <span>{empty.length}</span></summary>{empty.map(renderConversation)}</details>}
      {!w.initializing && !filtered.length && !empty.length && !draftRoles.length && <p className="sidebar-empty">{search ? '没有匹配的记录' : '发送后的会话会保存在这里'}</p>}
    </nav>
    <div className="sidebar-bottom">
      <Button variant="ghost" className="sidebar-action" onClick={onLibrary}><FolderOpen />资料库<span className="ml-auto count-badge">{w.attachments.length}</span></Button>
      <Button variant="ghost" className={cn('sidebar-action', !w.activeId && w.role === 'reviewer' && 'is-active')} aria-pressed={!w.activeId && w.role === 'reviewer'} disabled={w.interactionBusy} onClick={() => { w.create('reviewer'); onNavigate?.(); }}><ShieldCheck />审核已有任务</Button>
      <div className="sidebar-footer"><Button variant="ghost" className="sidebar-action" onClick={onSettings}><Settings2 />模型设置</Button>
        <span className="local-indicator"><i />本地工作区</span></div>
    </div>
  </aside>;
}
