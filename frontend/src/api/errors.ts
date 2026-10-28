// 统一错误对象：与后端 {"error": {code, message, details}} 对齐
import type { ErrorInfo } from './types';

export class ApiError extends Error {
  code: string;
  details: Record<string, unknown>;

  constructor(code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.code = code;
    this.details = details;
  }

  get isConflict(): boolean {
    return this.code === 'REVISION_CONFLICT';
  }
}

export function throwFromResponse(status: number, body: unknown): never {
  const shaped = body as { error?: ErrorInfo };
  if (shaped && shaped.error) {
    throw new ApiError(shaped.error.code, shaped.error.message, shaped.error.details ?? {});
  }
  throw new ApiError(`HTTP_${status}`, `请求失败（HTTP ${status}）`, {});
}
