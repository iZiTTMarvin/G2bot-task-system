import { ConfigProvider, Layout, Menu, Typography } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { useState } from 'react';
import { realClient } from './api';
import GeneratePage from './pages/GeneratePage';
import ReviewPage from './pages/ReviewPage';
import SettingsPage from './pages/SettingsPage';
import './app.css';

const { Header, Sider, Content } = Layout;

type PageKey = 'generate' | 'review' | 'settings';

const PAGE_TITLE: Record<PageKey, string> = {
  generate: '任务生成',
  review: '人工审核',
  settings: 'API 设置',
};

export default function App() {
  const [page, setPage] = useState<PageKey>('generate');

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          borderRadius: 8,
          colorPrimary: '#3157c8',
          colorBgLayout: '#f5f6f8',
          fontFamily: 'Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
        },
      }}
    >
      <Layout className="app-shell">
        <Sider className="app-sider" width={216} breakpoint="lg" collapsedWidth={0}>
          <div className="app-brand">
            <span className="app-brand-mark">G2</span>
            <span>任务系统</span>
          </div>
          <Menu
            className="app-menu"
            mode="inline"
            selectedKeys={[page]}
            onClick={(event) => setPage(event.key as PageKey)}
            items={[
              { key: 'generate', label: '任务生成' },
              { key: 'review', label: '人工审核' },
              { key: 'settings', label: 'API 设置' },
            ]}
          />
        </Sider>
        <Layout>
          <Header className="app-header">
            <Typography.Title level={4}>{PAGE_TITLE[page]}</Typography.Title>
          </Header>
          <Content className="app-content">
            {page === 'generate' && <GeneratePage api={realClient} />}
            {page === 'review' && <ReviewPage api={realClient} />}
            {page === 'settings' && <SettingsPage api={realClient} />}
          </Content>
        </Layout>
      </Layout>
    </ConfigProvider>
  );
}
