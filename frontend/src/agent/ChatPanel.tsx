/**
 * 对话视图：欢迎页 / 消息流 / 输入区，以及工具卡片的推进编排。
 *
 * 推进节奏的处理（这是本档「工具卡片回放」的核心）：
 * - 前 N-1 步按固定节奏点亮（保证演示时看得清）；
 * - 最后一步挂住等 /api/analyze 的真实响应，因此**真实链路慢的时候不会假装跑完**；
 * - 卡片上的结果值在响应到达后回填，全部取自真实 payload；
 * - 汇总行显示的是真实耗时（performance 计时），不是播放时长。
 */
import { useEffect, useRef, useState } from "react";
import { analyze, AnalyzeResp } from "../api";
import {
  buildThinking,
  buildTools,
  fillToolResults,
  ChatMessage,
  DEFAULT_MAX_RESULTS,
  Focus,
  MIN_REPLAY_MS,
  QUICK_STARTS,
  sleep,
  uid,
  type QuickStart,
} from "./model";
import ToolCard from "./ToolCard";

interface Props {
  draft: string;
  setDraft: (v: string) => void;
  /** 结果聚焦维度，由快捷开始入口决定 */
  focus: Focus;
  /** 当前意图标签，显示在输入区上方 */
  intentLabel: string;
  /** 非空时自动执行一次检索；n 递增用于区分相同 query 的重复请求 */
  runRequest: { q: string; n: number } | null;
  /** 递增即清空当前对话 */
  resetToken: number;
  mockMode: boolean | null;
  onResult: (r: AnalyzeResp) => void;
  onOpenReport: (query: string) => void;
  /** 欢迎页能力卡点击，与左侧「快捷开始」走同一条路径 */
  onPick: (q: QuickStart) => void;
}

const CAP_CARDS = ["review", "stats", "cloud", "top100", "search", "design"];

