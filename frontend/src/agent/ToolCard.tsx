/**
 * 单条工具调用卡片。
 *
 * 视觉上还原参考产品的「工具调用块」：一行摘要 + 可展开的入参/结果。
 * 状态四态：pending / running / done / error，全部用 SVG 绘制，不依赖字体图标。
 * 每张卡按工具名配一枚专属图标（对齐后端真实函数），右侧箭头提示可展开。
 */
import { useState } from "react";
import type { ToolCall } from "./model";
import { Icon } from "./Sidebar";

/** 工具完全限定名 -> 图标键；未命中不显示图标 */
const TOOL_ICON: Record<string, string> = {
  "pubmed.esearch": "search",
  "pubmed.efetch": "doc",
  "metrics.annotate": "tag",
  "analyze.aggregate": "chart",
  "review.generate": "review",
};

function StatusMark({ status }: { status: ToolCall["status"] }) {
  if (status === "running") {
    return (
      <span className="relative flex h-4 w-4 items-center justify-center">
        <svg viewBox="0 0 16 16" width="16" height="16" className="animate-spin text-brand">
          <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2" />
          <path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </span>
    );
  }
  if (status === "done") {
    return (
      <svg viewBox="0 0 16 16" width="16" height="16" className="text-emerald-500">
        <circle cx="8" cy="8" r="6.5" fill="currentColor" fillOpacity="0.12" />
        <path d="M5 8.2l2.1 2.1L11 6.4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (status === "error") {
    return (
      <svg viewBox="0 0 16 16" width="16" height="16" className="text-accent">
        <circle cx="8" cy="8" r="6.5" fill="currentColor" fillOpacity="0.12" />
        <path d="M6 6l4 4M10 6l-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" className="text-muted/50">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

const LABEL: Record<ToolCall["status"], string> = {
  pending: "等待中",
  running: "执行中",
  done: "完成",
  error: "失败",
};

export default function ToolCard({ tool }: { tool: ToolCall }) {
  const [open, setOpen] = useState(false);
  const running = tool.status === "running";
  const iconName = TOOL_ICON[tool.name];

  return (
    <div
      className={`rounded-md border bg-white shadow-card transition-colors ${
        running ? "border-brand/40" : "border-line"
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left"
      >
        <span className="mt-0.5 shrink-0">
          <StatusMark status={tool.status} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className="flex items-baseline gap-1.5">
              {iconName && <Icon name={iconName} className="relative top-0.5 text-muted" />}
              <span className="text-sm font-medium text-ink">{tool.title}</span>
            </span>
            <span className="truncate font-mono text-[11px] text-muted/80">{tool.name}</span>
          </span>
          {tool.result && <span className="mt-0.5 block text-xs leading-5 text-brand">{tool.result}</span>}
        </span>
        <span className="flex shrink-0 items-center gap-1.5 pt-0.5 text-[11px] tabular-nums text-muted">
          {LABEL[tool.status]}
          {tool.status === "done" && tool.ms != null && <span className="font-mono">{tool.ms} ms</span>}
          <svg
            viewBox="0 0 16 16"
            width="10"
            height="10"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={`text-muted/60 transition-transform ${open ? "rotate-90" : ""}`}
            aria-hidden="true"
          >
            <path d="M6 3.5L10.5 8 6 12.5" />
          </svg>
        </span>
      </button>

      {open && (
        <div className="border-t border-line px-3 py-2">
          <div className="text-[11px] font-medium tracking-[0.08em] text-muted/80">入参</div>
          <dl className="mt-1 space-y-0.5">
            {Object.entries(tool.args).map(([k, v]) => (
              <div key={k} className="flex gap-2 font-mono text-[11px] leading-5">
                <dt className="w-20 shrink-0 text-muted">{k}</dt>
                <dd className="min-w-0 break-all text-ink">{String(v)}</dd>
              </div>
            ))}
          </dl>
          {tool.notes && tool.notes.length > 0 && (
            <>
              <div className="mt-2 text-[11px] font-medium tracking-[0.08em] text-muted/80">备注</div>
              <ul className="mt-1 space-y-0.5">
                {tool.notes.map((n) => (
                  <li key={n} className="text-[11px] leading-5 text-muted">
                    · {n}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
