import {
  Alert,
  Button,
  Drawer,
  Empty,
  Input,
  InputNumber,
  Modal,
  Spin,
  Tag,
  message,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ApiClient } from '../api/client';
import { newIdempotencyKey } from '../api/client';
import type { ApiError } from '../api/errors';
import type { Material, TaskContent, TaskDetail } from '../api/types';
import { STATUS_LABEL } from '../api/types';

interface Props {
  api: ApiClient;
  taskId: string | null;
  onClose: () => void;
  onUpdated: () => void;
}

export default function TaskDrawer({ api, taskId, onClose, onUpdated }: Props) {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [steps, setSteps] = useState<string[]>([]);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [loading, setLoading] = useState(Boolean(taskId));
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [reviseOpen, setReviseOpen] = useState(false);
  const [feedback, setFeedback] = useState('');

  const applyDetail = useCallback((value: TaskDetail) => {
    setDetail(value);
    setSteps([...value.current_version.content.steps]);
    setMaterials(value.current_version.content.materials.map((material) => ({ ...material })));
  }, []);

  const load = useCallback(async () => {
    if (!taskId) return;
    try {
      applyDetail(await api.getTask(taskId));
    } catch (cause) {
      message.error((cause as ApiError).message);
    } finally {
      setLoading(false);
    }
  }, [api, applyDetail, taskId]);

  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    api.getTask(taskId)
      .then((value) => {
        if (!cancelled) applyDetail(value);
      })
      .catch((cause) => {
        if (!cancelled) message.error((cause as ApiError).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [api, applyDetail, taskId]);

  const busy = Boolean(detail?.summary.busy_run_id);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => void load(), 1500);
    return () => clearInterval(timer);
  }, [busy, load]);

  const dirty = useMemo(() => {
    if (!detail) return false;
    const original = detail.current_version.content;
    return (
      JSON.stringify(steps) !== JSON.stringify(original.steps) ||
      JSON.stringify(materials) !== JSON.stringify(original.materials)
    );
  }, [detail, materials, steps]);

  const save = async () => {
    if (!detail) return null;
    if (!steps.length || steps.some((step) => !step.trim())) {
      message.warning('步骤不能为空');
      return null;
    }
    if (!materials.length || materials.some((material) => !material.name.trim())) {
      message.warning('物料不能为空');
      return null;
    }
    setSaving(true);
    try {
      const content: TaskContent = {
        name: detail.current_version.content.name,
        steps: steps.map((step) => step.trim()),
        materials: materials.map((material) => ({ ...material, name: material.name.trim() })),
      };
      const saved = await api.saveVersion(
        detail.summary.id,
        {
          expected_revision: detail.summary.revision,
          content,
        },
        newIdempotencyKey()
      );
      applyDetail(saved);
      setEditing(false);
      onUpdated();
      message.success('已保存');
      return saved;
    } catch (cause) {
      message.error((cause as ApiError).message);
      return null;
    } finally {
      setSaving(false);
    }
  };

  const decide = async (decision: 'approve' | 'reject') => {
    if (!detail) return;
    try {
      const result = await api.decide(
        detail.summary.id,
        {
          expected_revision: detail.summary.revision,
          version_id: detail.current_version.id,
          decision,
          reason: decision === 'reject' ? rejectReason.trim() : '',
        },
        newIdempotencyKey()
      );
      applyDetail(result.task);
      setRejectOpen(false);
      setRejectReason('');
      onUpdated();
      message.success(decision === 'approve' ? '已通过' : '已驳回');
    } catch (cause) {
      message.error((cause as ApiError).message);
    }
  };

  const revise = async () => {
    if (!detail || !feedback.trim()) return;
    try {
      await api.reviseTask(
        detail.summary.id,
        {
          expected_revision: detail.summary.revision,
          version_id: detail.current_version.id,
          feedback: feedback.trim(),
        },
        newIdempotencyKey()
      );
      setReviseOpen(false);
      setFeedback('');
      await load();
      onUpdated();
    } catch (cause) {
      message.error((cause as ApiError).message);
    }
  };

  const review = async () => {
    if (!detail) return;
    try {
      await api.reviewTask(
        detail.summary.id,
        {
          expected_revision: detail.summary.revision,
          version_id: detail.current_version.id,
        },
        newIdempotencyKey()
      );
      await load();
      onUpdated();
    } catch (cause) {
      message.error((cause as ApiError).message);
    }
  };

  const close = () => {
    if (editing && dirty) {
      Modal.confirm({
        title: '放弃未保存的修改？',
        okText: '放弃',
        cancelText: '继续编辑',
        onOk: onClose,
      });
      return;
    }
    onClose();
  };

  const status = detail?.summary.status;
  const canEdit = Boolean(detail && !busy && status !== 'approved' && status !== 'ai_reviewing');
  const content = detail?.current_version.content;

  return (
    <Drawer
      open={Boolean(taskId)}
      onClose={close}
      width={720}
      title={content?.name ?? '任务'}
      extra={detail && <Tag>{STATUS_LABEL[detail.summary.status]}</Tag>}
      footer={
        detail && (
          <div className="drawer-actions">
            {editing ? (
              <>
                <Button
                  onClick={() => {
                    setSteps([...detail.current_version.content.steps]);
                    setMaterials(detail.current_version.content.materials.map((item) => ({ ...item })));
                    setEditing(false);
                  }}
                >
                  取消
                </Button>
                <Button type="primary" onClick={save} loading={saving} disabled={!dirty}>
                  保存
                </Button>
              </>
            ) : (
              <>
                {canEdit && <Button onClick={() => setEditing(true)}>编辑</Button>}
                {canEdit && <Button onClick={() => setReviseOpen(true)}>按反馈重写</Button>}
                {canEdit && status !== 'pending_review' && <Button onClick={review}>重新审核</Button>}
                {detail.can_decide && (
                  <>
                    <Button danger onClick={() => setRejectOpen(true)}>驳回</Button>
                    <Button type="primary" onClick={() => decide('approve')}>通过</Button>
                  </>
                )}
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
            {busy && <Alert type="info" showIcon message="AI 正在处理" />}
            <section className="task-detail-section">
              <div className="task-detail-title">任务步骤 · {content.steps.length}</div>
              {editing
                ? steps.map((step, index) => (
                    <div className="step-edit-row" key={index}>
                      <Input.TextArea
                        value={step}
                        autoSize={{ minRows: 1, maxRows: 3 }}
                        onChange={(event) =>
                          setSteps((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))
                        }
                      />
                      <Button onClick={() => setSteps((current) => current.filter((_, itemIndex) => itemIndex !== index))}>
                        删除
                      </Button>
                    </div>
                  ))
                : content.steps.map((step, index) => (
                    <div className="step-view" key={index}>
                      <span className="step-number">{index + 1}.</span>
                      <span>{step}</span>
                    </div>
                  ))}
              {editing && <Button onClick={() => setSteps((current) => [...current, ''])}>添加步骤</Button>}
            </section>

            <section className="task-detail-section">
              <div className="task-detail-title">单套所需物料</div>
              {editing ? (
                <>
                  {materials.map((material, index) => (
                    <div className="material-edit-row" key={index}>
                      <Input
                        value={material.name}
                        onChange={(event) =>
                          setMaterials((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item))
                        }
                      />
                      <InputNumber
                        min={1}
                        value={material.quantity}
                        onChange={(value) =>
                          setMaterials((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, quantity: value ?? 1 } : item))
                        }
                      />
                      <Button onClick={() => setMaterials((current) => current.filter((_, itemIndex) => itemIndex !== index))}>
                        删除
                      </Button>
                    </div>
                  ))}
                  <Button onClick={() => setMaterials((current) => [...current, { name: '', quantity: 1 }])}>
                    添加物料
                  </Button>
                </>
              ) : (
                <div className="material-tags">
                  {content.materials.map((material) => (
                    <Tag key={material.name}>{material.name} × {material.quantity}</Tag>
                  ))}
                </div>
              )}
            </section>

            {!editing && detail.current_version.validation.issues.length > 0 && (
              <section className="task-detail-section">
                <div className="task-detail-title">校验问题</div>
                {detail.current_version.validation.issues.map((issue, index) => (
                  <Alert
                    key={index}
                    type={issue.severity === 'error' ? 'error' : 'warning'}
                    message={`${issue.step_no ? `第 ${issue.step_no} 步 · ` : ''}${issue.message}`}
                  />
                ))}
              </section>
            )}

            {!editing && detail.latest_review && (
              <section className="task-detail-section">
                <div className="task-detail-title">AI 审核</div>
                <Tag color={detail.latest_review.verdict === 'pass' ? 'green' : 'orange'}>
                  {detail.latest_review.verdict === 'pass' ? '通过' : '需要修改'}
                </Tag>
                {!detail.ai_review_matches_current_version && <Tag>旧版本</Tag>}
                {detail.latest_review.summary && <div className="review-summary">{detail.latest_review.summary}</div>}
                {detail.latest_review.issues.map((issue, index) => (
                  <Alert
                    key={index}
                    type={issue.severity === 'error' ? 'error' : 'warning'}
                    message={`${issue.step_no ? `第 ${issue.step_no} 步 · ` : ''}${issue.message}`}
                    description={issue.suggestion || undefined}
                  />
                ))}
              </section>
            )}
          </>
        ) : (
          !loading && <Empty description="任务不存在" />
        )}
      </Spin>

      <Modal
        open={rejectOpen}
        title="驳回任务"
        okText="驳回"
        okButtonProps={{ danger: true, disabled: !rejectReason.trim() }}
        onOk={() => decide('reject')}
        onCancel={() => setRejectOpen(false)}
      >
        <Input.TextArea
          value={rejectReason}
          onChange={(event) => setRejectReason(event.target.value)}
          placeholder="驳回理由"
          autoSize={{ minRows: 3 }}
        />
      </Modal>

      <Modal
        open={reviseOpen}
        title="按反馈重写"
        okText="重写"
        okButtonProps={{ disabled: !feedback.trim() }}
        onOk={revise}
        onCancel={() => setReviseOpen(false)}
      >
        <Input.TextArea
          value={feedback}
          onChange={(event) => setFeedback(event.target.value)}
          placeholder="说明需要怎样修改"
          autoSize={{ minRows: 3 }}
        />
      </Modal>
    </Drawer>
  );
}
