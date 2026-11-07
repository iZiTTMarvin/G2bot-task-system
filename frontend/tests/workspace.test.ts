import assert from 'node:assert/strict';
import test from 'node:test';
import type { ChatMessage, Conversation, ValidationIssue } from '../src/api/types.ts';
import { collectResolutions, effectiveAttachments, errorHint, isEmptyDefaultConversation, needsRunResult, taskCategory, visibleMessages } from '../src/lib/presentation.ts';

const message = (id: string, role: 'user' | 'agent', run = 'run-1'): ChatMessage => ({ id, role, run_id: run,
  conversation_id: 'conv-1', batch_id: 'batch-1', content: '内容', attachments: [], task_ids: [],
  run: { id: run, batch_id: 'batch-1', task_id: null, task_ids: [], kind: 'generate_batch', stage: 'generating',
    status: 'failed', progress: { total: 1, completed: 0, failed: 1 }, error: null,
    created_at: '2026-11-06T00:00:00Z', started_at: null, finished_at: null },
  created_at: '2026-11-06T00:00:00Z' });

test('失败只由助手结果承载，不在用户消息下重复合成', () => {
  const user = message('u', 'user');
  const agent = message('a', 'agent');
  assert.equal(needsRunResult(user, [user]), true);
  assert.equal(needsRunResult(user, [user, agent]), false);
  assert.deepEqual(visibleMessages([user, message('a1', 'agent'), agent]).map((m) => m.id), ['u', 'a']);
});

test('不同作业的失败记录均保留，不误合并历史', () => {
  const records = [message('u1', 'user', 'r1'), message('a1', 'agent', 'r1'), message('u2', 'user', 'r2'), message('a2', 'agent', 'r2')];
  assert.equal(visibleMessages(records).length, 4);
});

test('资料继承、替换、追加、移除保持后端语义', () => {
  assert.deepEqual(effectiveAttachments(['a'], [], 'inherit'), ['a']);
  assert.deepEqual(effectiveAttachments(['a'], ['b'], 'inherit'), ['b']);
  assert.deepEqual(effectiveAttachments(['a'], [], 'replace'), []);
  assert.deepEqual(effectiveAttachments(['a'], ['a', 'b'], 'append'), ['a', 'b']);
  assert.deepEqual(effectiveAttachments(['a'], ['b'], 'clear'), []);
});

test('共用核验说明只赋给人工勾选的当前项，单项说明优先', () => {
  const required = ['PURPOSE', 'SITE', 'WORKLOAD'].map((code) => ({ code, severity: 'review_required', message: '', step_no: null, rule_id: null }) satisfies ValidationIssue);
  assert.deepEqual(collectResolutions(required, { PURPOSE: true, SITE: true }, '  现场已核对  ', { SITE: '单项实测记录' }),
    { PURPOSE: '现场已核对', SITE: '单项实测记录' });
  assert.deepEqual(collectResolutions(required, { PURPOSE: true }, ' ', {}), {});
  assert.deepEqual(collectResolutions(required, { unknown: true }, '现场已核对', {}), {});
});

test('库存核验能区分具体物料，错误有可操作提示', () => {
  assert.equal(taskCategory('INVENTORY_毛巾'), '库存：毛巾');
  assert.notEqual(taskCategory('INVENTORY_毛巾'), taskCategory('INVENTORY_盒子'));
  assert.match(errorHint({ code: 'MODEL_REQUEST_FAILED', message: 'HTTP 404' }), /服务地址与 API 格式/);
  assert.match(errorHint({ code: 'MODEL_TIMEOUT', message: 'timeout' }), /已保留/);
});

test('只折叠旧版自动创建且完全为空的默认会话', () => {
  const empty: Conversation = { id: 'c', agent_role: 'generator', title: '新的生成会话', attachment_ids: [],
    message_count: 0, task_count: 0, created_at: '', updated_at: '' };
  assert.equal(isEmptyDefaultConversation(empty), true);
  assert.equal(isEmptyDefaultConversation({ ...empty, title: '我的任务集' }), false);
  assert.equal(isEmptyDefaultConversation({ ...empty, message_count: 1 }), false);
  assert.equal(isEmptyDefaultConversation({ ...empty, task_count: 1 }), false);
  assert.equal(isEmptyDefaultConversation({ ...empty, attachment_ids: ['a'] }), false);
});