export default function ChatPanel({
  draft,
  setDraft,
  focus,
  intentLabel,
  runRequest,
  resetToken,
  mockMode,
  onResult,
  onOpenReport,
  onPick,
}: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  const lastRun = useRef(-1);
  const lastReset = useRef(0);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // 外部触发的检索（历史会话回放 / 深链）
  useEffect(() => {
    if (runRequest && runRequest.n !== lastRun.current) {
      lastRun.current = runRequest.n;
      void runAgent(runRequest.q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runRequest]);

  // 外部触发的清空（新对话）
  useEffect(() => {
    if (resetToken !== lastReset.current) {
      lastReset.current = resetToken;
      if (!busyRef.current) setMessages([]);
    }
  }, [resetToken]);

  function patchTool(msgId: string, index: number, status: "pending" | "running" | "done" | "error", payload: AnalyzeResp | null) {
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== msgId || !m.tools) return m;
        const tools = m.tools.slice();
        const next = { ...tools[index], status };
        if (status === "done" && payload) {
          const filled = fillToolResults(m.tools, payload)[index];
          next.result = filled.result;
          next.notes = filled.notes;
        }
        tools[index] = next;
        return { ...m, tools };
      }),
    );
  }

  async function runAgent(raw: string) {
    const query = raw.trim();
    if (!query || busyRef.current) return;
    setDraft("");

    const userMsg: ChatMessage = { id: uid(), role: "user", text: query, ts: Date.now() };
    const assistantId = uid();
    const tools = buildTools(query, DEFAULT_MAX_RESULTS);
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      thinking: buildThinking(query, DEFAULT_MAX_RESULTS),
      tools,
      ts: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setBusy(true);
    busyRef.current = true;

    const box: { data: AnalyzeResp | null; err: string; ms: number } = { data: null, err: "", ms: 0 };
    const t0 = performance.now();
    const req = analyze(query, DEFAULT_MAX_RESULTS)
      .then((r) => {
        box.ms = performance.now() - t0;
        if (r.error) box.err = r.error;
        else box.data = r;
      })
      .catch((e: unknown) => {
        box.ms = performance.now() - t0;
        box.err = e instanceof Error ? e.message : "请求失败";
      });

    const stepMs = Math.max(300, Math.round(MIN_REPLAY_MS / tools.length));
    for (let i = 0; i < tools.length; i += 1) {
      patchTool(assistantId, i, "running", box.data);
      await sleep(stepMs);
      if (i < tools.length - 1) {
        patchTool(assistantId, i, "done", box.data);
      } else {
        // 最后一步必须等真实响应，避免「链路还没跑完就显示完成」
        await req;
        patchTool(assistantId, i, box.err ? "error" : "done", box.data);
      }
    }

    // 这里记录的是「接口真实往返耗时」，不含工具卡片的播放时长（避免把动画时长说成链路耗时）
    const elapsedMs = Math.round(box.ms);
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== assistantId) return m;
        if (box.err) return { ...m, error: box.err, elapsedMs };
        if (!box.data) return m;
        return { ...m, tools: fillToolResults(m.tools ?? [], box.data), result: box.data, elapsedMs };
      }),
    );
    setBusy(false);
    busyRef.current = false;
    if (box.data) onResult(box.data);
  }

  const empty = messages.length === 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {empty ? (
          <Welcome onPick={onPick} />
        ) : (
          <div className="mx-auto w-full max-w-3xl space-y-5 px-6 py-6">
            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[78%] rounded-lg rounded-br-sm bg-brand px-4 py-2.5 text-sm leading-6 text-white">
                    {m.text}
                  </div>
                </div>
              ) : (
                <AssistantBubble
                  key={m.id}
                  msg={m}
                  active={busy && m.id === messages[messages.length - 1]?.id}
                  focus={focus}
                  onOpenReport={onOpenReport}
                />
              ),
            )}
          </div>
        )}
      </div>

      <div className="border-t border-line bg-white px-6 py-3">
        <div className="mx-auto w-full max-w-3xl">
          <div className="flex items-center gap-2 pb-2">
            <span className="inline-flex items-center gap-1.5 rounded-md border border-line bg-appbg px-2 py-1 text-[11px] text-muted">
              <span className="h-1.5 w-1.5 rounded-full bg-brand" />
              技能 · 全流程分析
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-md border border-line bg-appbg px-2 py-1 text-[11px] text-muted">
              {mockMode === true ? "示例模式（未配置密钥）" : "qwen · DashScope"}
            </span>
            {intentLabel && (
              <span className="inline-flex items-center gap-1.5 rounded-md border border-brand/30 bg-brand/10 px-2 py-1 text-[11px] text-brand">
                意图 · {intentLabel}
              </span>
            )}
          </div>

          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              rows={draft.length > 56 ? 3 : 1}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void runAgent(draft);
                }
              }}
              placeholder="向 PubMed Agent 提问，或点左侧快捷开始预填关键词，回车发送…"
              className="max-h-40 min-h-[42px] flex-1 resize-none rounded-lg border border-line bg-white px-4 py-3 text-sm leading-6 outline-none transition-colors focus:border-brand"
            />
            <button
              type="button"
              onClick={() => void runAgent(draft)}
              disabled={busy || !draft.trim()}
              className="rounded-lg bg-brand px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-40"
            >
              {busy ? "分析中…" : "发送"}
            </button>
          </div>
          <div className="pt-1.5 text-[11px] text-muted">
            Enter 发送 · Shift+Enter 换行 · 检索与统计走 NCBI E-utilities 与本地期刊指标库，结果可溯源到 PMID
          </div>
        </div>
      </div>
    </div>
  );
}

