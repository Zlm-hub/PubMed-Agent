/**
 * 左侧导航栏：品牌区 / 新对话 / 快捷开始 / 历史会话 / 设置与配置 / 工作目录。
 *
 * 布局参照参考产品，但**内容全部是本项目真实具备的能力**：
 * - 快捷开始前 6 项均能跑到真实链路；后 2 项显式标注「规划中」而非虚标。
 * - 「设置与配置」展示的是后端真实默认值（backend/app/config.py）。
 * - 「工作目录」列出的是真实存在的产物文件，不是渲染出来的假文件树。
 */
import { useState } from "react";
import { QUICK_STARTS, Session, type QuickStart } from "./model";

const ICONS: Record<string, string> = {
  search: "M6.5 11a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9Zm3.5-1 3 3",
  chart: "M2 13V8M6 13V3M10 13V6M14 13V9",
  cloud: "M5 11.5a3 3 0 0 1 .4-6 3.6 3.6 0 0 1 6.9 1A2.6 2.6 0 0 1 12 11.5H5Z",
  list: "M3 4h10M3 8h10M3 12h6",
  doc: "M4 2h5l3 3v9H4V2Zm5 0v3h3",
  bulb: "M8 2.5a3.8 3.8 0 0 1 2.3 6.8V11h-4.6V9.3A3.8 3.8 0 0 1 8 2.5ZM6.6 13h2.8",
  spark: "M8 2.5v2.6M8 10.9v2.6M2.5 8h2.6M10.9 8h2.6M4.4 4.4l1.8 1.8M9.8 9.8l1.8 1.8M11.6 4.4l-1.8 1.8M6.2 9.8l-1.8 1.8",
  flow: "M3 2.5h4v2.6H3V2.5Zm6 8.4h4v2.6H9v-2.6ZM7 3.8h3a2 2 0 0 1 2 2v4.7",
  gear: "M8 9.8a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6ZM8 1.8l.7 1.6 1.7-.4.6 1.7 1.6.7-.4 1.7.4 1.7-1.6.7-.6 1.7-1.7-.4L8 14.2l-.7-1.6-1.7.4-.6-1.7L3.4 10l.4-1.7-.4-1.7 1.6-.7.6-1.7 1.7.4L8 1.8Z",
  folder: "M2 4h4l1.5 2H14v7H2V4Z",
  plus: "M8 3.2v9.6M3.2 8h9.6",
};

export function Icon({ name, className = "" }: { name: string; className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="15"
      height="15"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
      aria-hidden="true"
    >
      <path d={ICONS[name] ?? ICONS.doc} />
    </svg>
  );
}

interface Props {
  sessions: Session[];
  activeKeyword: string;
  mockMode: boolean | null;
  onNewChat: () => void;
  onQuickStart: (q: QuickStart) => void;
  onOpenSession: (s: Session) => void;
  onClearSessions: () => void;
  onOpenReport: () => void;
}

