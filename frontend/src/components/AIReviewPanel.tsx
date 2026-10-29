import { Spin, Tag } from 'antd';
import type { TaskDetail } from '../api/types';

export default function AIReviewPanel({ detail }: { detail: TaskDetail }) {
  const { summary, current_version: version, latest_review: review } = detail;
  const busy = Boolean(summary.busy_run_id);
  const current = detail.ai_review_matches_current_version;
  const failed = summary.status === 'review_failed';
  const blocked = summary.status === 'ai_rejected';
  const optimized = version.author_type === 'ai_revision' && version.change_note.startsWith('AI 审核员优化：');
  const tone = busy ? 'working' : failed ? 'failed' : blocked ? 'attention' : current ? 'complete' : 'waiting';
  const title = busy ? '正在审查与优化' : failed ? '审核连接或执行失败' : blocked ? '仍有问题需要人工处理'
    : current ? (optimized ? (summary.status === 'human_pending' ? '已优化，等待人工审核' : '审查与优化已完成') : '审查完成') : '等待审核当前版本';

  return (
    <section className={`ai-review-panel ai-review-${tone}`} aria-label="AI 审核员" aria-live="polite">
      <div className="ai-review-heading">
        <span className="ai-review-avatar" aria-hidden="true">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
          </svg>
        </span>
        <div className="ai-review-identity"><strong>AI 审核员</strong><span>审查问题 · 直接优化 · 保留版本</span></div>
        {busy && <Spin size="small" />}
      </div>
      <div className="ai-review-result">{title}</div>
      <div className="ai-review-description">
        {busy ? '正在处理当前任务，完成后自动更新正文和审核结论。'
          : failed ? '任务正文已保留，可以点击「重新审核」继续处理。'
          : review && current ? review.summary
          : '当前正文尚无匹配的审核结论，重新审核后可查看结果。'}
      </div>
      <div className="ai-review-facts">
        <Tag>正文 v{version.version_no}</Tag>
        <Tag color={version.validation.status === 'passed' ? 'green' : 'orange'}>
          {version.validation.status === 'passed' ? '规则校验通过' : '规则问题待解决'}
        </Tag>
        {optimized && <Tag color="blue">已保存优化版本</Tag>}
        {review && !current && <Tag>上次结论属于旧版本</Tag>}
      </div>
      {!busy && review && current && review.issues.length > 0 && (
        <ul className="ai-review-issues">
          {review.issues.map((issue, index) => (
            <li key={index}>
              <strong>{issue.severity === 'error' ? '待处理' : '建议'}{issue.step_no ? ` · 第 ${issue.step_no} 步` : ''}</strong>
              <p>{issue.message}</p>
              {issue.suggestion && <p className="ai-review-description">{issue.suggestion}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
