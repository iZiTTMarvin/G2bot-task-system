// 前端 mock：与真实服务同一接口、同一语义；只验证交互，不含真实模型/规则。
// 覆盖接口契约第 9 节场景，可通过 mockFaults 注入故障。
import type { ApiClient, BatchCreateInput } from './client';
import { ApiError } from './errors';
import type {
  Attachment,
  Batch,
  DecisionResult,
  HumanDecision,
  Review,
  Run,
  Settings,
  TaskContent,
  TaskDetail,
  TaskStatus,
  TaskVersion,
  ValidationReport,
} from './types';

export interface MockFaults {
  nextSaveConflict: boolean;
  nextApproveFail: boolean;
  generateMode: 'ok' | 'model_error' | 'partial_review_fail' | 'ai_reject';
  networkDelayMs: number;
}

export const mockFaults: MockFaults = {
  nextSaveConflict: false,
  nextApproveFail: false,
  generateMode: 'ok',
  networkDelayMs: 120,
};

export function resetMockFaults(): void {
  mockFaults.nextSaveConflict = false;
  mockFaults.nextApproveFail = false;
  mockFaults.generateMode = 'ok';
  mockFaults.networkDelayMs = 120;
}

let seq = 0;
const nid = (p: string) => `${p}_mock_${String(++seq).padStart(3, '0')}`;
const now = () => new Date().toISOString();

interface MockTask {
  id: string;
  batch_id: string;
  seq: number;
  status: TaskStatus;
  revision: number;
  current_version_id: string;
  busy_run_id: string | null;
  last_error: { code: string; message: string; details: Record<string, unknown>; request_id: string } | null;
  created_at: string;
  updated_at: string;
  versions: Record<string, TaskVersion>;
  reviews: Review[];
  decisions: HumanDecision[];
}

interface MockBatch {
  id: string; name: string; goal: string; task_count: number; task_mode: 'standard' | 'long';
  reference_text: string; attachment_ids: string[]; rule_snapshot_id: string;
  created_at: string;
}

interface MockRun extends Run {}

interface State {
  settings: Settings & { api_key?: string };
  attachments: Record<string, Attachment>;
  batches: Record<string, MockBatch>;
  tasks: Record<string, MockTask>;
  runs: Record<string, MockRun>;
  exports: Record<string, { id: string; batch_id: string; filename: string; download_url: string; created_at: string; versions: { task_id: string; version_id: string }[] }>;
  idempotency: Map<string, { digest: string; status: 'in_progress' | 'committed'; statusCode: number; result: unknown }>;
}

const state: State = {
  settings: { base_url: 'https://api.example.com/v1', generation_model: 'mock-gen', review_model: 'mock-rev', api_key_set: false },
  attachments: {},
  batches: {},
  tasks: {},
  runs: {},
  exports: {},
  idempotency: new Map(),
};

const stepRanges: Record<string, [number, number]> = { standard: [10, 20], long: [20, 30] };

function makeSteps(count: number, tag: string): string[] {
  const steps: string[] = [];
  for (let i = 0; i < count; i += 1) {
    steps.push(i % 2 === 0
      ? `把【${tag}物品${i % 4}】从桌面拿起放进【${tag}收纳筐】`
      : `将【${tag}物品${i % 4}】对齐摆好`);
  }
  return steps;
}

function deriveMaterials(steps: string[]): { name: string; quantity: number }[] {
  const map = new Map<string, Set<string>>();
  for (const step of steps) {
    for (const m of step.matchAll(/【([^】]+)】/g)) {
      const base = m[1].replace(/\d+$/, '');
      if (!map.has(base)) map.set(base, new Set());
      map.get(base)!.add(m[1]);
    }
  }
  return [...map.entries()].map(([name, set]) => ({ name, quantity: set.size }));
}

