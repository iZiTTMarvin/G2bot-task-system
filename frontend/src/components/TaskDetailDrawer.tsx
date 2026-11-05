import { Alert, Button, Drawer, Input, InputNumber, Modal, Spin, Tag, message } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ApiClient } from '../api/client';
import { newIdempotencyKey } from '../api/client';
import type { ApiError } from '../api/errors';
import type { Material, TaskContent, TaskDetail, TaskVersion } from '../api/types';
import { STATUS_LABEL } from '../api/types';
import StatusChip from './StatusChip';

interface Props {
  api: ApiClient;
  taskId: string | null;
  onClose: () => void;
  onChanged: () => void;
}

export default function TaskDetailDrawer({ api, taskId, onClose, onChanged }: Props) {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [versions, setVersions] = useState<TaskVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState('');
  const [steps, setSteps] = useState<string[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');

  const apply = useCallback((value: TaskDetail) => {
    setDetail(value);
    setName(value.current_version.content.name);
    setSteps([...value.current_version.content.steps]);
    setMaterials(value.current_version.content.materials.map((item) => ({ ...item })));
    setEditing(false);
  }, []);

  const load = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    try {
      const [nextDetail, versionList] = await Promise.all([
        api.getTask(taskId),
        api.listVersions(taskId),
      ]);
      apply(nextDetail);
      setVersions(versionList.items);
    } catch (cause) {
      message.error((cause as ApiError).message);
    } finally {
      setLoading(false);
    }
  }, [api, apply, taskId]);

  useEffect(() => {
    if (taskId) void load();
  }, [load, taskId]);

  const diff = useMemo(() => {
    if (versions.length < 2) return null;
    const current = versions[0];
    const parent = versions[1];
    if (current.author_type === 'human') return null;
    const currentSet = new Set(current.content.steps);
    const parentSet = new Set(parent.content.steps);
    const added = current.content.steps.filter((step) => !parentSet.has(step));
    const removed = parent.content.steps.filter((step) => !currentSet.has(step));
    if (!added.length && !removed.length) return null;
    return { added, removed };
  }, [versions]);

  const save = async () => {
    if (!detail || !taskId) return;
    if (!name.trim() || steps.some((step) => !step.trim()) || !materials.length) {
      message.warning('任务名、步骤、物料都不能为空');
      return;
    }
    setSaving(true);
    try {
      const content: TaskContent = {
        name: name.trim(),
        steps: steps.map((step) => step.trim()),
        materials: materials.map((item) => ({ ...item, name: item.name.trim() })),
      };
      const saved = await api.saveVersion(
        taskId,
        { expected_revision: detail.summary.revision, content },
        newIdempotencyKey()
      );
      apply(saved);
      onChanged();
      void load();
      message.success('已保存');
    } catch (cause) {
      message.error((cause as ApiError).message);
    } finally {
      setSaving(false);
    }
  };

  const decide = async (decision: 'approve' | 'reject', reason = '') => {
    if (!detail || !taskId) return;
    try {
      const result = await api.decide(
        taskId,
        {
          expected_revision: detail.summary.revision,
          version_id: detail.current_version.id,
          decision,
          reason,
        },
        newIdempotencyKey()
      );
      apply(result.task);
      setRejectOpen(false);
      setRejectReason('');
      onChanged();
      message.success(decision === 'approve' ? '已确认' : '已驳回');
    } catch (cause) {
      message.error((cause as ApiError).message);
    }
  };

  const review = async () => {
    if (!detail || !taskId) return;
    try {
      await api.reviewTask(
        taskId,
        { expected_revision: detail.summary.revision, version_id: detail.current_version.id },
        newIdempotencyKey()
      );
      onChanged();
      message.success('已送去重新审核');
      void load();
    } catch (cause) {
      message.error((cause as ApiError).message);
    }
  };

  const busy = Boolean(detail?.summary.busy_run_id);
  const content = detail?.current_version.content;
  const reviewData = detail?.latest_review;
  const reviewIssues = reviewData?.issues.filter(
    (issue) => !issue.rule_id?.startsWith('SYSTEM_BATCH_')
  ) ?? [];

  return (
    <Drawer
      open={Boolean(taskId)}
      onClose={onClose}
      width="min(760px, 100vw)"
      title={content?.name ?? '任务'}
      extra={
        detail && (
          <div className="drawer-extra">
            <span className="version-tag">v{detail.current_version.version_no}</span>
            <StatusChip task={detail.summary} />
          </div>
        )
      }
      footer={
        detail && (
          <div className="drawer-actions">
            {editing ? (
              <>
                <Button onClick={() => apply(detail)}>取消</Button>
                <Button type="primary" loading={saving} onClick={() => void save()}>
                  保存
                </Button>
              </>
            ) : (
              <>
                <Button onClick={() => setEditing(true)} disabled={busy}>
                  在线编辑
                </Button>
                <Button onClick={() => void review()} disabled={busy}>
                  重新审核
                </Button>
                <Button danger onClick={() => setRejectOpen(true)} disabled={busy}>
                  驳回
                </Button>
                <Button
                  type="primary"
                  onClick={() => void decide('approve')}
                  disabled={busy || detail.summary.status === 'approved'}
                >
                  确认
                </Button>
              </>
            )}
          </div>
        )
      }
    >
      <Spin spinning={loading && !detail}>
        {detail && content ? (
          <>
            {detail.last_error && <Alert type="error" showIcon message={detail.last_error.message} />}
            {reviewData && (
              <section className="detail-section review-box">
                <div className="detail-title">
                  AI 审核 · {reviewData.verdict === 'pass' ? '通过' : '有问题'}
                  <span className="detail-sub">
                    {new Date(reviewData.created_at).toLocaleString('zh-CN')}
                  </span>
                </div>
                <div className="review-summary">{reviewData.summary}</div>
                {reviewIssues.length > 0 && (
                  <ul className="issue-list">
                    {reviewIssues.map((issue, index) => (
                      <li key={index} className={`issue issue-${issue.severity}`}>
                        <div className="issue-head">
                          {issue.step_no ? `第 ${issue.step_no} 步` : '整体'}
                          <Tag color={issue.severity === 'error' ? 'red' : 'orange'}>
                            {issue.severity === 'error' ? '必改' : '建议'}
                          </Tag>
                        </div>
                        <div className="issue-body">{issue.message}</div>
                        {issue.suggestion && (
                          <div className="issue-tip">建议：{issue.suggestion}</div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            {diff && (
              <section className="detail-section">
                <div className="detail-title">
                  AI 改了什么 · <span className="diff-add">+{diff.added.length}</span>{' '}
                  <span className="diff-del">-{diff.removed.length}</span>
                </div>
                {diff.added.map((step, index) => (
                  <div key={`a${index}`} className="diff-line is-add">
                    + {step}
                  </div>
                ))}
                {diff.removed.map((step, index) => (
                  <div key={`d${index}`} className="diff-line is-del">
                    − {step}
                  </div>
                ))}
              </section>
            )}

            <section className="detail-section">
              <div className="detail-title">任务步骤 · {steps.length}</div>
              {editing ? (
                <>
                  <Input
                    className="name-input"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    addonBefore="任务名"
                  />
                  {steps.map((step, index) => (
                    <div className="edit-row" key={index}>
                      <span className="step-no">{index + 1}</span>
                      <Input.TextArea
                        value={step}
                        autoSize={{ minRows: 1, maxRows: 3 }}
                        onChange={(event) =>
                          setSteps((current) =>
                            current.map((item, i) => (i === index ? event.target.value : item))
                          )
                        }
                      />
                      <Button
                        size="small"
                        onClick={() =>
                          setSteps((current) => current.filter((_, i) => i !== index))
                        }
                      >
                        删
                      </Button>
                    </div>
                  ))}
                  <Button size="small" onClick={() => setSteps((current) => [...current, ''])}>
                    加一步
                  </Button>
                </>
              ) : (
                content.steps.map((step, index) => (
                  <div className="step-view" key={index}>
                    <span className="step-no">{index + 1}</span>
                    <span>{step}</span>
                  </div>
                ))
              )}
            </section>

            <section className="detail-section">
              <div className="detail-title">单套所需物料</div>
              {editing ? (
                <>
                  {materials.map((material, index) => (
                    <div className="edit-row" key={index}>
                      <Input
                        value={material.name}
                        onChange={(event) =>
                          setMaterials((current) =>
                            current.map((item, i) =>
                              i === index ? { ...item, name: event.target.value } : item
                            )
                          )
                        }
                      />
                      <InputNumber
                        min={1}
                        value={material.quantity}
                        onChange={(value) =>
                          setMaterials((current) =>
                            current.map((item, i) =>
                              i === index ? { ...item, quantity: value ?? 1 } : item
                            )
                          )
                        }
                      />
                      <Button
                        size="small"
                        onClick={() =>
                          setMaterials((current) => current.filter((_, i) => i !== index))
                        }
                      >
                        删
                      </Button>
                    </div>
                  ))}
                  <Button
                    size="small"
                    onClick={() => setMaterials((current) => [...current, { name: '', quantity: 1 }])}
                  >
                    加物料
                  </Button>
                </>
              ) : (
                <div className="material-tags">
                  {content.materials.map((material) => (
                    <Tag key={material.name}>
                      {material.name} × {material.quantity}
                    </Tag>
                  ))}
                </div>
              )}
            </section>

            {detail.batch_issues.length > 0 && (
              <section className="detail-section">
                <div className="detail-title">同批对比</div>
                {detail.batch_issues.map((issue, index) => (
                  <Alert
                    key={index}
                    className="rule-issue"
                    type={issue.severity === 'error' ? 'error' : 'warning'}
                    message={issue.message}
                  />
                ))}
              </section>
            )}

            {detail.current_version.validation.issues.length > 0 && (
              <section className="detail-section">
                <div className="detail-title">规则校验</div>
                {detail.current_version.validation.issues.map((issue, index) => (
                  <Alert
                    key={index}
                    className="rule-issue"
                    type={issue.severity === 'error' ? 'error' : 'warning'}
                    message={`${issue.step_no ? `第 ${issue.step_no} 步 · ` : ''}${issue.message}`}
                  />
                ))}
              </section>
            )}

            <div className="detail-status-line">
              当前状态：{STATUS_LABEL[detail.summary.status]}
              {detail.summary.status === 'approved' ? '（可编辑，改完会回到待确认）' : ''}
            </div>
          </>
        ) : (
          !loading && <div className="empty-detail">任务不存在</div>
        )}
      </Spin>

      <Modal
        open={rejectOpen}
        title="驳回任务"
        okText="驳回"
        okButtonProps={{ danger: true, disabled: !rejectReason.trim() }}
        onOk={() => void decide('reject', rejectReason.trim())}
        onCancel={() => setRejectOpen(false)}
      >
        <Input.TextArea
          value={rejectReason}
          onChange={(event) => setRejectReason(event.target.value)}
          placeholder="驳回理由（会记进决定历史）"
          autoSize={{ minRows: 3 }}
        />
      </Modal>
    </Drawer>
  );
}