function Welcome({ onPick }: { onPick: (q: QuickStart) => void }) {
  const cards = CAP_CARDS.map((id) => QUICK_STARTS.find((q) => q.id === id)).filter(
    (q): q is QuickStart => !!q,
  );
  return (
    <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-6 py-10">
      <div className="text-center">
        <div className="mx-auto grid h-14 w-14 place-items-center rounded-lg bg-brand">
          <svg viewBox="0 0 16 16" width="26" height="26" fill="none" stroke="#fff" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 2h5l3 3v9H4V2Zm5 0v3h3M6 9h4M6 11.5h4" />
          </svg>
        </div>
        <h2 className="mt-4 text-xl font-semibold leading-7">你好，我是 PubMed Agent</h2>
        <p className="mt-2 text-sm leading-6 text-muted">
          输入一个关键词，我会跑完「检索 → 指标 → 统计 → 可视化 → 中文综述」整条链路
        </p>
      </div>

      <div className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {cards.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => onPick(c)}
            className="rounded-lg border border-line bg-white p-3.5 text-left transition-colors hover:border-brand"
          >
            <div className="text-[13px] font-medium text-brand">{c.label}</div>
            <div className="mt-1 text-[11px] leading-5 text-muted">{c.desc}</div>
          </button>
        ))}
      </div>

      <div className="mt-6 text-center text-[11px] leading-5 text-muted">
        一键演示关键词 · {QUICK_STARTS.filter((q) => q.keyword).map((q) => q.keyword).join(" · ")}
      </div>
    </div>
  );
}

