import { ConfigProvider, Layout, Menu, Switch, Tag, Typography, message } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useState } from 'react';
import AttachmentsPage from './pages/AttachmentsPage';
import GeneratePage from './pages/GeneratePage';
import ReviewPage from './pages/ReviewPage';
import SettingsPage from './pages/SettingsPage';
import MockConsole from './components/MockConsole';
import { getApiClient, getApiMode, setApiMode } from './api';

const { Header, Sider, Content } = Layout;

type PageKey = 'generate' | 'review' | 'attachments' | 'settings';

const PAGE_TITLE: Record<PageKey, string> = {
  generate: '任务生成',
  review: '人工审核',
  attachments: '资料',
  settings: '设置',
};

export default function App() {
  const [page, setPage] = useState<PageKey>('review');
  const [mode, setMode] = useState(getApiMode());
  const [messageApi, contextHolder] = message.useMessage();
  const api = getApiClient();

  const toggleMode = (checked: boolean) => {
    const next = checked ? 'real' : 'mock';
    setApiMode(next);
    setMode(next);
    messageApi.info(next === 'mock' ? '已切换到 Mock 数据（仅验证交互）' : '已连接真实服务 /api/v1');
  };

  return (
    <ConfigProvider locale={zhCN} theme={{ token: { borderRadius: 6 } }}>
      {contextHolder}
      <Layout style={{ minHeight: '100vh' }}>
        <Sider theme="dark" width={200}>
          <div style={{ color: '#fff', padding: 20, fontWeight: 700, fontSize: 16 }}>G2 任务系统</div>
          <Menu
            theme="dark"
            mode="inline"
            selectedKeys={[page]}
            onClick={(e) => setPage(e.key as PageKey)}
            items={[
              { key: 'generate', label: '任务生成' },
              { key: 'review', label: '人工审核' },
              { key: 'attachments', label: '资料' },
              { key: 'settings', label: '设置' },
            ]}
          />
        </Sider>
        <Layout>
          <Header
            style={{
              background: '#fff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '0 24px',
              borderBottom: '1px solid #f0f0f0',
            }}
          >
            <Typography.Title level={4} style={{ margin: 0 }}>
              {PAGE_TITLE[page]}
            </Typography.Title>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              {mode === 'mock' && (
                <Tag color="orange" data-testid="mock-badge">
                  Mock 数据·非真实结果
                </Tag>
              )}
              {mode === 'real' && <Tag color="green">真实服务</Tag>}
              <span style={{ fontSize: 13 }}>Mock</span>
              <Switch checked={mode === 'real'} onChange={toggleMode} />
              <span style={{ fontSize: 13 }}>真实</span>
            </div>
          </Header>
          <Content style={{ padding: 20, overflow: 'auto' }}>
            {page === 'generate' && <GeneratePage api={api} />}
            {page === 'review' && <ReviewPage api={api} />}
            {page === 'attachments' && <AttachmentsPage api={api} />}
            {page === 'settings' && <SettingsPage api={api} />}
          </Content>
        </Layout>
        {mode === 'mock' && <MockConsole />}
      </Layout>
    </ConfigProvider>
  );
}
