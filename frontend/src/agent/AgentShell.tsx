/**
 * 三栏外壳：左侧导航 + 主区（智能对话 / 智能报告）。
 *
 * 导航只保留侧栏一条路径：原先顶栏那排 tab 与侧栏功能完全重合，已按用户要求删除；
 * 「设计思考」页同步下线。顶栏现在只放运行状态（后端连接、模型）。
 */
import { useEffect, useRef, useState } from "react";
import { AnalyzeResp } from "../api";
import ReportView from "../ReportView";
import AdminPanel from "../AdminPanel";
import Sidebar from "./Sidebar";
import ChatPanel from "./ChatPanel";
import { logout as authLogout, fetchTrial, type AuthUser, type TrialQuota } from "../apiBase";
import {
  clearSessions,
  deleteSession,
  fetchReport,
  fetchSessionMessages,
  loadSessions,
  reportMetaOf,
  saveExchange,
  saveReport,
  Session,
  ChatMessage,
  ReportMeta,
} from "./model";
import { API_BASE as BASE } from "../apiBase";

type Tab = "chat" | "report";

/** 从侧栏打开的历史报告（整份快照直接渲染，不再请求分析） */
interface ReportSnapshot {
  id?: string;
  title: string;
  query: string;
  doc: AnalyzeResp;
  meta: ReportMeta;
  chatId: string | null;
  /** 来源对话标题（有 chatId 时用于「来自对话：xxx →」） */
  chatTitle?: string;
  /** 快照生成时间（ISO），页面上标注，避免被误读为实时数据 */
  savedAt: string;
}