function validate(content: TaskContent, mode: string): ValidationReport {
  const [lo, hi] = stepRanges[mode] ?? [10, 20];
  const issues: ValidationReport['issues'] = [];
  if (content.steps.length < lo || content.steps.length > hi) {
    issues.push({
      code: 'STEP_COUNT', severity: 'error',
      message: `步骤数 ${content.steps.length}，应在 ${lo}~${hi} 步`, step_no: null, rule_id: 'L-003',
    });
  }
  const derived = deriveMaterials(content.steps);
  const declared = new Map(content.materials.map((m) => [m.name, m.quantity]));
  for (const d of derived) {
    if (!declared.has(d.name)) {
      issues.push({ code: 'MATERIAL_MISSING', severity: 'error', message: `单套物料缺少『${d.name}${d.quantity}』`, step_no: null, rule_id: null });
    } else if (declared.get(d.name) !== d.quantity) {
      issues.push({ code: 'MATERIAL_MISMATCH', severity: 'error', message: `物料『${d.name}』应为 ${d.quantity} 件`, step_no: null, rule_id: null });
    }
  }
  for (const [name] of declared) {
    if (!derived.some((d) => d.name === name)) {
      issues.push({ code: 'MATERIAL_EXTRA', severity: 'error', message: `物料『${name}』步骤中未使用`, step_no: null, rule_id: null });
    }
  }
  return {
    status: issues.some((i) => i.severity === 'error') ? 'failed' : 'passed',
    issues, checked_at: now(), rule_snapshot_id: 'rs_mock_0000000000000',
  };
}

function contentOf(task: MockTask): TaskContent {
  return task.versions[task.current_version_id].content;
}

function insertVersion(task: MockTask, content: TaskContent, author: TaskVersion['author_type'], note: string, runId: string | null, mode: string): TaskVersion {
  const version: TaskVersion = {
    id: nid('ver'), task_id: task.id,
    version_no: Math.max(...Object.values(task.versions).map((v) => v.version_no)) + 1,
    parent_version_id: task.current_version_id, author_type: author,
    content, change_note: note, validation: validate(content, mode), run_id: runId, created_at: now(),
  };
  task.versions[version.id] = version;
  task.current_version_id = version.id;
  task.revision += 1;
  task.updated_at = now();
  return version;
}

function toSummary(task: MockTask) {
  const v = task.versions[task.current_version_id];
  return {
    id: task.id, batch_id: task.batch_id, name: v.content.name, step_count: v.content.steps.length,
    version_no: v.version_no, status: task.status, revision: task.revision,
    human_edited: v.author_type === 'human', busy_run_id: task.busy_run_id,
    created_at: task.created_at, updated_at: task.updated_at,
  };
}

function toDetail(task: MockTask): TaskDetail {
  const latestReview: Review | null = task.reviews.length
    ? task.reviews.reduce<Review>((a, b) => (a.created_at >= b.created_at ? a : b), task.reviews[0])
    : null;
  const v = task.versions[task.current_version_id];
  return {
    summary: toSummary(task),
    current_version: v,
    latest_review: latestReview,
    last_error: task.last_error,
    can_decide: task.status === 'human_pending' && !task.busy_run_id,
    ai_review_matches_current_version: !!latestReview && latestReview.task_version_id === task.current_version_id,
  };
}

function batchPayload(b: MockBatch): Batch {
  const tasks = Object.values(state.tasks).filter((t) => t.batch_id === b.id);
  const counts = { pending_review: 0, ai_reviewing: 0, human_pending: 0, ai_rejected: 0, review_failed: 0, approved: 0, rejected: 0 } as Batch['task_counts'];
  for (const t of tasks) counts[t.status] += 1;
  const runs = Object.values(state.runs).filter((r) => r.batch_id === b.id).sort((a, c) => a.created_at.localeCompare(c.created_at));
  const active = runs.some((r) => r.status === 'queued' || r.status === 'running');
  return {
    id: b.id, name: b.name, goal: b.goal, task_count: b.task_count, task_mode: b.task_mode,
    reference_text: b.reference_text, attachment_ids: b.attachment_ids, rule_snapshot_id: b.rule_snapshot_id,
    task_counts: counts,
    latest_run_id: runs.length ? runs[runs.length - 1].id : null,
    can_generate: tasks.length === 0 && !active,
    created_at: b.created_at,
  };
}

function getTaskOr404(taskId: string): MockTask {
  const t = state.tasks[taskId];
  if (!t) throw new ApiError('NOT_FOUND', '任务不存在', {});
  return t;
}

