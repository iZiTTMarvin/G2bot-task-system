// API 适配器选择：默认 mock（前端独立开发），可切换真实服务（联调）。
// mock 必须有可见标识（App 顶栏 Tag），关闭 mock 才算正式联调。
import type { ApiClient } from './client';
import { mockClient } from './mock';
import { realClient } from './real';

const STORAGE_KEY = 'g2.api.mode';

export type ApiMode = 'mock' | 'real';

export function getApiMode(): ApiMode {
  const url = new URL(window.location.href);
  const param = url.searchParams.get('api');
  if (param === 'real' || param === 'mock') {
    localStorage.setItem(STORAGE_KEY, param);
    url.searchParams.delete('api');
    window.history.replaceState(null, '', url.toString());
  }
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === 'real' ? 'real' : 'mock';
}

export function setApiMode(mode: ApiMode): void {
  localStorage.setItem(STORAGE_KEY, mode);
}

export function getApiClient(): ApiClient {
  return getApiMode() === 'mock' ? mockClient : realClient;
}

export { mockClient, realClient };