export default function AgentShell({ user }: { user?: AuthUser | null }) {
  const [tab, setTab] = useState<Tab>("chat");
  const [draft, setDraft] = useState("");
  const [intentLabel, setIntentLabel] = useState("");
  const [activeKeyword, setActiveKeyword] = useState("");
  // 历史会话已迁到服务端持久化（sessions.db）：挂载后异步拉取，拉不到就空列表
  const [sessions, setSessions] = useState<Session[]>([]);
  const [mockMode, setMockMode] = useState<boolean | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [injectQuery, setInjectQuery] = useState("");
  /** 从侧栏打开的整份历史报告快照（非空时报告页直接渲染它，不发分析请求） */
  const [reportSnapshot, setReportSnapshot] = useState<ReportSnapshot | null>(null);
  const [runRequest, setRunRequest] = useState<{ q: string; n: number } | null>(null);
  /** 非空时整条还原历史线程消息（不重新检索、不播动画） */
  const [restoreRequest, setRestoreRequest] = useState<{ messages: ChatMessage[]; n: number } | null>(null);
  /** 管理后台覆盖层（仅 admin 可开；独立覆盖层，不侵入对话/报告两视图） */
  const [adminOpen, setAdminOpen] = useState(false);
  /** 当前对话线程 id：null = 新线程（下一问创建），非空 = 追问挂到这个线程（同线程连问不分家）。
   *  纯 ref 即可：id 不参与渲染，只需在异步保存回调里取到最新值。 */
  const activeSessionRef = useRef<string | null>(null);
  const setActiveSession = (id: string | null) => {
    activeSessionRef.current = id;
  };
  /** 侧栏高亮用：当前正在看的那条记录（对话或报告）的 id */
  const [activeRecordId, setActiveRecordId] = useState<string | null>(null);
  const [resetToken, setResetToken] = useState(0);
  /** 报告页清空信号：侧栏「智能报告」= 新建一份报告（对齐「新对话」），递增让报告页回到起始页 */
  const [reportClearToken, setReportClearToken] = useState(0);
  /** 免费试用额度（服务器版每账号限次；null = 未启用或管理员豁免，不显示任何提示）。
   *  数值只从后端取——前端不做本地推算，避免"显示的剩余次数"与真实可用的不一致。 */
  const [trial, setTrial] = useState<TrialQuota | null>(null);
  const refreshTrial = () => {
    void fetchTrial().then((t) => setTrial(t?.quota ?? null));
  };
  const runSeq = useRef(0);

  useEffect(() => {
    fetch(`${BASE}/api/health`, { credentials: "include" })
      .then((r) => setConnected(r.ok))
      .catch(() => setConnected(false));
  }, []);

  useEffect(() => {
    void loadSessions().then(setSessions);
    void fetchTrial().then((t) => setTrial(t?.quota ?? null));
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
      setIntentLabel("深链");
      runSeq.current += 1;
      setRunRequest({ q: chat, n: runSeq.current });
      setTab("chat");
      return;
    }
    if (t === "report" || t === "chat") setTab(t);
  }, []);

  function openReport(query: string) {
    setReportSnapshot(null); // 主动查询 = 重新跑，不用历史快照
    setActiveRecordId(null); // 等这次分析存成报告后再高亮
    setInjectQuery(query);
    setTab("report");
  }

  /**
   * 侧栏主入口导航。「智能报告」= **新建一份报告**（语义对齐「新对话」）：
   * 清掉当前报告回到起始页，旧报告已在历史会话里、随时可点回。
   * 「智能对话」则保留当前对话内容（只切视图）。
   */
  function handleNavigate(tab: Tab) {
    if (tab === "report") {
      setReportSnapshot(null);
      setActiveRecordId(null);
      setInjectQuery("");
      setReportClearToken((v) => v + 1);
    }
    refreshTrial(); // 切视图时顺带对一次额度（报告页自己也消耗次数，回到对话页时数字要准）
    setTab(tab);
  }

  /** 报告页「来源对话 →」：跳回产生这份报告的对话线程 */
  function handleNavigateToChat(chatId: string) {
    const s = sessions.find((x) => x.id === chatId);
    if (s) {
      handleOpenSession(s);
      return;
    }
    // 列表里没有（已被挤掉/删除）：退回对话页并说明，不假装还能打开
    setTab("chat");
  }

  function handleOpenSession(s: Session) {
    // 报告：拉整份快照 → 切报告页直接渲染（离线可看，不依赖缓存与分析请求）
    if (s.kind === "report") {
      setActiveKeyword(s.query ?? s.title);
      setActiveSession(null); // 报告不是对话线程，不参与对话追加
      setActiveRecordId(s.id); // 侧栏高亮这条报告
      runSeq.current += 1;
      void fetchReport(s.id).then((rep) => {
        if (!rep) {
          setInjectQuery(s.query ?? s.title);
          setReportSnapshot(null);
          setTab("report");
          return;
        }
        if (!rep.doc) return;
        setMockMode(!!rep.doc.review?.mock);
        setReportSnapshot({
          id: rep.id,
          title: rep.title,
          query: rep.query,
          doc: rep.doc,
          meta: rep.meta,
          chatId: rep.chatId,
          chatTitle: rep.chatId ? sessions.find((x) => x.id === rep.chatId)?.title ?? "" : undefined,
          savedAt: rep.savedAt,
        });
        setTab("report");
      });
      return;
    }

    // 对话：还原整条线程，并把当前上下文切到它（之后的追问追加到该线程）
    setTab("chat");
    setActiveKeyword(s.title);
    setIntentLabel("历史会话");
    setReportSnapshot(null);
    setActiveSession(s.id);
    setActiveRecordId(s.id); // 侧栏高亮这条对话
    runSeq.current += 1;
    void fetchSessionMessages(s.id).then((messages) => {
      if (messages) {
        const lastResult = [...messages].reverse().find((m) => m.result)?.result;
        if (lastResult) setMockMode(!!lastResult.review?.mock);
        setRestoreRequest({ messages, n: runSeq.current });
      } else {
        // 线程空/拉取失败：退回重新检索该线程标题词
        setRunRequest({ q: s.title, n: runSeq.current });
      }
    });
  }

  /**
   * 由对话结果「生成报告」：写入/复用一条从属报告（chat_id=当前线程 + 全量快照），
   * 然后切到报告页用这份快照渲染。复用键 (chatId, query)，重复点不会堆重复。
   * 标题用 askText（用户原话）——不能把用户的问题替换成提取出的关键词。
   */
  function handleGenerateReport(doc: AnalyzeResp, elapsedMs?: number, askText?: string) {
    const chatId = activeSessionRef.current;
    const chatTitle = sessions.find((x) => x.id === chatId)?.title ?? "";
    const title = (askText || "").trim() || doc.query;
    // 先用本地快照把页面点亮（用户零等待），落库在后台完成
    setReportSnapshot({
      title,
      query: doc.query,
      doc,
      meta: reportMetaOf(doc, elapsedMs),
      chatId,
      chatTitle: chatId ? chatTitle : undefined,
      savedAt: new Date().toISOString(),
    });
    setInjectQuery("");
    setTab("report");
    void saveReport(doc.query, doc, reportMetaOf(doc, elapsedMs), chatId, title).then((row) => {
      if (!row) return;
      setReportSnapshot((prev) => (prev ? { ...prev, id: row.id, chatId: row.chatId ?? null } : prev));
      setActiveRecordId(row.id); // 生成的报告成为"当前记录"，侧栏高亮它
      setSessions((prev) => {
        const exists = prev.some((s) => s.id === row.id);
        return exists ? prev.map((s) => (s.id === row.id ? row : s)) : [row, ...prev].slice(0, 24);
      });
    });
  }

  /** 报告页自己检索产生的独立报告：侧栏即时出现并高亮（此前要刷新页面才看得到） */
  function handleReportSaved(row: Session) {
    refreshTrial(); // 报告页的分析同样计次
    setSessions((prev) => {
      const exists = prev.some((s) => s.id === row.id);
      return exists ? prev.map((s) => (s.id === row.id ? row : s)) : [row, ...prev].slice(0, 24);
    });
    setActiveRecordId(row.id);
  }

  /** 删单条记录：对话删掉后其报告保留（服务端只把 chat_id 置空，变成独立报告） */
  function handleDeleteSession(id: string) {
    void deleteSession(id).then((ok) => {
      if (!ok) return;
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeSessionRef.current === id) {
        setActiveSession(null);
        setResetToken((v) => v + 1);
      }
      setActiveRecordId((prev) => (prev === id ? null : prev));
      setReportSnapshot((prev) => (prev?.id === id ? null : prev));
    });
  }

  function handleNewChat() {
    setResetToken((v) => v + 1);
    setDraft("");
    setIntentLabel("");
    setActiveKeyword("");
    setActiveSession(null); // 新对话 = 脱离当前线程，下一问创建新线程
    setActiveRecordId(null); // 没有任何历史记录处于"正在看"状态
    setTab("chat");
  }

  function handleResult(r: AnalyzeResp, elapsedMs?: number, askText?: string) {
    setMockMode(!!r.review?.mock);
    setActiveKeyword(r.query);
    refreshTrial(); // 一次分析 = 一次额度消耗，完成后向后端要最新剩余次数
    // 线程化持久化：有当前线程 → 追加这一轮；没有 → 新建线程。
    // 新建时标题用**用户原话**（检索仍用关键词）——避免"我的提问被改写成关键词"的观感。
    void saveExchange(activeSessionRef.current, r.query, r, elapsedMs, askText).then((row) => {
      if (!row) return;
      if (!activeSessionRef.current) setActiveSession(row.id);
      setActiveRecordId(row.id); // 新线程/当前线程在侧栏高亮
      setSessions((prev) => {
        const exists = prev.some((s) => s.id === row.id);
        return exists
          ? prev.map((s) => (s.id === row.id ? row : s))
          : [row, ...prev].slice(0, 12);
      });
    });
  }

  return (
    <div className="flex h-screen min-h-0 bg-appbg">
      <Sidebar
        sessions={sessions}
        activeTab={tab}
        activeId={activeRecordId}
        mockMode={mockMode}
        onNewChat={handleNewChat}
        onNavigate={handleNavigate}
        onOpenSession={handleOpenSession}
        onDeleteSession={handleDeleteSession}
        onClearSessions={() => void clearSessions().then(setSessions)}
        onOpenReport={() => openReport(activeKeyword)}
        user={user}
        onLogout={() => void authLogout().then(() => window.location.reload())}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* 顶栏只放运行状态与管理入口：用户名/退出已于 2026-09-20 挪到侧栏底部
            （视图切换统一由侧栏承担，顶栏 tab 曾与侧栏重合，已删） */}
        <header className="flex h-12 shrink-0 items-center justify-end gap-2 border-b border-line bg-white px-5">
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

          {/* 免费试用额度（服务器版每账号限次；未启用或管理员豁免时不显示） */}
          {trial && (
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ${
                trial.remaining > 0
                  ? "border-line bg-appbg text-muted"
                  : "border-red-200 bg-red-50 font-medium text-red-600"
              }`}
              title={`免费试用额度：已用 ${trial.used} / ${trial.limit} 次`}
            >
              {trial.remaining > 0 ? `免费试用剩余 ${trial.remaining} 次` : "免费试用已用尽"}
            </span>
          )}

          {/* 管理入口（仅 admin）：用户身份与退出登录在侧栏底部 */}
          {user?.role === "admin" && (
            <button
              onClick={() => setAdminOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-2.5 py-1 text-[11px] text-ink transition-all hover:bg-appbg"
            >
              管理后台
            </button>
          )}
        </header>

        {/* 试用额度用尽提示（含管理员联系方式）：置顶显示，避免用户反复点分析却只看到失败 */}
        {trial && trial.remaining === 0 && (
          <div className="shrink-0 border-b border-amber-200 bg-amber-50 px-5 py-2.5 text-[12px] leading-5 text-amber-800">
            <span className="font-medium">
              免费试用次数已用完（共 {trial.limit} 次），请与管理员联系开通
            </span>
            {trial.contact ? `：${trial.contact}` : ""}
          </div>
        )}

        <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {/* 两个视图常驻挂载、只切换可见性：切走再切回不丢会话与报告状态，
              也不会因组件重挂而重放 runRequest（实测反馈：切个视图就整链重跑） */}
          <div className={tab === "chat" ? "flex min-h-0 flex-1 flex-col" : "hidden"}>
            <ChatPanel
              draft={draft}
              setDraft={setDraft}
              focus="all"
              intentLabel={intentLabel}
              runRequest={runRequest}
              restoreRequest={restoreRequest}
              resetToken={resetToken}
              mockMode={mockMode}
              onResult={handleResult}
              onGenerateReport={handleGenerateReport}
            />
          </div>

          <div
            className={
              tab === "report" ? "flex min-h-0 flex-1 flex-col overflow-y-auto" : "hidden"
            }
          >
            <ReportView
              injectQuery={injectQuery}
              onQueryInjected={() => setInjectQuery("")}
              injectSnapshot={reportSnapshot}
              onNavigateToChat={handleNavigateToChat}
              onReportSaved={handleReportSaved}
              clearToken={reportClearToken}
            />
          </div>
        </main>
      </div>

      {/* 管理后台覆盖层：admin 独享；关闭即回到原视图（对话/报告状态不受影响） */}
      {adminOpen && user?.role === "admin" && (
        <AdminPanel user={user} onClose={() => setAdminOpen(false)} />
      )}
    </div>
  );
}