function errBusy(t: MockTask): void {
  if (t.busy_run_id) throw new ApiError('TASK_BUSY', '任务正在被后台作业处理', { busy_run_id: t.busy_run_id });
}

function checkRevision(t: MockTask, expected: number, versionId?: string): void {
  if (t.revision !== expected) {
    throw new ApiError('REVISION_CONFLICT', '任务已更新，请重新加载后合并修改', { expected_revision: expected, current_revision: t.revision });
  }
  if (versionId && versionId !== t.current_version_id) {
    throw new ApiError('REVISION_CONFLICT', '操作必须针对当前版本；任务已更新，请刷新后重试', { version_id: versionId, current_version_id: t.current_version_id });
  }
}

// ---------- 幂等 ----------

function digest(obj: unknown): string {
  return JSON.stringify(obj);
}

function idempotent<T>(scope: string, key: string, body: unknown, run: () => { status: number; result: T }): T {
  const d = digest(body);
  const existing = state.idempotency.get(`${scope}|${key}`);
  if (existing) {
    if (existing.digest !== d) throw new ApiError('IDEMPOTENCY_CONFLICT', '同一幂等键已用于不同请求', {});
    if (existing.status === 'in_progress') throw new ApiError('REQUEST_IN_PROGRESS', '同键请求正在处理中', {});
    return existing.result as T;
  }
  state.idempotency.set(`${scope}|${key}`, { digest: d, status: 'in_progress', statusCode: 0, result: undefined });
  let outcome: { status: number; result: unknown };
  try {
    outcome = run();
  } catch (e) {
    // 前置校验/业务校验失败不占用幂等键（与真实后端一致）
    state.idempotency.delete(`${scope}|${key}`);
    throw e;
  }
  state.idempotency.set(`${scope}|${key}`, { digest: d, status: 'committed', statusCode: outcome.status, result: outcome.result });
  return outcome.result as T;
}

// ---------- 作业模拟 ----------

function newRun(batchId: string, taskId: string | null, taskIds: string[], kind: MockRun['kind'], total: number): MockRun {
  const run: MockRun = {
    id: nid('run'), batch_id: batchId, task_id: taskId, task_ids: taskIds, kind,
    stage: 'queued', status: 'queued', progress: { total, completed: 0, failed: 0 },
    error: null, created_at: now(), started_at: null, finished_at: null,
  };
  state.runs[run.id] = run;
  return run;
}

function reviewOne(task: MockTask, run: MockRun, mode: 'ok' | 'timeout' | 'reject'): void {
  const version = task.versions[task.current_version_id];
  if (version.validation.status !== 'passed') {
    task.status = 'ai_rejected';
    run.progress.completed += 1;
    return;
  }
  task.status = 'ai_reviewing';
  if (mode === 'timeout') {
    task.status = 'review_failed';
    task.last_error = { code: 'MODEL_TIMEOUT', message: '审核模型超时', details: {}, request_id: run.id };
    run.progress.completed += 1;
    run.progress.failed += 1;
    return;
  }
  if (mode === 'reject') {
    task.reviews.push({
      id: nid('rev'), task_id: task.id, task_version_id: version.id, reviewer_id: 'reviewer-default', run_id: run.id,
      verdict: 'needs_changes',
      issues: [{ severity: 'error', step_no: 1, rule_id: 'MOCK', quote: version.content.steps[0], message: '终态不符合要求：用品应收好待用', suggestion: '补一步整理终态' }],
      summary: '模拟：审核退回', created_at: now(),
    });
    task.status = 'ai_rejected';
  } else {
    task.reviews.push({
      id: nid('rev'), task_id: task.id, task_version_id: version.id, reviewer_id: 'reviewer-default', run_id: run.id,
      verdict: 'pass', issues: [], summary: '模拟：审核通过', created_at: now(),
    });
    task.status = 'human_pending';
  }
  run.progress.completed += 1;
}

