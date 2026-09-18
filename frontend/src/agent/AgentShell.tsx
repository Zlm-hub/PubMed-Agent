/**
 * 三栏外壳：左侧导航 + 顶部视图切换 + 主区。
 *
 * 视图切换沿用参考产品的「对话 / 文档」思路，但这里拆成三个：
 * 对话（Agent 交互）/ 报告（原 F1–F4 完整报告，逻辑零改动）/ 设计思考（原有页）。
 * 升级只新增了外壳，原有报告与设计思考页的行为完全保留。
 */
import { useEffect, useRef, useState } from "react";
import { AnalyzeResp } from "../api";
import ReportView from "../ReportView";
import Thinking from "../Thinking";
import Sidebar, { Icon } from "./Sidebar";
import ChatPanel from "./ChatPanel";
import { clearSessions, Focus, loadSessions, QuickStart, saveSession, Session } from "./model";

const BASE = "http://localhost:8000";

type Tab = "chat" | "report" | "design";

/** 输入框已有内容时，点击「快捷开始」不直接覆盖，而是挂起等用户确认 */
type PendingSwap = { keyword: string; label: string; focus: Focus };

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "chat", label: "对话", icon: "chat" },
  { id: "report", label: "报告", icon: "doc" },
  { id: "design", label: "设计思考", icon: "design" },
];

export default function AgentShell() {
  const [tab, setTab] = useState<Tab>("chat");
  const [draft, setDraft] = useState("");
  const [focus, setFocus] = useState<Focus>("all");
  const [intentLabel, setIntentLabel] = useState("");
  const [activeKeyword, setActiveKeyword] = useState("");
  const [sessions, setSessions] = useState<Session[]>(() => loadSessions());
  const [mockMode, setMockMode] = useState<boolean | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [injectQuery, setInjectQuery] = useState("");
  const [runRequest, setRunRequest] = useState<{ q: string; n: number } | null>(null);
  const [resetToken, setResetToken] = useState(0);
  const [pendingSwap, setPendingSwap] = useState<PendingSwap | null>(null);
  /** 最近一次由「快捷开始」填入的预设词，用于在输入区给出明确提示 */
  const [filledFrom, setFilledFrom] = useState("");
  const runSeq = useRef(0);

  // 用户一旦改动输入框，就不再是「预设词待发送」状态
  useEffect(() => {
    if (filledFrom && draft !== filledFrom) setFilledFrom("");
  }, [draft, filledFrom]);

  useEffect(() => {
    fetch(`${BASE}/api/health`)
      .then((r) => setConnected(r.ok))
      .catch(() => setConnected(false));
  }, []);

  // 深链兼容：/?q=Alzheimer 仍直接进报告页（升级前的既有行为，不能丢）
  //            /?chat=Alzheimer 直接进对话页并自动跑一次，便于现场演示与截图
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const q = (params.get("q") ?? "").trim();
    const chat = (params.get("chat") ?? "").trim();
    const t = params.get("tab");
    if (q) {
      setInjectQuery(q);
      setActiveKeyword(q);
      setTab("report");
      return;
    }
    if (chat) {
      setActiveKeyword(chat);
      setFocus("all");
      setIntentLabel("深链");
      runSeq.current += 1;
      setRunRequest({ q: chat, n: runSeq.current });
      setTab("chat");
      return;
    }
    if (t === "report" || t === "design" || t === "chat") setTab(t);
  }, []);

  function openReport(query: string) {
    setInjectQuery(query);
    setTab("report");
  }

  /** 确认应用一个快捷开始项：切对话页 + 填预设词 + 设定聚焦维度 */
  function applyQuickStart(q: PendingSwap) {
    setTab("chat");
    setActiveKeyword(q.keyword);
    setFocus(q.focus);
    setIntentLabel(q.label);
    setDraft(q.keyword);
    setFilledFrom(q.keyword);
    setPendingSwap(null);
  }

  function handleQuickStart(q: QuickStart) {
    if (q.planned) return;
    if (!q.keyword) {
      setTab("design");
      return;
    }
    // 输入框里有用户自己敲的内容时，不静默覆盖，挂起等确认
    const current = draft.trim();
    if (current && current !== q.keyword) {
      setTab("chat");
      setPendingSwap({ keyword: q.keyword, label: q.label, focus: q.focus });
      return;
    }
    applyQuickStart({ keyword: q.keyword, label: q.label, focus: q.focus });
  }

  function handleOpenSession(s: Session) {
    setTab("chat");
    setActiveKeyword(s.query);
    setFocus("all");
    setIntentLabel("历史会话");
    setPendingSwap(null);
    setFilledFrom("");
    runSeq.current += 1;
    setRunRequest({ q: s.query, n: runSeq.current });
  }

  function handleNewChat() {
    setResetToken((v) => v + 1);
    setDraft("");
    setIntentLabel("");
    setFocus("all");
    setActiveKeyword("");
    setPendingSwap(null);
    setFilledFrom("");
    setTab("chat");
  }

  function handleResult(r: AnalyzeResp) {
    setMockMode(!!r.review?.mock);
    setActiveKeyword(r.query);
    setSessions((prev) => saveSession(prev, r.query));
  }

  return (
    <div className="flex h-screen min-h-0 bg-appbg">
      <Sidebar
        sessions={sessions}
        activeKeyword={activeKeyword}
        mockMode={mockMode}
        onNewChat={handleNewChat}
        onQuickStart={handleQuickStart}
        onOpenSession={handleOpenSession}
        onClearSessions={() => setSessions(clearSessions())}
        onOpenReport={() => openReport(activeKeyword)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-line bg-white px-5">
          <nav className="flex items-center gap-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] transition-colors ${
                  tab === t.id ? "bg-brand/10 font-medium text-brand" : "text-muted hover:bg-appbg hover:text-ink"
                }`}
              >
                <Icon name={t.icon} />
                {t.label}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-2">
            <span className="hidden items-center gap-1.5 rounded-full border border-line bg-appbg px-2.5 py-1 text-[11px] text-muted sm:inline-flex">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  connected === null ? "bg-muted" : connected ? "bg-emerald-500" : "bg-accent"
                }`}
              />
              {connected === null ? "检测中" : connected ? "已连接" : "后端未响应"}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-appbg px-2.5 py-1 text-[11px] text-muted">
              {mockMode === true ? "示例模式" : "qwen · DashScope"}
            </span>
          </div>
        </header>

        <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {tab === "chat" && (
            <ChatPanel
              draft={draft}
              setDraft={setDraft}
              focus={focus}
              intentLabel={intentLabel}
              runRequest={runRequest}
              resetToken={resetToken}
              mockMode={mockMode}
              filledFrom={filledFrom}
              pendingSwap={
                pendingSwap ? { keyword: pendingSwap.keyword, label: pendingSwap.label } : null
              }
              onAcceptSwap={() => pendingSwap && applyQuickStart(pendingSwap)}
              onDismissSwap={() => setPendingSwap(null)}
              onResult={handleResult}
              onOpenReport={openReport}
              onPick={handleQuickStart}
            />
          )}

          {tab === "report" && (
            <div className="min-h-0 flex-1 overflow-y-auto">
              <ReportView injectQuery={injectQuery} onQueryInjected={() => setInjectQuery("")} />
            </div>
          )}

          {tab === "design" && (
            <div className="min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-5xl px-6 py-8">
                <Thinking />
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
