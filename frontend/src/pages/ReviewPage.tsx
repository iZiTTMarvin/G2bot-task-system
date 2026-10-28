// 人工审核页：状态页签（服务端全量计数）+ 表格 + 详情抽屉 + 已通过导出。
import {
  Alert, Button, Input, Pagination, Select, Space, Spin, Table, Tabs, Tag, Typography, message,
} from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ApiClient } from '../api/client';
import { newIdempotencyKey } from '../api/client';
import { ApiError } from '../api/errors';
import type { Batch, TaskPage, TaskStatus, TaskSummary } from '../api/types';
import { STATUS_LABEL, STATUS_ORDER } from '../api/types';
import TaskDrawer from '../components/TaskDrawer';

interface Props {
  api: ApiClient;
}

export default function ReviewPage({ api }: Props) {
  const [page, setPage] = useState<TaskPage | null>(null);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [status, setStatus] = useState<TaskStatus>('human_pending');
  const [batchId, setBatchId] = useState<string | undefined>();
  const [q, setQ] = useState('');
  const [pageNum, setPageNum] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openTaskId, setOpenTaskId] = useState<string | null>(null);
  const [selectedApproved, setSelectedApproved] = useState<string[]>([]);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listTasks({
        status,
        batch_id: batchId,
        q: q || undefined,
        page: pageNum,
        page_size: 20,
      });
      setPage(data);
    } catch (e) {
      setError((e as ApiError).message ?? '列表读取失败');
    } finally {
      setLoading(false);
    }
  }, [api, status, batchId, q, pageNum]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    api.listBatches(1, 100).then((r) => setBatches(r.items)).catch(() => {});
  }, [api]);

  // 活动作业时 2 秒轮询刷新（终态自然停止：无 busy 任务即停）
  const hasBusy = !!page?.items.some((t) => t.busy_run_id);
  useEffect(() => {
    if (!hasBusy) return;
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [hasBusy, load]);

  const counts = page?.status_counts;

  const doExport = async () => {
    if (selectedApproved.length === 0) return;
    const batchOf = page?.items.find((t) => t.id === selectedApproved[0])?.batch_id;
    if (!batchOf) return;
    if (selectedApproved.some((id) => page?.items.find((t) => t.id === id)?.batch_id !== batchOf)) {
      message.warning('只能导出同一批次的任务');
      return;
    }
    setExporting(true);
    try {
      const rec = await api.createExport(
        { batch_id: batchOf, task_ids: selectedApproved },
        newIdempotencyKey()
      );
      const blob = await api.downloadExport(rec.download_url);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = rec.filename;
      a.click();
      URL.revokeObjectURL(url);
      message.success(`已导出 ${rec.versions.length} 条任务`);
      setSelectedApproved([]);
    } catch (e) {
      message.error(`${(e as ApiError).message}（${(e as ApiError).code}）`);
    } finally {
      setExporting(false);
    }
  };

  const columns = useMemo(
    () => [
      { title: '任务名', dataIndex: 'name', key: 'name', ellipsis: true },
      {
        title: '批次',
        dataIndex: 'batch_id',
        key: 'batch',
        width: 150,
        ellipsis: true,
        render: (id: string) => batches.find((b) => b.id === id)?.name ?? id.slice(0, 12),
      },
      { title: '步骤数', dataIndex: 'step_count', key: 'steps', width: 80 },
      { title: '当前版本', dataIndex: 'version_no', key: 'version', width: 90, render: (v: number) => `v${v}` },
      {
        title: '人工修改',
        dataIndex: 'human_edited',
        key: 'human_edited',
        width: 90,
        render: (v: boolean) => (v ? <Tag color="blue">是</Tag> : <Tag>否</Tag>),
      },
      {
        title: '更新时间',
        dataIndex: 'updated_at',
        key: 'updated_at',
        width: 160,
        render: (t: string) => new Date(t).toLocaleString(),
      },
      {
        title: '操作',
        key: 'action',
        width: 90,
        render: (_: unknown, record: TaskSummary) => (
          <Button size="small" type="link" onClick={() => setOpenTaskId(record.id)}>
            查看 / 审核
          </Button>
        ),
      },
    ],
    [batches]
  );

  return (
    <div>
      {error && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="列表读取失败"
          description={error}
          action={
            <Button size="small" onClick={load}>
              重试
            </Button>
          }
        />
      )}
      <Tabs
        activeKey={status}
        onChange={(key) => {
          setStatus(key as TaskStatus);
          setPageNum(1);
          setSelectedApproved([]);
        }}
        items={STATUS_ORDER.map((s) => ({
          key: s,
          label: `${STATUS_LABEL[s]}${counts ? ` (${counts[s]})` : ''}`,
        }))}
      />
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          allowClear
          placeholder="按批次筛选"
          style={{ width: 220 }}
          value={batchId}
          onChange={(v) => {
            setBatchId(v);
            setPageNum(1);
          }}
          options={batches.map((b) => ({ value: b.id, label: b.name }))}
        />
        <Input.Search
          placeholder="按任务名搜索（字面包含）"
          style={{ width: 260 }}
          allowClear
          onSearch={(v) => {
            setQ(v);
            setPageNum(1);
          }}
        />
        <Typography.Text type="secondary">
          共 {page?.total ?? 0} 条（当前筛选）
        </Typography.Text>
        {status === 'approved' && (
          <Button
            type="primary"
            disabled={selectedApproved.length === 0}
            loading={exporting}
            onClick={doExport}
          >
            导出选中（{selectedApproved.length}）为 XLSX
          </Button>
        )}
      </Space>

      <Spin spinning={loading}>
        <Table
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={page?.items ?? []}
          pagination={false}
          locale={{ emptyText: '暂无任务；可先到「任务生成」页创建批次并生成' }}
          rowSelection={
            status === 'approved'
              ? {
                  selectedRowKeys: selectedApproved,
                  onChange: (keys) => setSelectedApproved(keys as string[]),
                  getCheckboxProps: (record: TaskSummary) => ({
                    disabled: record.status !== 'approved' || !!record.busy_run_id,
                  }),
                }
              : undefined
          }
          onRow={(record) => ({
            onClick: (e) => {
              if ((e.target as HTMLElement).closest('button, input, .ant-checkbox')) return;
              setOpenTaskId(record.id);
            },
            style: { cursor: 'pointer' },
          })}
        />
      </Spin>
      <div style={{ marginTop: 12, textAlign: 'right' }}>
        <Pagination
          current={pageNum}
          pageSize={20}
          total={page?.total ?? 0}
          showSizeChanger={false}
          onChange={setPageNum}
        />
      </div>

      <TaskDrawer
        api={api}
        taskId={openTaskId}
        onClose={(changed) => {
          setOpenTaskId(null);
          if (changed) load();
        }}
        onUpdated={load}
      />
    </div>
  );
}