function runGenerate(batchId: string, mode: MockFaults['generateMode']): Run {
  const batch = state.batches[batchId];
  const run = newRun(batchId, null, [], 'generate_batch', batch.task_count);
  const created: MockTask[] = [];

  setTimeout(() => {
    run.status = 'running'; run.started_at = now(); run.stage = 'generating';
  }, 150);

  setTimeout(() => {
    if (mode === 'model_error') {
      run.status = 'failed';
      run.error = { code: 'MODEL_AUTH_ERROR', message: '模拟：模型认证失败', details: {}, request_id: run.id };
      run.finished_at = now();
      return;
    }
    run.stage = 'validating';
    for (let i = 0; i < batch.task_count; i += 1) {
      const tag = `演示${i + 1}`;
      const [lo] = stepRanges[batch.task_mode] ?? [10, 20];
      const steps = makeSteps(lo + (i % 3) * 2, tag);
      const content: TaskContent = { name: `模拟基地-演示任务${i + 1}`, steps, materials: deriveMaterials(steps) };
      const task: MockTask = {
        id: nid('task'), batch_id: batchId, seq: i + 1, status: 'pending_review', revision: 1,
        current_version_id: '', busy_run_id: run.id, last_error: null,
        created_at: now(), updated_at: now(), versions: {}, reviews: [], decisions: [],
      };
      const v: TaskVersion = {
        id: nid('ver'), task_id: task.id, version_no: 1, parent_version_id: null, author_type: 'ai',
        content, change_note: '首次生成草稿', validation: validate(content, batch.task_mode),
        run_id: run.id, created_at: now(),
      };
      task.versions[v.id] = v;
      task.current_version_id = v.id;
      state.tasks[task.id] = task;
      created.push(task);
    }
    run.task_ids = created.map((t) => t.id);
    run.stage = 'reviewing';
  }, 900);

  setTimeout(() => {
    if (run.status !== 'queued' && run.status !== 'running') return;
    created.forEach((task, i) => {
      const reviewMode = mode === 'partial_review_fail' && i === 1 ? 'timeout' : mode === 'ai_reject' ? 'reject' : 'ok';
      reviewOne(task, run, reviewMode);
    });
    created.forEach((t) => { t.busy_run_id = null; t.revision += 1; t.updated_at = now(); });
    run.stage = 'done';
    run.status = run.progress.failed > 0 ? 'failed' : 'succeeded';
    run.finished_at = now();
    if (run.status === 'failed' && run.progress.failed > 0) {
      run.error = { code: 'MODEL_TIMEOUT', message: '部分任务审核失败，其余结果已保留', details: {}, request_id: run.id };
    }
  }, 2200 + 300 * batch.task_count);

  return { ...run };
}

function runSingleTask(taskId: string, kind: 'review_task' | 'revise_task', feedback: string): Run {
  const task = getTaskOr404(taskId);
  const run = newRun(task.batch_id, taskId, [taskId], kind, 1);
  const mode = state.batches[task.batch_id]?.task_mode ?? 'long';

  setTimeout(() => { run.status = 'running'; run.started_at = now(); run.stage = kind === 'revise_task' ? 'generating' : 'validating'; }, 120);
  setTimeout(() => {
    if (run.status !== 'queued' && run.status !== 'running') return;
    if (kind === 'revise_task') {
      const base = contentOf(task);
      const steps = [...base.steps];
      steps[steps.length - 1] += '，整理为待用终态';
      const content: TaskContent = { name: `${base.name}（已重写）`, steps, materials: deriveMaterials(steps) };
      insertVersion(task, content, 'ai_revision', `按反馈重写：${feedback.slice(0, 40)}`, run.id, mode);
      task.status = 'pending_review';
      run.stage = 'reviewing';
      reviewOne(task, run, 'ok');
    } else {
      const v = task.versions[task.current_version_id];
      v.validation = validate(v.content, mode);
      run.stage = 'reviewing';
      reviewOne(task, run, 'ok');
    }
    task.busy_run_id = null;
    task.revision += 1;
    task.updated_at = now();
    run.stage = 'done';
    run.status = run.progress.failed > 0 ? 'failed' : 'succeeded';
    run.finished_at = now();
  }, 1200);
  return { ...run };
}

