// 任务生成页：批次表单 + 最近批次 + 作业进度轮询（2s，终态停止）。
import {
  Alert, Button, Card, Col, Form, Input, InputNumber, Radio, Row, Select, Space, Table, Tag, Typography, message,
} from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ApiClient } from '../api/client';
import { newIdempotencyKey } from '../api/client';
import { ApiError } from '../api/errors';
import type { AttachmentSummary, Batch, Run } from '../api/types';

interface Props {
  api: ApiClient;
}

const STAGE_LABEL: Record<Run['stage'], string> = {
  queued: '排队中',
  generating: '生成中',
  validating: '规则校验中',
  reviewing: 'AI 审核中',
  done: '已完成',
};

const STATUS_LABEL: Record<Run['status'], string> = {
  queued: '排队中',
  running: '运行中',
  succeeded: '成功',
  failed: '失败',
  interrupted: '已中断',
};

export default function GeneratePage({ api }: Props) {
  const [form] = Form.useForm();
  const [attachments, setAttachments] = useState<AttachmentSummary[]>([]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [creating, setCreating] = useState(false);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadBatches = useCallback(async () => {
    try {
      const r = await api.listBatches(1, 20);
      setBatches(r.items);
      return r.items;
    } catch {
      return [];
    }
  }, [api]);

  useEffect(() => {
    api.listAttachments(1, 100).then((r) => setAttachments(r.items)).catch(() => {});
    loadBatches();
  }, [api, loadBatches]);

  const stopPolling = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const pollRun = useCallback(
    (runId: string) => {
      stopPolling();
      timerRef.current = setInterval(async () => {
        try {
          const run = await api.getRun(runId);
          setActiveRun(run);
          if (run.status !== 'queued' && run.status !== 'running') {
            stopPolling();
            loadBatches();
            if (run.status === 'failed') {
              message.warning(
                run.error?.code === 'MODEL_TIMEOUT'
                  ? '部分任务审核失败，其余结果已保留'
                  : `作业失败：${run.error?.message ?? '未知错误'}`
              );
            } else if (run.status === 'interrupted') {
              message.warning('作业被服务重启中断，相关任务转为「审核失败」，可手动重审');
            } else {
              message.success('批次生成与审核完成，请到「人工审核」处理');
            }
          }
        } catch {
          setRunError('状态读取失败，正在重试…');
        }
      }, 2000);
    },
    [api, loadBatches]
  );

  useEffect(() => stopPolling, []);

  // 刷新后通过批次 latest_run_id 找回活动作业
  useEffect(() => {
    const active = batches.find(
      (b) => b.latest_run_id && Object.values(b.task_counts).some((v) => v > 0)
    );
    void active;
  }, [batches]);

  const onCreate = async (values: {
    name: string;
    goal: string;
    task_count: number;
    task_mode: 'standard' | 'long';
    reference_text?: string;
    attachment_ids?: string[];
  }) => {
    setCreating(true);
    try {
      const batch = await api.createBatch(
        {
          name: values.name,
          goal: values.goal,
          task_count: values.task_count,
          task_mode: values.task_mode,
          reference_text: values.reference_text ?? '',
          attachment_ids: values.attachment_ids ?? [],
        },
        newIdempotencyKey()
      );
      message.success('批次已创建（未调用模型）');
      await loadBatches();
      return batch;
    } catch (e) {
      message.error(`${(e as ApiError).message}（${(e as ApiError).code}）`);
      return null;
    } finally {
      setCreating(false);
    }
  };

  const onCreateAndGenerate = async () => {
    const values = await form.validateFields();
    const batch = await onCreate(values);
    if (!batch) return;
    try {
      const run = await api.generateBatch(batch.id, newIdempotencyKey());
      setActiveRun(run);
      setRunError(null);
      pollRun(run.id);
      message.info('已开始生成；页面关闭不会取消后台作业');
    } catch (e) {
      const err = e as ApiError;
      message.error(`${err.message}（${err.code}）`);
    }
  };

  const onGenerate = async (batchId: string) => {
    try {
      const run = await api.generateBatch(batchId, newIdempotencyKey());
      setActiveRun(run);
      setRunError(null);
      pollRun(run.id);
    } catch (e) {
      message.error(`${(e as ApiError).message}（${(e as ApiError).code}）`);
    }
  };

  const runActive = activeRun?.status === 'queued' || activeRun?.status === 'running';

  return (
    <Row gutter={16}>
      <Col span={12}>
        <Card title="创建批次" size="small">
          <Form
            form={form}
            layout="vertical"
            initialValues={{ task_count: 3, task_mode: 'long', reference_text: '', attachment_ids: [] }}
          >
            <Form.Item name="name" label="批次名" rules={[{ required: true, message: '请填写批次名' }]}>
              <Input maxLength={100} placeholder="如：居家长任务试跑" />
            </Form.Item>
            <Form.Item name="goal" label="目标要求" rules={[{ required: true, message: '请填写目标' }]}>
              <Input.TextArea
                maxLength={10000}
                autoSize={{ minRows: 2, maxRows: 6 }}
                placeholder="围绕一次真实居家活动设计任务，遵守当前 G2 规则"
              />
            </Form.Item>
            <Space size="large" wrap>
              <Form.Item name="task_count" label="任务数量（1–10）">
                <InputNumber min={1} max={10} />
              </Form.Item>
              <Form.Item name="task_mode" label="任务模式">
                <Radio.Group
                  options={[
                    { value: 'standard', label: '普通（10–20 步）' },
                    { value: 'long', label: '长任务（20–30 步）' },
                  ]}
                  optionType="button"
                />
              </Form.Item>
            </Space>
            <Form.Item name="reference_text" label="粘贴资料（可选，与附件至少一项）">
              <Input.TextArea
                maxLength={80000}
                autoSize={{ minRows: 2, maxRows: 4 }}
                placeholder="台面物料包括收纳篮、带拉链的收纳袋、毛巾；按附件中的实际库存设计。"
              />
            </Form.Item>
            <Form.Item name="attachment_ids" label="选择资料附件">
              <Select
                mode="multiple"
                allowClear
                placeholder="选择「资料」页上传的附件"
                options={attachments.map((a) => ({
                  value: a.id,
                  label: `${a.filename}（${a.text_length} 字）`,
                }))}
              />
            </Form.Item>
            <Space>
              <Button onClick={() => form.validateFields().then(onCreate)} loading={creating}>
                仅创建批次
              </Button>
              <Button type="primary" onClick={onCreateAndGenerate} loading={creating || runActive}>
                创建并开始生成
              </Button>
            </Space>
          </Form>
        </Card>
      </Col>
      <Col span={12}>
        {activeRun && (
          <Card size="small" title="当前作业" style={{ marginBottom: 16 }}>
            <Space wrap>
              <Tag color={activeRun.status === 'failed' ? 'red' : activeRun.status === 'succeeded' ? 'green' : 'processing'}>
                {STATUS_LABEL[activeRun.status]}
              </Tag>
              <Tag>{STAGE_LABEL[activeRun.stage]}</Tag>
              <span>
                进度：{activeRun.progress.completed}/{activeRun.progress.total}
                {activeRun.progress.failed > 0 && (
                  <span style={{ color: '#cf1322' }}>（失败 {activeRun.progress.failed}）</span>
                )}
              </span>
            </Space>
            {activeRun.error && (
              <Alert
                style={{ marginTop: 8 }}
                type={activeRun.progress.failed > 0 && activeRun.progress.completed > activeRun.progress.failed ? 'warning' : 'error'}
                showIcon
                message={`${activeRun.error.code}：${activeRun.error.message}`}
                description={activeRun.progress.failed > 0 ? '部分结果已保留，可在「人工审核」查看' : undefined}
              />
            )}
            {runError && <Alert style={{ marginTop: 8 }} type="warning" showIcon message={runError} />}
          </Card>
        )}
        <Card title="最近批次" size="small">
          <Table
            rowKey="id"
            size="small"
            dataSource={batches}
            pagination={false}
            columns={[
              { title: '批次', dataIndex: 'name', ellipsis: true },
              { title: '模式', dataIndex: 'task_mode', width: 70, render: (m: string) => (m === 'long' ? '长' : '普通') },
              {
                title: '任务计数',
                dataIndex: 'task_counts',
                width: 200,
                render: (c: Batch['task_counts']) => (
                  <Typography.Text style={{ fontSize: 12 }}>
                    待人工 {c.human_pending} / 退回 {c.ai_rejected} / 失败 {c.review_failed} / 通过 {c.approved}
                  </Typography.Text>
                ),
              },
              {
                title: '操作',
                width: 110,
                render: (_: unknown, b: Batch) => (
                  <Button
                    size="small"
                    type="primary"
                    ghost
                    disabled={!b.can_generate || runActive}
                    onClick={() => onGenerate(b.id)}
                  >
                    {b.can_generate ? '开始生成' : '已生成'}
                  </Button>
                ),
              },
            ]}
          />
        </Card>
      </Col>
    </Row>
  );
}
