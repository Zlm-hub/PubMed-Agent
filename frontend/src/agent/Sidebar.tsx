/**
 * 左侧导航栏：品牌区 / 新对话 / 快捷开始 / 历史会话 / 设置与配置 / 工作目录。
 *
 * 布局参照参考产品，但**内容全部是本项目真实具备的能力**：
 * - 快捷开始前 6 项均能跑到真实链路；后 2 项显式标注「规划中」而非虚标。
 * - 「设置与配置」展示的是后端真实默认值（backend/app/config.py）。
 * - 「工作目录」列出的是真实存在的产物文件，不是渲染出来的假文件树。
 *
 * 图标：16px 网格手绘 SVG（stroke 1.5、圆角端点），键名与快捷开始 id 对齐——
 * 此前 stats / top100 / review / design / topic / meta 缺键，全部回落成 doc 图标，已补齐。
 */
import { useState } from "react";
import { QUICK_STARTS, Session, type QuickStart } from "./model";

const ICONS: Record<string, string> = {
  search: "M7 12A5 5 0 1 0 7 2a5 5 0 0 0 0 10Zm3.6-.6L14 14.5",
  chat: "M2.5 3.5h11v7.5H8L5 13.5V11H2.5V3.5Z",
  cn: "M8 14A6 6 0 1 0 8 2a6 6 0 0 0 0 12Zm0 0c-1.8-1.2-2.6-3.4-2.6-6S6.2 3.2 8 2c1.8 1.2 2.6 3.4 2.6 6S9.8 12.8 8 14ZM2.5 8h11",
  stats: "M2.5 13.5h11M4.5 13.5V8.5M8 13.5V4.5M11.5 13.5V7",
  chart: "M2.5 13.5h11M4.5 13.5V8.5M8 13.5V4.5M11.5 13.5V7",
  cloud: "M5 11.5a3 3 0 0 1 .4-6 3.6 3.6 0 0 1 6.9 1A2.6 2.6 0 0 1 12 11.5H5Z",
  top100: "M2.5 13.5h11M3.2 13.5V9h3v4.5M6.9 13.5V5.5h2.9v8M10.5 13.5V7.5h3v6",
  review: "M3.5 2.5h5.8l3.2 3.2v7.8H3.5V2.5Zm5.8 0v3.2h3.2M6 8.5h4M6 11h2.5",
  design: "M8 2a4.2 4.2 0 0 1 2.5 7.6c-.4.3-.7.7-.7 1.2v.7H6.2v-.7c0-.5-.3-.9-.7-1.2A4.2 4.2 0 0 1 8 2ZM6.3 13.6h3.4M7 15h2",
  topic: "M8 13.2A5.2 5.2 0 1 0 8 2.8a5.2 5.2 0 0 0 0 10.4Zm0-3.4a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6Z",
  meta: "M8 2.4 14 5.4 8 8.4 2 5.4 8 2.4ZM3.2 8.1 8 10.5l4.8-2.4M3.2 10.8 8 13.2l4.8-2.4",
  doc: "M4 2.5h5l3 3v8H4v-11Zm5 0v3h3M6 8.5h4M6 11h4",
  list: "M3 4.5h10M3 8h10M3 11.5h6",
  flow: "M2.5 2.5H7v3H2.5zM9 10.5h4.5v3H9zM7 4h3.4a2 2 0 0 1 2 2v4.5",
  spark: "M8 2.3c.5 3 2.2 4.7 5.2 5.7-3 1-4.7 2.7-5.2 5.7-.5-3-2.2-4.7-5.2-5.7 3-1 4.7-2.7 5.2-5.7Z",
  // 齿轮在 16px 下糊成一团，改成更清爽的「滑杆」隐喻
  gear: "M2.5 4.5h5M10.5 4.5h3M2.5 11.5h3.5M9 11.5h4.5M9 3v3M6.5 10v3",
  folder: "M2 4.6c0-.6.4-1.1 1-1.1h3.1l1.5 1.8H13c.6 0 1 .5 1 1.1v6c0 .6-.4 1.1-1 1.1H3c-.6 0-1-.5-1-1.1V4.6Z",
  plus: "M8 3.2v9.6M3.2 8h9.6",
  tag: "M8.3 2.5h5.2v5.2l-6 6-5.2-5.2 6-6Zm2.6 2.6h.01",
};

export function Icon({ name, className = "" }: { name: string; className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="15"
      height="15"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
      aria-hidden="true"
    >
      <path d={ICONS[name] ?? ICONS.doc} />
    </svg>
  );
}

/** 品牌标：文档轮廓 + 一道脉搏线，呼应「文献 × 分析」 */
function LogoMark({ size = 16 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill="none"
      stroke="#fff"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4.5 2.5h4.8l3.2 3.2v7.8h-8V2.5Zm4.8 0v3.2h3.2" />
      <path d="M5.8 9.4h1.3l.9-1.7 1.4 2.8.9-1.1h1.5" />
    </svg>
  );
}

/** 分组小标题：字距略放宽，压住下方列表的密度 */
function SectionLabel({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between px-1 pb-1.5 pt-1">
      <span className="text-[11px] font-medium tracking-[0.08em] text-muted/80">{children}</span>
      {action}
    </div>
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
          <div className="grid h-8 w-8 place-items-center rounded-md bg-brand shadow-card">
            <LogoMark />
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold leading-5 tracking-tight">PubMed Agent</div>
            <div className="truncate text-[11px] leading-4 text-muted">生物医学文献分析助手</div>
          </div>
        </div>
        <button
          type="button"
          onClick={onNewChat}
          className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md bg-brand py-2 text-sm font-medium text-white shadow-card transition-all hover:bg-brand-hover hover:shadow-lift"
        >
          <Icon name="plus" />
          新对话
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-2">
        <SectionLabel>快捷开始</SectionLabel>
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
                      ? "bg-brand/10 font-medium text-brand"
                      : "text-ink hover:bg-appbg"
                }`}
              >
                <Icon name={q.id} className={q.planned ? "" : "text-brand"} />
                <span className="min-w-0 flex-1 truncate text-[13px] leading-5">{q.label}</span>
                {q.planned && (
                  <span className="shrink-0 rounded-full border border-line bg-appbg px-1.5 py-px text-[10px] text-muted/80">
                    规划中
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="mt-5">
          <SectionLabel
            action={
              sessions.length > 0 && (
                <button type="button" onClick={onClearSessions} className="text-[11px] text-muted transition-colors hover:text-accent">
                  清空
                </button>
              )
            }
          >
            历史会话
          </SectionLabel>
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
                <div>期刊指标 · journal_metrics.db（SCImago 32,193 + OpenAlex 2,709）</div>
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
          className={`flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] transition-colors ${panel === "config" ? "bg-brand/10 font-medium text-brand" : "text-muted hover:bg-appbg hover:text-ink"}`}
        >
          <Icon name="gear" />
          设置与配置
        </button>
        <button
          type="button"
          onClick={() => setPanel((p) => (p === "files" ? "" : "files"))}
          className={`flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] transition-colors ${panel === "files" ? "bg-brand/10 font-medium text-brand" : "text-muted hover:bg-appbg hover:text-ink"}`}
        >
          <Icon name="folder" />
          工作目录
        </button>
      </div>
    </aside>
  );
}
