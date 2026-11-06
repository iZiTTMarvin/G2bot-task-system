import type { ComponentProps, ReactNode } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';

export function Brand({ compact = false }: { compact?: boolean }) {
  return <div className="brand-lockup"><span className="brand-symbol" aria-hidden="true">G2</span>
    {!compact && <div><strong>任务工作台</strong><span>遥操作采集任务</span></div>}</div>;
}

export function IconButton({ label, children, ...props }: ComponentProps<typeof Button> & { label: string }) {
  return <Tooltip><TooltipTrigger asChild><Button variant="ghost" size="icon" aria-label={label} {...props}>{children}</Button></TooltipTrigger>
    <TooltipContent>{label}</TooltipContent></Tooltip>;
}

export function Busy({ children }: { children: ReactNode }) {
  return <span className="inline-flex items-center gap-2"><Loader2 className="size-4 animate-spin" aria-hidden="true" />{children}</span>;
}

export function InlineError({ message, action, onAction }: { message: string; action?: string; onAction?: () => void }) {
  return <div className="inline-error" role="alert"><AlertCircle className="size-4 shrink-0" aria-hidden="true" />
    <span>{message}</span>{action && onAction && <Button variant="ghost" size="sm" onClick={onAction}>{action}</Button>}</div>;
}

export interface ConfirmState { title: string; description: string; action?: string; destructive?: boolean; onConfirm: () => void }

export function ConfirmDialog({ value, onClose }: { value: ConfirmState | null; onClose: () => void }) {
  return <AlertDialog open={Boolean(value)} onOpenChange={(open) => { if (!open) onClose(); }}>
    <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{value?.title}</AlertDialogTitle>
      <AlertDialogDescription>{value?.description}</AlertDialogDescription></AlertDialogHeader>
      <AlertDialogFooter><AlertDialogCancel>取消</AlertDialogCancel>
        <AlertDialogAction className={value?.destructive ? 'bg-destructive text-white hover:bg-destructive/90' : ''}
          onClick={() => value?.onConfirm()}>{value?.action ?? '继续'}</AlertDialogAction></AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>;
}