export default function Sidebar({
  sessions,
  activeKeyword,
  mockMode,
  onNewChat,
  onQuickStart,
  onOpenSession,
  onClearSessions,
  onOpenReport,
}: Props) {
  const [panel, setPanel] = useState<"" | "config" | "files">("");

  return (
    <aside className="flex w-[236px] shrink-0 flex-col border-r border-line bg-white">
      <div className="px-3 pb-3 pt-4">
        <div className="flex items-center gap-2.5">
          <div className="grid h-8 w-8 place-items-center rounded-md bg-brand">
            <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="#fff" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
              <path d={ICONS.doc} />
            </svg>
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold leading-5">PubMed Agent</div>
            <div className="truncate text-[11px] text-muted">生物医学文献分析助手</div>
          </div>
        </div>
        <button
          type="button"
          onClick={onNewChat}
          className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md bg-brand py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
        >
          <Icon name="plus" />
          新对话
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-2">
        <div className="px-1 pb-1.5 pt-1 text-[11px] font-medium text-muted">快捷开始</div>
        <nav className="space-y-0.5">
          {QUICK_STARTS.map((q) => {
            const active = !!q.keyword && q.keyword === activeKeyword;
            return (
              <button
                key={q.id}
                type="button"
                title={q.desc}
                disabled={q.planned}
                onClick={() => onQuickStart(q)}
                className={`flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors ${
                  q.planned
                    ? "cursor-not-allowed text-muted/45"
                    : active
                      ? "bg-brand/10 text-brand"
                      : "text-ink hover:bg-appbg"
                }`}
              >
                <Icon name={q.id} className={q.planned ? "" : "text-brand"} />
                <span className="min-w-0 flex-1 truncate text-[13px] leading-5">{q.label}</span>
                {q.planned && <span className="shrink-0 text-[10px] text-muted/70">规划中</span>}
              </button>
            );
          })}
        </nav>

        <div className="mt-5 flex items-center justify-between px-1 pb-1.5">
          <span className="text-[11px] font-medium text-muted">历史会话</span>
          {sessions.length > 0 && (
            <button type="button" onClick={onClearSessions} className="text-[11px] text-muted transition-colors hover:text-accent">
              清空
            </button>
          )}
        </div>
        {sessions.length === 0 ? (
          <div className="px-2 text-[11px] leading-5 text-muted/70">暂无记录，检索后自动保存。</div>
        ) : (
          <nav className="space-y-0.5">
            {sessions.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => onOpenSession(s)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-muted transition-colors hover:bg-appbg hover:text-ink"
              >
                <Icon name="doc" />
                <span className="min-w-0 flex-1 truncate text-[13px] leading-5">{s.title}</span>
              </button>
            ))}
          </nav>
        )}
      </div>

      {panel !== "" && (
        <div className="mx-3 mb-2 rounded-md border border-line bg-appbg p-2.5 text-[11px] leading-5">
          {panel === "config" ? (
            <>
              <div className="mb-1.5 font-medium text-ink">后端配置（真实默认值）</div>
              <div className="space-y-0.5 text-muted">
                <div>大模型 · qwen-plus（DashScope 兼容）</div>
                <div>密钥状态 · {mockMode === false ? "已配置，走真实 LLM" : mockMode === true ? "未配置，走统计兜底" : "未检测"}</div>
                <div>综述取摘要 · Top 30 篇</div>
                <div>检索上限 · 1000（默认取 200）</div>
                <div>缓存 · 内存 + 文件预缓存，TTL 未启用</div>
                <div>期刊指标 · journal_metrics.json（1324 本）</div>
              </div>
              <div className="mt-1.5 text-muted/80">值来自 backend/app/config.py，前端不硬编码模型名以外的参数。</div>
            </>
          ) : (
            <>
              <div className="mb-1.5 font-medium text-ink">工作目录（真实产物）</div>
              <div className="space-y-0.5 font-mono text-muted">
                <div>backend/cache/*.json</div>
                <div>docs/01-overview.png</div>
                <div>docs/02-charts.png</div>
                <div>docs/03-wordcloud.png</div>
                <div>docs/04-top100.png</div>
                <div>docs/05-agent-home.png</div>
                <div>docs/06-agent-flow.png</div>
              </div>
              <div className="mt-1.5 text-muted/80">
                预缓存数据集 3 个（对应预置关键词）；交付截图 6 张。Top100 CSV 在报告视图内导出。
              </div>
              <button type="button" onClick={onOpenReport} className="mt-2 w-full rounded border border-line bg-white py-1 text-muted transition-colors hover:border-brand hover:text-brand">
                在报告中查看
              </button>
            </>
          )}
        </div>
      )}

      <div className="border-t border-line px-3 py-2">
        <button
          type="button"
          onClick={() => setPanel((p) => (p === "config" ? "" : "config"))}
          className={`flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] transition-colors ${panel === "config" ? "bg-brand/10 text-brand" : "text-muted hover:bg-appbg hover:text-ink"}`}
        >
          <Icon name="gear" />
          设置与配置
        </button>
        <button
          type="button"
          onClick={() => setPanel((p) => (p === "files" ? "" : "files"))}
          className={`flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] transition-colors ${panel === "files" ? "bg-brand/10 text-brand" : "text-muted hover:bg-appbg hover:text-ink"}`}
        >
          <Icon name="folder" />
          工作目录
        </button>
      </div>
    </aside>
  );
}