function AssistantBubble({
  msg,
  active,
  focus,
  onOpenReport,
}: {
  msg: ChatMessage;
  active: boolean;
  focus: Focus;
  onOpenReport: (q: string) => void;
}) {
  const [manual, setManual] = useState<boolean | null>(null);
  const open = manual ?? active;

  return (
    <div className="flex gap-3">
      <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md bg-brand/10 text-[11px] font-medium text-brand">
        AI
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        {msg.thinking && msg.thinking.length > 0 && (
          <div className="rounded-md border border-line bg-appbg">
            <button
              type="button"
              onClick={() => setManual(!open)}
              className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[11px] text-muted transition-colors hover:text-ink"
            >
              <svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={open ? "rotate-90 transition-transform" : "transition-transform"}>
                <path d="M6 3.5L10.5 8 6 12.5" />
              </svg>
              思考过程
              {active && <span className="ml-1 text-brand">进行中</span>}
            </button>
            {open && (
              <ul className="space-y-1 px-3 pb-2.5">
                {msg.thinking.map((t) => (
                  <li key={t} className="text-[11px] leading-5 text-muted">
                    · {t}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {msg.tools && msg.tools.length > 0 && <div className="space-y-1.5">
          {msg.tools.map((t) => (
            <ToolCard key={t.id} tool={t} />
          ))}
        </div>}

        {msg.error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
            执行失败：{msg.error}
          </div>
        )}

        {msg.result && (
          <ResultBlock result={msg.result} focus={focus} elapsedMs={msg.elapsedMs} onOpenReport={onOpenReport} />
        )}
      </div>
    </div>
  );
}

function ResultBlock({
  result,
  focus,
  elapsedMs,
  onOpenReport,
}: {
  result: AnalyzeResp;
  focus: Focus;
  elapsedMs?: number;
  onOpenReport: (q: string) => void;
}) {
  const [expandReview, setExpandReview] = useState(false);
  const ifs = result.stats.if_statistics;
  const coverage = result.returned > 0 ? Math.round((ifs.known_count / result.returned) * 100) : 0;
  const topJournal = (result.stats.top100 ?? []).find((x) => x.impact_factor) ?? null;

  const statsBlock = (
    <div key="stats" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <Mini label="命中总量" value={result.total.toLocaleString()} />
      <Mini label="IF 覆盖" value={`${coverage}%`} sub={`${ifs.known_count} / ${result.returned} 篇`} />
      <Mini label="平均 IF" value={ifs.mean != null ? String(ifs.mean) : "—"} sub={ifs.median != null ? `中位 ${ifs.median}` : undefined} />
      <Mini label="最高 IF" value={topJournal?.impact_factor != null ? String(topJournal.impact_factor) : "—"} sub={topJournal?.journal} />
    </div>
  );

  const cloudBlock = (
    <div key="cloud" className="rounded-md border border-line bg-white p-3">
      <div className="text-[11px] font-medium text-muted">研究方向（按 MeSH 词频聚类，未调用大模型）</div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {(result.stats.topics ?? []).slice(0, 8).map((t) => (
          <span key={t.topic} className="inline-flex items-center gap-1 rounded-full bg-brand/10 px-2.5 py-1 text-[11px] text-brand">
            {t.topic} <span className="text-brand/60">×{t.count}</span>
          </span>
        ))}
        {(result.stats.topics ?? []).length === 0 && <span className="text-[11px] text-muted">暂无足够 MeSH 数据</span>}
      </div>
    </div>
  );

  const topBlock = (
    <div key="top100" className="rounded-md border border-line bg-white">
      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-[11px] font-medium text-muted">影响力 Top 5（共 {result.stats.top100.length} 条）</span>
        <button type="button" onClick={() => onOpenReport(result.query)} className="text-[11px] text-brand hover:underline">
          查看完整报告
        </button>
      </div>
      <div className="border-t border-line">
        {(result.stats.top100 ?? []).slice(0, 5).map((r, i) => (
          <div key={r.pmid} className="flex items-start gap-2 border-b border-line px-3 py-2 last:border-b-0">
            <span className="w-4 shrink-0 text-[11px] text-muted">{i + 1}</span>
            <a href={r.url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-[12px] leading-5 hover:text-brand">
              {r.title}
            </a>
            <span className="shrink-0 text-[11px] text-muted">{r.journal}</span>
            <span className="w-14 shrink-0 text-right text-[11px] font-medium">{r.impact_factor ?? "—"}</span>
          </div>
        ))}
      </div>
    </div>
  );

  const text = result.review?.text ?? "";
  const reviewBlock = (
    <div key="review" className="rounded-md border border-line bg-white p-3">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-medium text-muted">中文综述</span>
        {result.review?.mock && <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">统计兜底</span>}
        <span className="text-[10px] text-muted">· {text.length} 字 · {result.review?.sources.length ?? 0} 处 PMID 出处</span>
      </div>
      <div className="mt-1.5 whitespace-pre-wrap text-[12px] leading-6 text-ink">
        {expandReview ? text : text.slice(0, 240) + (text.length > 240 ? "…" : "")}
      </div>
      <div className="mt-2 flex items-center gap-3">
        {text.length > 240 && (
          <button type="button" onClick={() => setExpandReview((v) => !v)} className="text-[11px] text-brand hover:underline">
            {expandReview ? "收起" : "展开全文"}
          </button>
        )}
        <button type="button" onClick={() => onOpenReport(result.query)} className="text-[11px] text-muted hover:text-brand">
          含全部出处 →
        </button>
      </div>
    </div>
  );

  const order: Record<Focus, string[]> = {
    all: ["stats", "cloud", "top100", "review"],
    stats: ["stats", "cloud", "top100", "review"],
    cloud: ["cloud", "stats", "top100", "review"],
    top100: ["top100", "stats", "cloud", "review"],
    review: ["review", "stats", "cloud", "top100"],
  };
  const blocks: Record<string, JSX.Element> = { stats: statsBlock, cloud: cloudBlock, top100: topBlock, review: reviewBlock };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted">
        <span>
          检索 “<span className="text-ink">{result.query}</span>” · 命中 <span className="text-ink">{result.total.toLocaleString()}</span> 篇 · 本次分析 {result.returned} 篇
        </span>
        {elapsedMs != null && <span>· 链路耗时 {elapsedMs} ms</span>}
      </div>
      {order[focus].map((k) => blocks[k])}
    </div>
  );
}

function Mini({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-md border border-line bg-white px-3 py-2">
      <div className="text-[11px] text-muted">{label}</div>
      <div className="mt-0.5 text-base font-semibold leading-6">{value}</div>
      {sub && <div className="truncate text-[10px] text-muted">{sub}</div>}
    </div>
  );
}
