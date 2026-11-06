import { FolderOpen, MessageSquare, MoreHorizontal, PanelLeftClose, Plus, Search, Settings2, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import type { Workspace } from '@/hooks/use-workspace';
import type { Conversation } from '@/api/types';
import { Brand, IconButton } from '@/components/shared';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';

interface Props { workspace: Workspace; onLibrary: () => void; onSettings: () => void;
  onRename: (conversation: Conversation) => void; onCollapse: () => void; onNavigate?: () => void }

export default function WorkspaceSidebar({ workspace: w, onLibrary, onSettings, onRename, onCollapse, onNavigate }: Props) {
  const [search, setSearch] = useState('');
  const filtered = w.conversations.filter((c) => c.title.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  return <aside className="workspace-sidebar" aria-label="任务集导航">
    <div className="sidebar-brand"><Brand /><IconButton label="收起导航" onClick={onCollapse}><PanelLeftClose /></IconButton></div>
    <div className="sidebar-create"><Button className="w-full justify-start" disabled={w.interactionBusy}
      onClick={() => { void w.create('generator'); onNavigate?.(); }}><Plus />新建任务集</Button></div>
    <div className="sidebar-search"><Search className="size-3.5" aria-hidden="true" /><Input aria-label="搜索任务集"
      placeholder="搜索任务集" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
    <div className="sidebar-section-title">最近任务集 <span>{w.conversations.length}</span></div>
    <nav className="conversation-list">
      {filtered.map((item) => <div key={item.id} className={cn('conversation-item', w.activeId === item.id && 'is-active')}>
        <button className="conversation-link" disabled={w.interactionBusy} onClick={() => { w.choose(item); onNavigate?.(); }}
          aria-current={w.activeId === item.id ? 'page' : undefined}>
          {item.agent_role === 'generator' ? <MessageSquare className="size-4" /> : <ShieldCheck className="size-4" />}
          <span><strong>{item.title}</strong><small>{item.agent_role === 'reviewer' ? '审核记录' : '任务生成'}{item.task_count > 0 && ` / ${item.task_count} 条任务`}</small></span>
        </button>
        <DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" className="conversation-menu"
          aria-label={`管理任务集 ${item.title}`}><MoreHorizontal /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="start"><DropdownMenuItem onSelect={() => onRename(item)}>重命名</DropdownMenuItem></DropdownMenuContent>
        </DropdownMenu>
      </div>)}
      {!w.initializing && !filtered.length && <p className="sidebar-empty">{search ? '没有匹配的任务集' : '你的任务集会保存在这里'}</p>}
    </nav>
    <div className="sidebar-bottom">
      <Button variant="ghost" className="sidebar-action" onClick={onLibrary}><FolderOpen />资料库<span className="ml-auto count-badge">{w.attachments.length}</span></Button>
      <Button variant="ghost" className="sidebar-action" disabled={w.interactionBusy} onClick={() => { void w.create('reviewer'); onNavigate?.(); }}><ShieldCheck />审核已有任务</Button>
      <div className="sidebar-footer"><Button variant="ghost" className="sidebar-action" onClick={onSettings}><Settings2 />模型设置</Button>
        <span className="local-indicator"><i />本地工作区</span></div>
    </div>
  </aside>;
}
