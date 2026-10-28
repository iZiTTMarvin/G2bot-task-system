// Mock 控制台：仅 mock 模式显示，用于注入契约第 9 节的故障场景。
import { Button, Card, Popconfirm, Select, Space } from 'antd';
import { useState } from 'react';
import { mockFaults, mockClient, resetMockFaults } from '../api/mock';

export default function MockConsole() {
  const [, force] = useState(0);
  const rerender = () => force((n) => n + 1);

  return (
    <div style={{ position: 'fixed', right: 16, bottom: 16, zIndex: 1000, maxWidth: 340 }}>
      <Card
        size="small"
        title="Mock 控制台（仅前端演示数据）"
        extra={
          <Button size="small" onClick={() => { resetMockFaults(); rerender(); }}>
            重置故障
          </Button>
        }
      >
        <Space direction="vertical" style={{ width: '100%' }} size="small">
          <Space wrap>
            <span style={{ fontSize: 12 }}>生成结果：</span>
            <Select
              size="small"
              style={{ width: 190 }}
              value={mockFaults.generateMode}
              onChange={(v) => {
                mockFaults.generateMode = v;
                rerender();
              }}
              options={[
                { value: 'ok', label: '正常（AI 全通过）' },
                { value: 'ai_reject', label: 'AI 质量退回' },
                { value: 'partial_review_fail', label: '部分审核调用失败' },
                { value: 'model_error', label: '模型认证失败' },
              ]}
            />
          </Space>
          <Space wrap>
            <Button
              size="small"
              danger={mockFaults.nextSaveConflict}
              onClick={() => {
                mockFaults.nextSaveConflict = true;
                rerender();
                alert('已注入：下一次保存将返回 REVISION_CONFLICT（模拟另一页面先保存）');
              }}
            >
              下次保存冲突 409
            </Button>
            <Button
              size="small"
              danger={mockFaults.nextApproveFail}
              onClick={() => {
                mockFaults.nextApproveFail = true;
                rerender();
                alert('已注入：下一次「通过」将失败（验证“保存成功但通过失败”场景）');
              }}
            >
              下次通过失败
            </Button>
          </Space>
          <Space wrap>
            <Popconfirm
              title="模拟服务重启？"
              description="运行中的作业将标记 interrupted，被占用任务转为审核失败。"
              onConfirm={() => {
                mockClient.simulateRestart();
                alert('已模拟重启：作业 interrupted、任务 review_failed；可手动重审恢复');
                window.location.reload();
              }}
            >
              <Button size="small">模拟服务重启</Button>
            </Popconfirm>
            <Popconfirm
              title="重置演示数据？"
              onConfirm={() => {
                mockClient.reseed();
                window.location.reload();
              }}
            >
              <Button size="small">重置演示数据</Button>
            </Popconfirm>
          </Space>
        </Space>
      </Card>
    </div>
  );
}