// ---------- 种子数据（契约 9.1/9.2/9.9） ----------

function seed(): void {
  seq = 0;
  state.attachments = {}; state.batches = {}; state.tasks = {}; state.runs = {}; state.exports = {};
  state.idempotency = new Map();

  const batch: MockBatch = {
    id: nid('batch'), name: '居家演示批次', goal: '围绕真实居家活动设计任务',
    task_count: 3, task_mode: 'long', reference_text: '台面物料：收纳篮、毛巾、带拉链的收纳袋',
    attachment_ids: [], rule_snapshot_id: 'rs_mock_0000000000000', created_at: now(),
  };
  state.batches[batch.id] = batch;

  const mkTask = (i: number, status: TaskStatus, humanEdit: boolean): MockTask => {
    const steps = makeSteps(20 + i, `演示${i}`);
    const content: TaskContent = { name: `模拟基地-演示任务${i}`, steps, materials: deriveMaterials(steps) };
    const task: MockTask = {
      id: nid('task'), batch_id: batch.id, seq: i, status, revision: 1,
      current_version_id: '', busy_run_id: null,
      last_error: status === 'review_failed' ? { code: 'RUN_INTERRUPTED', message: '服务重启中断了本次作业', details: {}, request_id: 'mock' } : null,
      created_at: now(), updated_at: now(), versions: {}, reviews: [], decisions: [],
    };
    const v1: TaskVersion = {
      id: nid('ver'), task_id: task.id, version_no: 1, parent_version_id: null, author_type: 'ai',
      content, change_note: '首次生成草稿', validation: validate(content, 'long'), run_id: null, created_at: now(),
    };
    task.versions[v1.id] = v1;
    task.current_version_id = v1.id;
    task.reviews.push({
      id: nid('rev'), task_id: task.id, task_version_id: v1.id, reviewer_id: 'reviewer-default', run_id: nid('run'),
      verdict: status === 'ai_rejected' ? 'needs_changes' : 'pass',
      issues: status === 'ai_rejected'
        ? [{ severity: 'error', step_no: 3, rule_id: 'MOCK', quote: content.steps[2], message: '步骤顺序不符合真实作业流', suggestion: '先取出再整理' }]
        : [],
      summary: status === 'ai_rejected' ? '模拟：审核退回' : '模拟：审核通过', created_at: now(),
    });
    if (humanEdit) {
      const edited: TaskContent = {
        ...content,
        name: content.name,
        steps: content.steps.map((s, idx) => (idx === 0 ? `${s}（人工调整）` : s)),
      };
      insertVersion(task, edited, 'human', '人工微调首步', null, 'long');
    }
    return task;
  };

  // 场景 2：AI 原稿 v1 + 人工稿 v2，latest_review 仍指向 v1
  for (const [i, status, humanEdit] of [
    [1, 'human_pending', true],
    [2, 'ai_rejected', false],
    [3, 'review_failed', false],
  ] as [number, TaskStatus, boolean][]) {
    const t = mkTask(i, status, humanEdit);
    state.tasks[t.id] = t;
  }

  // 场景 9：可导出的已通过批次
  const batch2: MockBatch = {
    id: nid('batch'), name: '已通过可导出批次', goal: '整理桌面用品',
    task_count: 2, task_mode: 'standard', reference_text: '书本、文件夹',
    attachment_ids: [], rule_snapshot_id: 'rs_mock_0000000000000', created_at: now(),
  };
  state.batches[batch2.id] = batch2;
  for (let i = 4; i <= 5; i += 1) {
    const t = mkTask(i, 'human_pending', false);
    t.batch_id = batch2.id;
    const v = t.versions[t.current_version_id];
    v.validation = { ...v.validation, status: 'passed', issues: [] };
    // standard 模式校验重新通过
    v.content = { ...v.content, steps: makeSteps(12, `标准${i}`), };
    v.content = { ...v.content, materials: deriveMaterials(v.content.steps) };
    v.validation = validate(v.content, 'standard');
    t.status = 'approved';
    t.decisions.push({
      id: nid('dec'), task_id: t.id, task_version_id: t.current_version_id,
      decision: 'approve', reason: '', created_at: now(),
    });
    state.tasks[t.id] = t;
  }
}

