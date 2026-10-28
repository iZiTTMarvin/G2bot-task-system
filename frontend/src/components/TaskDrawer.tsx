// 人工审核详情抽屉：主区编辑 + 侧区校验/AI 意见/版本/决定 + 状态相关操作。
import {
  Alert, Button, Descriptions, Drawer, Empty, Input, InputNumber, List, Modal,
  Popconfirm, Space, Spin, Tabs, Tag, Tooltip, Typography, message,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ApiClient } from '../api/client';
import { newIdempotencyKey } from '../api/client';
import { ApiError } from '../api/errors';
import type { HumanDecision, Review, TaskContent, TaskDetail, TaskVersion } from '../api/types';
import { STATUS_LABEL } from '../api/types';

const AUTHOR_LABEL: Record<TaskVersion['author_type'], string> = {
  ai: 'AI 原稿',
  human: '人工修改',
  ai_revision: 'AI 重写',
};

interface Props {
  api: ApiClient;
  taskId: string | null;
  onClose: (changed: boolean) => void;
  onUpdated: () => void; // 列表与计数刷新
}

export default function TaskDrawer({ api, taskId, onClose, onUpdated }: Props) {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [versions, setVersions] = useState<TaskVersion[]>([]);
  const [decisions, setDecisions] = useState<HumanDecision[]>([]);
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState('');
  const [steps, setSteps] = useState<string[]>([]);
  const [materials, setMaterials] = useState<{ name: string; quantity: number }[]>([]);
  const [changeNote, setChangeNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [viewVersionId, setViewVersionId] = useState<string | null>(null);
  const [compare, setCompare] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [reviseOpen, setReviseOpen] = useState(false);
  const [reviseFeedback, setReviseFeedback] = useState('');

  const load = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    try {
      const [d, vs, ds] = await Promise.all([
        api.getTask(taskId),
        api.listVersions(taskId),
        api.listDecisions(taskId),
      ]);
      setDetail(d);
      setVersions(vs.items);
      setDecisions(ds.items);
      setName(d.current_version.content.name);
      setSteps([...d.current_version.content.steps]);
      setMaterials(d.current_version.content.materials.map((m) => ({ ...m })));
      setChangeNote('');
    } catch (e) {
      message.error((e as ApiError).message ?? '读取任务失败');
    } finally {
      setLoading(false);
    }
  }, [api, taskId]);

  useEffect(() => {
    setViewVersionId(null);
    setCompare(false);
    load();
  }, [load]);

  const dirty = useMemo(() => {
    if (!detail) return false;
    const original = detail.current_version.content;
    return (
      name !== original.name ||
      JSON.stringify(steps) !== JSON.stringify(original.steps) ||
      JSON.stringify(materials) !== JSON.stringify(original.materials)
    );
  }, [detail, name, steps, materials]);

  const busy = !!detail?.summary.busy_run_id;
  const status = detail?.summary.status;
  const canSave = !!detail && !busy && status !== 'approved' && status !== 'ai_reviewing';
  const canDecide = !!detail?.can_decide && !dirty;

  const closeGuard = () => {
    if (!dirty) {
      onClose(false);
      return;
    }
    Modal.confirm({
      title: '有未保存的修改',
      content: '关闭前是否保存？未保存的修改将丢失。',
      okText: '保存并关闭',
      cancelText: '放弃修改',
      okButtonProps: { danger: false },
      onOk: async () => {
        await doSave();
        onClose(true);
      },
      onCancel: () => onClose(true),
    });
  };

  const buildContent = (): TaskContent => ({ name: name.trim(), steps: steps.map((s) => s.trim()), materials });

  const doSave = async (): Promise<TaskDetail | null> => {
    if (!detail) return null;
    setSaving(true);
    try {
      const saved = await api.saveVersion(
        detail.summary.id,
        {
          expected_revision: detail.summary.revision,
          content: buildContent(),
          change_note: changeNote,
        },
        newIdempotencyKey()
      );
      setDetail(saved);
      setName(saved.current_version.content.name);
      setSteps([...saved.current_version.content.steps]);
      setMaterials(saved.current_version.content.materials.map((m) => ({ ...m })));
      setChangeNote('');
      message.success(`已保存为 v${saved.summary.version_no}`);
      void load(); // 刷新版本与决定历史
      onUpdated();
      return saved;
    } catch (e) {
      const err = e as ApiError;
      if (err.code === 'NO_CHANGES') message.info('没有需要保存的修改');
      else message.error(`${err.message}（${err.code}）`);
      return null;
    } finally {
      setSaving(false);
    }
  };

  const doSaveAndApprove = async () => {
    const saved = await doSave();
    if (!saved) return;
    try {
      const result = await api.decide(
        saved.summary.id,
        {
          expected_revision: saved.summary.revision,
          version_id: saved.current_version.id,
          decision: 'approve',
        },
        newIdempotencyKey()
      );
      setDetail(result.task);
      message.success('已保存并通过');
      onUpdated();
    } catch {
      // 蓝图：第二步失败显示“版本已保存，通过失败”，保留新稿
      message.warning('版本已保存，通过失败；新版本已保留，请处理后重试');
      await load();
      onUpdated();
    }
  };

  const doDecide = async (decision: 'approve' | 'reject', reason = '') => {
    if (!detail) return;
    try {
      const result = await api.decide(
        detail.summary.id,
        {
          expected_revision: detail.summary.revision,
          version_id: detail.current_version.id,
          decision,
          reason,
        },
        newIdempotencyKey()
      );
      setDetail(result.task);
      message.success(decision === 'approve' ? '已通过' : '已驳回');
      setRejectOpen(false);
      setRejectReason('');
      void load();
      onUpdated();
    } catch (e) {
      message.error(`${(e as ApiError).message}（${(e as ApiError).code}）`);
    }
  };

  const doRerun = async (kind: 'review' | 'revise', feedback = '') => {
    if (!detail) return;
    try {
      const run =
        kind === 'review'
          ? await api.reviewTask(
              detail.summary.id,
              { expected_revision: detail.summary.revision, version_id: detail.current_version.id },
              newIdempotencyKey()
            )
          : await api.reviseTask(
              detail.summary.id,
              {
                expected_revision: detail.summary.revision,
                version_id: detail.current_version.id,
                feedback,
              },
              newIdempotencyKey()
            );
      message.info(`已登记后台作业（${run.kind}），完成后状态自动更新`);
      setReviseOpen(false);
      setReviseFeedback('');
      await load();
      onUpdated();
    } catch (e) {
      message.error(`${(e as ApiError).message}（${(e as ApiError).code}）`);
    }
  };

  const stepRow = (i: number, value: string, onChange: (v: string) => void, disabled: boolean) => (
    <Space key={i} style={{ display: 'flex', marginBottom: 4 }} align="start">
      <span style={{ width: 28, textAlign: 'right', color: '#888' }}>{i + 1}.</span>
      <Input.TextArea
        value={value}
        disabled={disabled}
        autoSize={{ minRows: 1, maxRows: 3 }}
        onChange={(e) => onChange(e.target.value)}
        style={{ flex: 1 }}
      />
      {!disabled && (
        <>
          <Button size="small" disabled={i === 0} onClick={() => {
            const next = [...steps]; [next[i - 1], next[i]] = [next[i], next[i - 1]]; setSteps(next);
          }}>↑</Button>
          <Button size="small" disabled={i === steps.length - 1} onClick={() => {
            const next = [...steps]; [next[i + 1], next[i]] = [next[i], next[i + 1]]; setSteps(next);
          }}>↓</Button>
          <Button size="small" danger onClick={() => setSteps(steps.filter((_, idx) => idx !== i))}>删</Button>
        </>
      )}
    </Space>
  );

  const shownVersion = viewVersionId ? versions.find((v) => v.id === viewVersionId) : null;
  const originalVersion = useMemo(
    () => [...versions].sort((a, b) => a.version_no - b.version_no)[0] ?? null,
    [versions]
  );

  const contentPanel = (content: TaskContent, readonly: boolean) => (
    <div>
      <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="任务名">
          {readonly ? content.name : (
            <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
          )}
        </Descriptions.Item>
      </Descriptions>
      <Typography.Text type="secondary">步骤（{content.steps.length} 步，导出时自动编号）</Typography.Text>
      <div style={{ marginTop: 6, marginBottom: 12 }}>
        {readonly
          ? content.steps.map((s, i) => (
              <div key={i} style={{ marginBottom: 2 }}>
                <span style={{ color: '#888', marginRight: 8 }}>{i + 1}.</span>
                {s}
              </div>
            ))
          : steps.map((s, i) => stepRow(i, s, (v) => setSteps(steps.map((x, idx) => (idx === i ? v : x))), false))}
        {!readonly && (
          <Button size="small" style={{ marginTop: 4 }} onClick={() => setSteps([...steps, ''])}>
            + 添加步骤
          </Button>
        )}
      </div>
      <Typography.Text type="secondary">物料（名称 + 单套数量；最终导出为汇总文本）</Typography.Text>
      <div style={{ marginTop: 6 }}>
        {readonly
          ? content.materials.map((m, i) => (
              <Tag key={i}>{m.name} × {m.quantity}</Tag>
            ))
          : materials.map((m, i) => (
              <Space key={i} style={{ display: 'flex', marginBottom: 4 }}>
                <Input
                  value={m.name}
                  style={{ width: 220 }}
                  maxLength={100}
                  onChange={(e) => setMaterials(materials.map((x, idx) => (idx === i ? { ...x, name: e.target.value } : x)))}
                />
                <InputNumber
                  min={1}
                  max={1000}
                  value={m.quantity}
                  onChange={(v) => setMaterials(materials.map((x, idx) => (idx === i ? { ...x, quantity: v ?? 1 } : x)))}
                />
                <Button size="small" danger onClick={() => setMaterials(materials.filter((_, idx) => idx !== i))}>删</Button>
              </Space>
            ))}
        {!readonly && (
          <Button size="small" onClick={() => setMaterials([...materials, { name: '', quantity: 1 }])}>
            + 添加物料
          </Button>
        )}
      </div>
    </div>
  );

  const validationPanel = (report: TaskVersion['validation']) => (
    <div>
      <Tag color={report.status === 'passed' ? 'green' : 'red'}>
        {report.status === 'passed' ? '规则校验通过' : '规则校验未通过'}
      </Tag>
      {report.issues.length === 0 && <Typography.Text type="secondary"> 无问题</Typography.Text>}
      <List
        size="small"
        dataSource={report.issues}
        renderItem={(issue) => (
          <List.Item style={{ padding: '4px 0' }}>
            <div>
              <Tag color={issue.severity === 'error' ? 'red' : 'orange'}>{issue.severity === 'error' ? '阻断' : '提醒'}</Tag>
              {issue.rule_id && <Tag>{issue.rule_id}</Tag>}
              {issue.step_no != null && <Tag>第 {issue.step_no} 步</Tag>}
              <div>{issue.message}</div>
            </div>
          </List.Item>
        )}
      />
    </div>
  );

  const reviewPanel = (review: Review | null, matches: boolean) =>
    !review ? (
      <Empty description="暂无 AI 审核记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
    ) : (
      <div>
        <Space wrap>
          <Tag color={review.verdict === 'pass' ? 'green' : 'volcano'}>
            {review.verdict === 'pass' ? 'AI 通过' : 'AI 建议修改'}
          </Tag>
          <Tag>针对版本 {versions.find((v) => v.id === review.task_version_id)?.version_no ?? '?'}</Tag>
          {!matches && <Tag color="orange">非当前版本</Tag>}
        </Space>
        <Typography.Paragraph style={{ marginTop: 8, marginBottom: 4 }} type="secondary">
          {review.summary}
        </Typography.Paragraph>
        <List
          size="small"
          dataSource={review.issues}
          renderItem={(issue) => (
            <List.Item style={{ padding: '4px 0' }}>
              <div>
                <Tag color={issue.severity === 'error' ? 'red' : 'orange'}>{issue.severity}</Tag>
                {issue.rule_id && <Tag>{issue.rule_id}</Tag>}
                {issue.step_no != null && <Tag>第 {issue.step_no} 步</Tag>}
                {issue.quote && <Typography.Text code>{issue.quote}</Typography.Text>}
                <div>{issue.message}</div>
                {issue.suggestion && <div style={{ color: '#888' }}>建议：{issue.suggestion}</div>}
              </div>
            </List.Item>
          )}
        />
      </div>
    );

  if (!taskId || (!detail && !loading)) {
    return (
      <Drawer open={!!taskId} onClose={() => onClose(false)} width="70%">
        <Empty description="任务不存在" />
      </Drawer>
    );
  }

  return (
    <Drawer
      open
      onClose={closeGuard}
      width="76%"
      title={
        detail && (
          <Space wrap>
            <span>{detail.current_version.content.name}</span>
            <Tag>{STATUS_LABEL[detail.summary.status]}</Tag>
            <Tag>v{detail.summary.version_no}</Tag>
            {detail.summary.human_edited && <Tag color="blue">人工修改过</Tag>}
            {busy && <Tag color="purple">作业处理中</Tag>}
          </Space>
        )
      }
      footer={
        detail && (
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <Tooltip title={canSave ? '' : '当前状态或作业占用不允许保存'}>
              <Button onClick={doSave} disabled={!canSave} loading={saving}>
                保存
              </Button>
            </Tooltip>
            {canDecide && (
              <>
                <Popconfirm title="确认通过当前版本？" onConfirm={() => doDecide('approve')} disabled={dirty}>
                  <Button type="primary" disabled={dirty}>
                    通过
                  </Button>
                </Popconfirm>
                <Button danger disabled={dirty} onClick={() => setRejectOpen(true)}>
                  驳回
                </Button>
              </>
            )}
            {canSave && (
              <Button type="primary" ghost onClick={doSaveAndApprove} disabled={!detail.can_decide} loading={saving}>
                保存并通过
              </Button>
            )}
            {(status === 'ai_rejected' || status === 'review_failed' || status === 'rejected' || status === 'human_pending') && !busy && (
              <Button onClick={() => doRerun('review')}>重新 AI 审核</Button>
            )}
            {status !== 'approved' && status !== 'ai_reviewing' && !busy && (
              <Button onClick={() => setReviseOpen(true)}>按反馈重写</Button>
            )}
          </div>
        )
      }
    >
      {loading && <Spin />}
      {detail && (
        <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: 24 }}>
          <div>
            {busy && (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message="后台作业处理中"
                description="该任务正被生成/审核作业占用，暂不能编辑或决定；作业结束后自动恢复。"
              />
            )}
            {dirty && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message="有未保存的修改" />}
            {detail.last_error && (
              <Alert
                type="error"
                showIcon
                style={{ marginBottom: 12 }}
                message={`最近错误：${detail.last_error.code}`}
                description={detail.last_error.message}
              />
            )}
            {compare && originalVersion ? (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <Typography.Title level={5}>AI 原稿 v{originalVersion.version_no}</Typography.Title>
                  <div style={{ maxHeight: 480, overflow: 'auto', borderRight: '1px solid #f0f0f0', paddingRight: 8 }}>
                    {contentPanel(originalVersion.content, true)}
                  </div>
                </div>
                <div>
                  <Typography.Title level={5}>当前稿 v{detail.summary.version_no}</Typography.Title>
                  <div style={{ maxHeight: 480, overflow: 'auto' }}>
                    {contentPanel(detail.current_version.content, true)}
                  </div>
                </div>
              </div>
            ) : shownVersion ? (
              <div>
                <Space style={{ marginBottom: 12 }}>
                  <Tag>只读历史版本 v{shownVersion.version_no}</Tag>
                  <Tag>{AUTHOR_LABEL[shownVersion.author_type]}</Tag>
                  {shownVersion.change_note && <Typography.Text type="secondary">{shownVersion.change_note}</Typography.Text>}
                  <Button size="small" onClick={() => setViewVersionId(null)}>
                    返回编辑
                  </Button>
                </Space>
                {contentPanel(shownVersion.content, true)}
              </div>
            ) : (
              <div>
                {contentPanel(buildContent(), false)}
                <div style={{ marginTop: 16 }}>
                  <Typography.Text type="secondary">修改说明（可选，用于复盘）</Typography.Text>
                  <Input.TextArea
                    value={changeNote}
                    onChange={(e) => setChangeNote(e.target.value)}
                    maxLength={2000}
                    autoSize={{ minRows: 1, maxRows: 3 }}
                    style={{ marginTop: 4 }}
                  />
                </div>
              </div>
            )}
          </div>
          <div>
            <Tabs
              defaultActiveKey="validation"
              items={[
                {
                  key: 'validation',
                  label: '规则校验',
                  children: detail.current_version.validation ? validationPanel(detail.current_version.validation) : <Empty />,
                },
                {
                  key: 'review',
                  label: 'AI 意见',
                  children: reviewPanel(detail.latest_review, detail.ai_review_matches_current_version),
                },
                {
                  key: 'versions',
                  label: `版本 (${versions.length})`,
                  children: (
                    <div>
                      <Space style={{ marginBottom: 8 }}>
                        <Button size="small" onClick={() => setCompare(!compare)} disabled={versions.length < 2}>
                          {compare ? '关闭对照' : '原稿 vs 当前稿'}
                        </Button>
                      </Space>
                      <List
                        size="small"
                        dataSource={[...versions].sort((a, b) => b.version_no - a.version_no)}
                        renderItem={(v) => (
                          <List.Item
                            actions={[
                              <Button key="view" size="small" type="link" onClick={() => { setCompare(false); setViewVersionId(v.id); }}>
                                查看
                              </Button>,
                            ]}
                          >
                            <Space>
                              <Tag>v{v.version_no}</Tag>
                              <span>{AUTHOR_LABEL[v.author_type]}</span>
                              <span style={{ color: '#888' }}>
                                {v.validation.status === 'passed' ? '校验通过' : '校验未过'}
                              </span>
                            </Space>
                          </List.Item>
                        )}
                      />
                    </div>
                  ),
                },
                {
                  key: 'decisions',
                  label: `人工决定 (${decisions.length})`,
                  children: decisions.length ? (
                    <List
                      size="small"
                      dataSource={decisions}
                      renderItem={(d) => (
                        <List.Item>
                          <div>
                            <Tag color={d.decision === 'approve' ? 'green' : 'volcano'}>
                              {d.decision === 'approve' ? '通过' : '驳回'}
                            </Tag>
                            <span style={{ color: '#888' }}>
                              v{versions.find((v) => v.id === d.task_version_id)?.version_no ?? '?'} ·{' '}
                              {new Date(d.created_at).toLocaleString()}
                            </span>
                            {d.reason && <div style={{ marginTop: 2 }}>理由：{d.reason}</div>}
                          </div>
                        </List.Item>
                      )}
                    />
                  ) : (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无人工决定" />
                  ),
                },
              ]}
            />
          </div>
        </div>
      )}

      <Modal
        open={rejectOpen}
        title="驳回任务（必须填写理由）"
        okText="驳回"
        okButtonProps={{ danger: true, disabled: !rejectReason.trim() }}
        cancelText="取消"
        onOk={() => doDecide('reject', rejectReason.trim())}
        onCancel={() => setRejectOpen(false)}
      >
        <Input.TextArea
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          placeholder="例如：第 8 步把已备好的用品收回，撤销了题目要求的待用终态。"
          maxLength={5000}
          autoSize={{ minRows: 3 }}
        />
      </Modal>

      <Modal
        open={reviseOpen}
        title="按反馈重写（生成新版本后自动审核）"
        okText="开始重写"
        cancelText="取消"
        okButtonProps={{ disabled: !reviseFeedback.trim() }}
        onOk={() => doRerun('revise', reviseFeedback.trim())}
        onCancel={() => setReviseOpen(false)}
      >
        <Input.TextArea
          value={reviseFeedback}
          onChange={(e) => setReviseFeedback(e.target.value)}
          placeholder="告诉生成 Agent 需要怎么改，例如：终态应为用品摆好待用，不要收回。"
          maxLength={5000}
          autoSize={{ minRows: 3 }}
        />
      </Modal>
    </Drawer>
  );
}
