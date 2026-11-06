import { useEffect, useRef, useState } from 'react';
import { FileText, FolderOpen, Upload, ArrowLeft, ExternalLink } from 'lucide-react';
import type { Attachment } from '@/api/types';
import type { Workspace } from '@/hooks/use-workspace';
import { effectiveAttachments } from '@/lib/presentation';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Busy, InlineError } from '@/components/shared';

export default function MaterialLibrary({ workspace: w, open, onOpenChange }: {
  workspace: Workspace; open: boolean; onOpenChange: (open: boolean) => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [preview, setPreview] = useState<Attachment | null>(null);
  const [error, setError] = useState('');
  const ids = effectiveAttachments(w.conversation?.attachment_ids ?? [], w.draft.attachmentIds, w.draft.attachmentMode);
  useEffect(() => {
    if (!previewId) return;
    let cancelled = false;
    w.api.getAttachment(previewId).then((value) => { if (!cancelled) setPreview(value); })
      .catch((cause: unknown) => { if (!cancelled) setError((cause as Error).message); });
    return () => { cancelled = true; };
  }, [previewId, w.api]);
  const toggle = (id: string) => w.updateDraft({ attachmentMode: 'replace',
    attachmentIds: ids.includes(id) ? ids.filter((value) => value !== id) : [...ids, id] });
  return <Dialog open={open} onOpenChange={(value) => { if (!value) { setPreviewId(null); setPreview(null); setError(''); } onOpenChange(value); }}>
    <DialogContent className="library-dialog sm:max-w-3xl">
      <DialogHeader><DialogTitle>{previewId ? '资料详情' : '资料库'}</DialogTitle>
        <DialogDescription>{previewId ? '表格声明供任务设计参考，现场情况仍需核验。' : '选择本次任务使用的资料，已有批次保留原快照。'}</DialogDescription></DialogHeader>
      {previewId ? <div className="library-preview">
        <Button variant="ghost" size="sm" onClick={() => { setPreviewId(null); setPreview(null); setError(''); }}><ArrowLeft />返回资料库</Button>
        {error ? <InlineError message={error} /> : !preview ? <Skeleton className="h-40 w-full" /> : <>
          <h3>{preview.filename}</h3>
          {preview.inventory.length > 0 ? <div className="table-scroll"><table className="material-table"><thead><tr>
            {['物料', '总数量', '可备套数', '颜色', '场景'].map((text) => <th key={text}>{text}</th>)}</tr></thead>
            <tbody>{preview.inventory.map((item, index) => <tr key={index}><td>{item.name}</td><td>{item.quantity ?? '未提供'}</td>
              <td>{item.available_sets ?? '未提供'}</td><td>{item.color || '未提供'}</td><td>{item.scene || '未提供'}</td></tr>)}</tbody></table></div>
            : <p className="muted-copy">这份资料按文本提供给 Agent，未识别为结构化物料表。</p>}
          <details className="plain-details"><summary>查看解析文本</summary><pre>{preview.parsed_text}</pre></details>
        </>}
      </div> : <>
        {w.role === 'generator' && <div className="library-mode"><label htmlFor="dataset-mode">资料使用方式</label>
          <Select value={w.draft.attachmentMode} disabled={w.interactionBusy} onValueChange={(value) => w.updateDraft({
            attachmentMode: value as typeof w.draft.attachmentMode, ...(value === 'clear' ? { attachmentIds: [] } : {}),
          })}><SelectTrigger id="dataset-mode"><SelectValue /></SelectTrigger><SelectContent>
            <SelectItem value="inherit">沿用当前资料</SelectItem><SelectItem value="replace">使用本次选择</SelectItem>
            <SelectItem value="append">追加到当前资料</SelectItem><SelectItem value="clear">不使用资料</SelectItem>
          </SelectContent></Select>
        </div>}
        <div className="library-files">
          {w.attachments.map((item) => <div key={item.id} className="library-file">
            <Checkbox id={`material-${item.id}`} checked={ids.includes(item.id)} disabled={w.interactionBusy || (!ids.includes(item.id) && ids.length >= 20)}
              onCheckedChange={() => toggle(item.id)} aria-label={`使用 ${item.filename}`} />
            <FileText className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
            <label htmlFor={`material-${item.id}`}><strong>{item.filename}</strong><span>{Math.max(1, Math.round(item.size_bytes / 1024))} KB</span></label>
            <Button variant="ghost" size="sm" onClick={() => { setPreviewId(item.id); setPreview(null); setError(''); }} aria-label={`预览 ${item.filename}`}><ExternalLink className="size-4" /></Button>
          </div>)}
          {!w.attachments.length && <div className="library-empty"><FolderOpen className="size-8" /><h3>先添加一份资料</h3><p>物料清单、场景说明或待审核的任务文件。</p></div>}
        </div>
        <div className="library-bottom"><input type="file" ref={fileInput} className="sr-only" tabIndex={-1} aria-label="上传资料文件"
          accept=".txt,.md,.csv,.xlsx" onChange={(event) => { const file = event.target.files?.[0]; if (file) void w.upload(file); event.target.value = ''; }} />
          <div><Button variant="outline" disabled={w.interactionBusy} onClick={() => fileInput.current?.click()}>
            {w.uploading ? <Busy>正在上传</Busy> : <><Upload />上传资料</>}</Button><p>TXT、MD、CSV、XLSX，单个不超过 5 MB</p></div>
          <Button onClick={() => onOpenChange(false)} disabled={w.uploading}>完成{ids.length ? `选择（${ids.length}）` : ''}</Button>
        </div>
      </>}
    </DialogContent>
  </Dialog>;
}
