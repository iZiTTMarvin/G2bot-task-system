import { useEffect, useState } from 'react';
import { Eye, EyeOff, KeyRound, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import type { ApiClient } from '@/api/client';
import type { Settings } from '@/api/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Busy, InlineError } from '@/components/shared';

export default function SettingsPage({ api, onSaved, onDirtyChange }: { api: ApiClient; onSaved?: () => void; onDirtyChange?: (dirty: boolean) => void }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [values, setValues] = useState({ api_format: 'openai' as Settings['api_format'], base_url: '', generation_model: '', review_model: '' });
  const [key, setKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const dirty = Boolean(settings) && (Boolean(key) || Object.entries(values).some(([field, value]) => settings?.[field as keyof Settings] !== value));
  useEffect(() => { onDirtyChange?.(dirty || saving); }, [dirty, saving, onDirtyChange]);
  useEffect(() => {
    let cancelled = false;
    api.getSettings().then((data) => {
      if (cancelled) return;
      setSettings(data); setValues({ api_format: data.api_format, base_url: data.base_url, generation_model: data.generation_model, review_model: data.review_model }); setError('');
    }).catch((cause: unknown) => { if (!cancelled) setError((cause as Error).message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [api, reload]);
  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving || !settings) return;
    setSaving(true); setError('');
    try {
      const data = await api.updateSettings({ ...values, base_url: values.base_url.trim(), generation_model: values.generation_model.trim(),
        review_model: values.review_model.trim() || values.generation_model.trim(), ...(key.trim() ? { api_key: key.trim() } : {}) });
      setSettings(data); setValues({ api_format: data.api_format, base_url: data.base_url, generation_model: data.generation_model, review_model: data.review_model }); setKey('');
      toast.success('模型设置已保存'); onSaved?.();
    } catch (cause) { setError((cause as Error).message); }
    finally { setSaving(false); }
  };
  if (loading) return <div className="settings-loading"><Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" /></div>;
  if (!settings) return <InlineError message={error || '无法加载设置'} action="重新加载" onAction={() => setReload((v) => v + 1)} />;
  return <form className="settings-form" onSubmit={(event) => void save(event)}>
    {error && <InlineError message={error} />}
    <div className="field"><label htmlFor="api-format">API 格式</label><Select value={values.api_format} disabled={saving} onValueChange={(value) => setValues((current) => ({ ...current, api_format: value as Settings['api_format'] }))}>
      <SelectTrigger id="api-format"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="openai">OpenAI 兼容</SelectItem><SelectItem value="anthropic">Anthropic 兼容</SelectItem></SelectContent></Select></div>
    <div className="field"><label htmlFor="base-url">服务地址</label><Input id="base-url" type="url" required disabled={saving} value={values.base_url} placeholder="https://api.example.com/v1"
      onChange={(e) => setValues((current) => ({ ...current, base_url: e.target.value }))} /><p>支持 Base URL 或完整接口地址。404 通常需要核对地址与接口格式。</p></div>
    <div className="field"><label htmlFor="generation-model">生成模型</label><Input id="generation-model" required disabled={saving} value={values.generation_model} placeholder="输入服务商提供的模型名称" onChange={(e) => setValues((current) => ({ ...current, generation_model: e.target.value }))} /></div>
    <div className="field"><label htmlFor="api-key">API Key {settings.api_key_set && <span className="configured-label"><ShieldCheck className="size-3.5" />已配置</span>}</label>
      <div className="password-field"><Input id="api-key" type={showKey ? 'text' : 'password'} disabled={saving} value={key} autoComplete="new-password" onChange={(e) => setKey(e.target.value)} placeholder={settings.api_key_set ? '留空保留当前密钥' : '输入 API Key'} />
        <Button type="button" variant="ghost" size="icon" aria-label={showKey ? '隐藏密钥' : '显示密钥'} onClick={() => setShowKey((value) => !value)}>{showKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}</Button></div>
      <p className="key-note"><KeyRound className="size-3" />密钥仅提交到本地服务，不会回显已保存的值。</p></div>
    <details className="plain-details"><summary>高级设置</summary><div className="field mt-4"><label htmlFor="review-model">审核模型</label><Input id="review-model" disabled={saving} value={values.review_model} placeholder="留空使用生成模型" onChange={(e) => setValues((current) => ({ ...current, review_model: e.target.value }))} /></div></details>
    <div className="settings-actions"><span>{dirty ? '有未保存的修改' : '当前设置已保存'}</span><Button type="submit" disabled={saving || !dirty}>{saving ? <Busy>保存中</Busy> : '保存设置'}</Button></div>
  </form>;
}