seed();

// ---------- API 实现 ----------

const delay = () => new Promise((r) => setTimeout(r, mockFaults.networkDelayMs));

export const mockClient: ApiClient & { simulateRestart(): void; reseed(): void } = {
  getHealth: async () => ({ status: 'ok', database: 'ok', contract_version: '0.1.0' }),
  getSettings: async () => {
    await delay();
    const { api_key, ...rest } = state.settings as Settings & { api_key?: string };
    return { ...rest, api_key_set: !!api_key };
  },
  updateSettings: async (payload) => {
    await delay();
    state.settings = {
      base_url: payload.base_url, generation_model: payload.generation_model,
      review_model: payload.review_model,
      api_key: payload.api_key ?? (state.settings as Settings & { api_key?: string }).api_key,
    } as Settings & { api_key?: string };
    const { api_key, ...rest } = state.settings as Settings & { api_key?: string };
    return { ...rest, api_key_set: !!api_key };
  },

  uploadAttachment: async (file) => {
    await delay();
    if (file.size > 5 * 1024 * 1024) throw new ApiError('FILE_TOO_LARGE', '文件超过 5 MiB 上限', {});
    const text = await file.text();
    const att: Attachment = {
      id: nid('att'), filename: file.name, media_type: file.type || 'text/plain',
      size_bytes: file.size, text_length: text.length, content_hash: 'mock',
      created_at: now(), parsed_text: text.slice(0, 50000),
    };
    state.attachments[att.id] = att;
    return att;
  },
  listAttachments: async (page = 1, pageSize = 20) => {
    await delay();
    const all = Object.values(state.attachments).sort((a, b) => b.created_at.localeCompare(a.created_at));
    return {
      items: all.slice((page - 1) * pageSize, page * pageSize).map(({ parsed_text: _t, ...s }) => s),
      total: all.length, page, page_size: pageSize,
    };
  },
  getAttachment: async (id) => {
    await delay();
    const att = state.attachments[id];
    if (!att) throw new ApiError('NOT_FOUND', '附件不存在', {});
    return att;
  },

  createBatch: async (input: BatchCreateInput, key) => {
    await delay();
    return idempotent('POST /batches', key, input, () => {
      if (!input.reference_text.trim() && input.attachment_ids.length === 0) {
        throw new ApiError('VALIDATION_ERROR', '参考资料文本与附件至少提供一项', {});
      }
      const batch: MockBatch = {
        id: nid('batch'), name: input.name, goal: input.goal, task_count: input.task_count,
        task_mode: input.task_mode as 'standard' | 'long', reference_text: input.reference_text,
        attachment_ids: input.attachment_ids, rule_snapshot_id: 'rs_mock_0000000000000', created_at: now(),
      };
      state.batches[batch.id] = batch;
      return { status: 201, result: batchPayload(batch) };
    });
  },
  listBatches: async (page = 1, pageSize = 20) => {
    await delay();
    const all = Object.values(state.batches).sort((a, b) => b.created_at.localeCompare(a.created_at));
    return { items: all.map(batchPayload), total: all.length, page, page_size: pageSize };
  },
  getBatch: async (id) => {
    await delay();
    const b = state.batches[id];
    if (!b) throw new ApiError('NOT_FOUND', '批次不存在', {});
    return batchPayload(b);
  },
  generateBatch: async (batchId, key) => {
    await delay();
    return idempotent(`POST /batches/${batchId}/generate`, key, {}, () => {
      const b = state.batches[batchId];
      if (!b) throw new ApiError('NOT_FOUND', '批次不存在', {});
      const active = Object.values(state.runs).some((r) => r.status === 'queued' || r.status === 'running');
      if (active) throw new ApiError('RUN_BUSY', '已有一个模型作业在运行', {});
      const has = Object.values(state.tasks).some((t) => t.batch_id === batchId);
      if (has) throw new ApiError('BATCH_ALREADY_GENERATED', '该批次已生成过任务', {});
      return { status: 202, result: runGenerate(batchId, mockFaults.generateMode) };
    });
  },

  getRun: async (runId) => {
    await delay();
    const r = state.runs[runId];
    if (!r) throw new ApiError('NOT_FOUND', '作业不存在', {});
    return { ...r };
  },

  listTasks: async (params) => {
    await delay();
    let all = Object.values(state.tasks);
    if (params.batch_id) all = all.filter((t) => t.batch_id === params.batch_id);
    if (params.q) all = all.filter((t) => contentOf(t).name.includes(params.q!));
    const counts = { pending_review: 0, ai_reviewing: 0, human_pending: 0, ai_rejected: 0, review_failed: 0, approved: 0, rejected: 0 } as Batch['task_counts'];
    for (const t of all) counts[t.status] += 1;
    if (params.status) all = all.filter((t) => t.status === params.status);
    all.sort((a, b) => b.created_at.localeCompare(a.created_at));
    const page = params.page ?? 1;
    const pageSize = params.page_size ?? 20;
    return {
      items: all.slice((page - 1) * pageSize, page * pageSize).map(toSummary),
      total: all.length, page, page_size: pageSize, status_counts: counts,
    };
  },
  getTask: async (taskId) => {
    await delay();
    return toDetail(getTaskOr404(taskId));
  },
  listVersions: async (taskId) => {
    await delay();
    const t = getTaskOr404(taskId);
    return { items: Object.values(t.versions).sort((a, b) => b.version_no - a.version_no) };
  },
  saveVersion: async (taskId, payload, key) => {
    await delay();
    return idempotent(`POST /tasks/${taskId}/versions`, key, payload, () => {
      const t = getTaskOr404(taskId);
      errBusy(t);
      if (t.status === 'approved' || t.status === 'ai_reviewing') {
        throw new ApiError('INVALID_STATE', `当前状态 ${t.status} 不允许保存新版本`, {});
      }
      checkRevision(t, payload.expected_revision);
      const current = contentOf(t);
      const next = payload.content;
      if (mockFaults.nextSaveConflict) {
        mockFaults.nextSaveConflict = false;
        t.revision += 1; // 模拟另一页面已先保存
        throw new ApiError('REVISION_CONFLICT', '任务已更新（另一页面先保存），请重新加载后合并修改', { expected_revision: payload.expected_revision, current_revision: t.revision });
      }
      if (JSON.stringify(current) === JSON.stringify(next)) {
        throw new ApiError('NO_CHANGES', '没有需要保存的修改', {});
      }
      const mode = state.batches[t.batch_id]?.task_mode ?? 'long';
      insertVersion(t, next, 'human', payload.change_note ?? '', null, mode);
      return { status: 201, result: toDetail(t) };
    });
  },
  listReviews: async (taskId) => {
    await delay();
    return { items: [...getTaskOr404(taskId).reviews].sort((a, b) => b.created_at.localeCompare(a.created_at)) };
  },
  listDecisions: async (taskId) => {
    await delay();
    return { items: [...getTaskOr404(taskId).decisions].sort((a, b) => b.created_at.localeCompare(a.created_at)) };
  },
  decide: async (taskId, payload, key) => {
    await delay();
    return idempotent(`POST /tasks/${taskId}/decisions`, key, payload, () => {
      const t = getTaskOr404(taskId);
      errBusy(t);
      if (t.status !== 'human_pending') throw new ApiError('INVALID_STATE', `当前状态 ${t.status} 不允许人工决定`, {});
      checkRevision(t, payload.expected_revision, payload.version_id);
      if (payload.decision === 'reject' && !payload.reason?.trim()) {
        throw new ApiError('VALIDATION_ERROR', '驳回必须填写具体理由', { fields: ['reason'] });
      }
      const v = t.versions[t.current_version_id];
      if (payload.decision === 'approve' && v.validation.status !== 'passed') {
        throw new ApiError('RULE_GATE_FAILED', '当前版本存在规则校验阻断错误，不能人工通过', {});
      }
      if (payload.decision === 'approve' && mockFaults.nextApproveFail) {
        mockFaults.nextApproveFail = false;
        throw new ApiError('INTERNAL_ERROR', '模拟：通过请求失败（版本已保存）', {});
      }
      const decision = {
        id: nid('dec'), task_id: t.id, task_version_id: t.current_version_id,
        decision: payload.decision, reason: payload.reason ?? '', created_at: now(),
      };
      t.decisions.push(decision);
      t.status = payload.decision === 'approve' ? 'approved' : 'rejected';
      t.revision += 1;
      t.updated_at = now();
      return { status: 201, result: { decision, task: toDetail(t) } as DecisionResult };
    });
  },
  reviewTask: async (taskId, payload, key) => {
    await delay();
    return idempotent(`POST /tasks/${taskId}/review`, key, payload, () => {
      const t = getTaskOr404(taskId);
      errBusy(t);
      if (t.status === 'approved' || t.status === 'ai_reviewing') {
        throw new ApiError('INVALID_STATE', `当前状态 ${t.status} 不允许重审`, {});
      }
      checkRevision(t, payload.expected_revision, payload.version_id);
      const active = Object.values(state.runs).some((r) => r.status === 'queued' || r.status === 'running');
      if (active) throw new ApiError('RUN_BUSY', '已有一个模型作业在运行', {});
      const run = runSingleTask(taskId, 'review_task', '');
      t.busy_run_id = run.id;
      t.status = 'pending_review';
      t.revision += 1;
      return { status: 202, result: run };
    });
  },
  reviseTask: async (taskId, payload, key) => {
    await delay();
    return idempotent(`POST /tasks/${taskId}/revise`, key, payload, () => {
      const t = getTaskOr404(taskId);
      errBusy(t);
      if (t.status === 'approved' || t.status === 'ai_reviewing') {
        throw new ApiError('INVALID_STATE', `当前状态 ${t.status} 不允许重写`, {});
      }
      checkRevision(t, payload.expected_revision, payload.version_id);
      const active = Object.values(state.runs).some((r) => r.status === 'queued' || r.status === 'running');
      if (active) throw new ApiError('RUN_BUSY', '已有一个模型作业在运行', {});
      const run = runSingleTask(taskId, 'revise_task', payload.feedback);
      t.busy_run_id = run.id;
      t.revision += 1;
      return { status: 202, result: run };
    });
  },

  createExport: async (payload, key) => {
    await delay();
    return idempotent('POST /exports', key, payload, () => {
      const tasks = payload.task_ids.map((id) => getTaskOr404(id));
      const bad = tasks.filter((t) => t.batch_id !== payload.batch_id || t.status !== 'approved');
      if (bad.length) {
        throw new ApiError('INVALID_STATE', '导出要求所有任务属于同一批次且已人工通过', { invalid_task_ids: bad.map((t) => t.id) });
      }
      const rec = {
        id: nid('exp'), batch_id: payload.batch_id,
        versions: tasks.map((t) => ({ task_id: t.id, version_id: t.current_version_id })),
        filename: `G2任务导出_MOCK_${Date.now()}.xlsx`,
        download_url: `/api/v1/exports/${'exp_mock'}/download`,
        created_at: now(),
      };
      rec.download_url = `/api/v1/exports/${rec.id}/download`;
      state.exports[rec.id] = rec;
      return { status: 201, result: rec };
    });
  },
  downloadExport: async () => {
    await delay();
    return new Blob(['mock xlsx content'], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  },

  // ---- mock 专属：故障注入 ----
  simulateRestart(): void {
    for (const r of Object.values(state.runs)) {
      if (r.status === 'queued' || r.status === 'running') {
        r.status = 'interrupted';
        r.finished_at = now();
      }
    }
    for (const t of Object.values(state.tasks)) {
      if (t.busy_run_id) {
        t.busy_run_id = null;
        t.status = 'review_failed';
        t.last_error = { code: 'RUN_INTERRUPTED', message: '服务重启中断了本次作业；请手动重新审核或重写', details: {}, request_id: 'restart' };
        t.revision += 1;
      }
    }
    for (const [k, rec] of state.idempotency) {
      // 处理中记录按可重试处理：删除后同键请求重新执行
      if (rec.status === 'in_progress') state.idempotency.delete(k);
    }
  },
  reseed(): void {
    seed();
  },
};
