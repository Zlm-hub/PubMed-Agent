/**
 * 管理后台面板（自包含，2026-09-20 用户/管理员功能配套）。
 *
 * 仅 role=admin 可见入口；以全屏覆盖层呈现，不侵入三栏外壳（对话/报告零改动）。
 * 两个页签：
 *  用户管理 —— 建号 / 重置密码 / 禁用启用 / 删除（含自我保护与最后管理员保护，
 *             服务端同样校验，这里只是把错误如实显示）
 *  全部会话 —— 按用户过滤查看/删除任意会话与报告（管理权限，诚实口径）
 */
import { useEffect, useState } from "react";
import { fetchTrial, type AuthUser } from "./apiBase";
import {
  AdminUserRow,
  createUser,
  deleteAnySession,
  deleteUser,
  fetchAllSessions,
  fetchOverview,
  fetchUsers,
  patchUser,
} from "./admin";
import type { Session } from "./agent/model";

type Tab = "users" | "sessions";

const btn =
  "rounded-lg px-3 py-1.5 text-xs font-medium transition-all disabled:opacity-50 disabled:shadow-none";
const btnGhost = `${btn} border border-line bg-white text-ink hover:bg-appbg`;
const btnBrand = `${btn} bg-brand hover:bg-brand-hover text-white shadow-card`;
const input =
  "w-full rounded-lg border border-line bg-white px-3 py-2 text-sm outline-none transition-all focus:border-brand focus:ring-2 focus:ring-brand/15";

function fmtTs(v: string | null): string {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString("zh-CN", { hour12: false });
}

export default function AdminPanel({ user, onClose }: { user: AuthUser; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("users");
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [overview, setOverview] = useState<{ users: number; chats: number; reports: number } | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [userFilter, setUserFilter] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  // 新建用户表单
  const [nuName, setNuName] = useState("");
  const [nuPass, setNuPass] = useState("");
  const [nuRole, setNuRole] = useState<"user" | "admin">("user");
  const [nuDisplay, setNuDisplay] = useState("");
  const [nuErr, setNuErr] = useState("");
  /** 试用额度是否启用（服务器版才有）——决定用户表是否显示「试用」列与重置按钮 */
  const [trialLimit, setTrialLimit] = useState(0);

  async function reload() {
    setBusy(true);
    const [ov, us] = await Promise.all([fetchOverview(), fetchUsers()]);
    setOverview(ov);
    setUsers(us);
    setSessions(await fetchAllSessions(userFilter || undefined));
    setBusy(false);
  }

  useEffect(() => {
    void reload();
    void fetchTrial().then((t) => setTrialLimit(t?.enabled ? (t.limit ?? 0) : 0));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userFilter]);

  function flash(msg: string) {
    setNotice(msg);
    window.setTimeout(() => setNotice(""), 3200);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setNuErr("");
    const res = await createUser(nuName.trim(), nuPass, nuRole, nuDisplay.trim() || undefined);
    if (!res.ok) {
      setNuErr(res.error ?? "创建失败");
      return;
    }
    setNuName("");
    setNuPass("");
    setNuDisplay("");
    flash(`已创建用户 ${nuName.trim()}`);
    void reload();
  }

  async function handleResetPassword(u: AdminUserRow) {
    const pw = window.prompt(`为 ${u.username} 设置新密码（6~64 位）：`);
    if (pw === null) return;
    const res = await patchUser(u.id, { password: pw });
    flash(res.ok ? `已重置 ${u.username} 的密码` : (res.error ?? "重置失败"));
  }

  /** 试用额度清零（客户联系后「再给 N 次」就点这个） */
  async function handleResetTrial(u: AdminUserRow) {
    if (!window.confirm(`把「${u.username}」的免费试用次数清零（可再用 ${trialLimit} 次）？`)) return;
    const res = await patchUser(u.id, { reset_trial: true });
    flash(res.ok ? `已为 ${u.username} 重置试用次数` : (res.error ?? "重置失败"));
    void reload();
  }

  async function handleToggleDisabled(u: AdminUserRow) {
    const res = await patchUser(u.id, { disabled: !u.disabled });
    if (!res.ok) flash(res.error ?? "操作失败");
    void reload();
  }

  async function handleDeleteUser(u: AdminUserRow) {
    if (!window.confirm(`确认删除用户「${u.username}」？其名下 ${u.chats + u.reports} 条会话将转给你保留。`)) return;
    const res = await deleteUser(u.id);
    flash(res.ok ? `已删除 ${u.username}` : (res.error ?? "删除失败"));
    void reload();
  }

  async function handleDeleteSession(s: Session) {
    if (!window.confirm(`确认删除「${s.title}」？`)) return;
    if (await deleteAnySession(s.id)) {
      setSessions((prev) => prev.filter((x) => x.id !== s.id));
      void reload();
    }
  }

  const nameOf = (id: string | null | undefined) =>
    users.find((u) => u.id === id)?.username ?? (id ? "（已删除）" : "—");

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-appbg">
      {/* 顶栏 */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-line bg-white px-5">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-ink">管理后台</span>
          <span className="text-xs text-muted">以 {user.username} 身份管理</span>
        </div>
        <button onClick={onClose} className={btnGhost}>
          关闭
        </button>
      </header>

      {/* 页签 */}
      <div className="flex shrink-0 items-center gap-2 border-b border-line bg-white px-5 py-2">
        {(
          [
            ["users", `用户管理${overview ? `（${overview.users}）` : ""}`],
            ["sessions", "全部会话"],
          ] as [Tab, string][]
        ).map(([id, label]) => (
          <button
            key={id}
            onClick={() => {
              setTab(id);
              if (id === "sessions") void fetchAllSessions(userFilter || undefined).then(setSessions);
            }}
            className={`${btn} ${tab === id ? "bg-brand text-white shadow-card" : "border border-line bg-white text-muted hover:bg-appbg"}`}
          >
            {label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 text-xs text-muted">
          {overview && (
            <span>
              用户 {overview.users} · 对话 {overview.chats} · 报告 {overview.reports}
            </span>
          )}
          <button onClick={() => void reload()} disabled={busy} className={btnGhost}>
            {busy ? "刷新中…" : "刷新"}
          </button>
        </div>
      </div>

      {notice && (
        <div className="shrink-0 border-b border-line bg-emerald-50 px-5 py-2 text-xs text-emerald-700">
          {notice}
        </div>
      )}

      <main className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {tab === "users" ? (
          <div className="mx-auto flex max-w-4xl flex-col gap-4">
            {/* 新建用户 */}
            <form onSubmit={handleCreate} className="rounded-xl border border-line bg-white p-4 shadow-card">
              <div className="text-sm font-medium text-ink">新建用户</div>
              <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_1fr_120px_1fr_auto]">
                <input className={input} placeholder="用户名（2~32 位）" value={nuName} onChange={(e) => { setNuName(e.target.value); setNuErr(""); }} />
                <input className={input} placeholder="密码（6~64 位）" type="text" value={nuPass} onChange={(e) => { setNuPass(e.target.value); setNuErr(""); }} />
                <select className={input} value={nuRole} onChange={(e) => setNuRole(e.target.value as "user" | "admin")}>
                  <option value="user">普通用户</option>
                  <option value="admin">管理员</option>
                </select>
                <input className={input} placeholder="显示名（可选）" value={nuDisplay} onChange={(e) => setNuDisplay(e.target.value)} />
                <button type="submit" disabled={!nuName.trim() || !nuPass} className={btnBrand}>
                  创建
                </button>
              </div>
              {nuErr && <div className="mt-2 text-xs text-red-600">{nuErr}</div>}
            </form>

            {/* 用户表 */}
            <div className="overflow-hidden rounded-xl border border-line bg-white shadow-card">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-line bg-appbg text-xs text-muted">
                    <th className="px-4 py-2.5 font-normal">用户名</th>
                    <th className="px-4 py-2.5 font-normal">角色</th>
                    <th className="px-4 py-2.5 font-normal">对话</th>
                    <th className="px-4 py-2.5 font-normal">报告</th>
                    {trialLimit > 0 && <th className="px-4 py-2.5 font-normal">试用</th>}
                    <th className="px-4 py-2.5 font-normal">最近登录</th>
                    <th className="px-4 py-2.5 font-normal">状态</th>
                    <th className="px-4 py-2.5 font-normal">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id} className="border-b border-line last:border-0">
                      <td className="px-4 py-2.5">
                        <div className="font-medium text-ink">{u.username}</div>
                        {u.display_name && <div className="text-xs text-muted">{u.display_name}</div>}
                      </td>
                      <td className="px-4 py-2.5">
                        <span
                          className={`rounded-full px-2 py-0.5 text-xs ${
                            u.role === "admin" ? "bg-purple-100 text-purple-700" : "bg-appbg text-muted"
                          }`}
                        >
                          {u.role === "admin" ? "管理员" : u.role === "user" ? "用户" : "—"}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-muted">{u.chats}</td>
                      <td className="px-4 py-2.5 text-muted">{u.reports}</td>
                      {trialLimit > 0 && (
                        <td className="px-4 py-2.5">
                          <span
                            className={`text-xs ${
                              (u.trial_used ?? 0) >= trialLimit ? "font-medium text-red-600" : "text-muted"
                            }`}
                          >
                            {u.role === "admin" ? "豁免" : `${u.trial_used ?? 0} / ${trialLimit}`}
                          </span>
                        </td>
                      )}
                      <td className="px-4 py-2.5 text-xs text-muted">{fmtTs(u.last_login_at)}</td>
                      <td className="px-4 py-2.5">
                        <span className={`text-xs ${u.disabled ? "text-red-600" : "text-emerald-600"}`}>
                          {u.disabled ? "已禁用" : "正常"}
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        {u.id !== "_orphan" && (
                          <div className="flex flex-wrap gap-1.5">
                            <button onClick={() => void handleResetPassword(u)} className={btnGhost}>
                              重置密码
                            </button>
                            <button onClick={() => void handleToggleDisabled(u)} className={btnGhost}>
                              {u.disabled ? "启用" : "禁用"}
                            </button>
                            {trialLimit > 0 && u.role !== "admin" && (
                              <button onClick={() => void handleResetTrial(u)} className={btnGhost}>
                                重置试用
                              </button>
                            )}
                            <button
                              onClick={() => void handleDeleteUser(u)}
                              className={`${btn} border border-line bg-white text-red-600 hover:bg-red-50`}
                            >
                              删除
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-4xl flex-col gap-3">
            <div className="flex items-center gap-2">
              <select className={`${input} max-w-xs`} value={userFilter} onChange={(e) => setUserFilter(e.target.value)}>
                <option value="">全部用户</option>
                {users
                  .filter((u) => u.id !== "_orphan")
                  .map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.username}
                    </option>
                  ))}
              </select>
              <span className="text-xs text-muted">共 {sessions.length} 条记录</span>
            </div>

            {sessions.length === 0 ? (
              <div className="rounded-xl border border-line bg-white p-8 text-center text-sm text-muted shadow-card">
                暂无会话记录
              </div>
            ) : (
              sessions.map((s) => (
                <div key={s.id} className="flex items-center gap-3 rounded-xl border border-line bg-white px-4 py-3 shadow-card">
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${
                      s.kind === "report" ? "bg-amber-100 text-amber-700" : "bg-blue-100 text-blue-700"
                    }`}
                  >
                    {s.kind === "report" ? "报告" : "对话"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-ink">{s.title}</div>
                    <div className="mt-0.5 text-xs text-muted">
                      归属 {nameOf(s.user_id)} · {fmtTs(new Date(s.ts).toISOString())}
                      {s.kind === "chat" && s.exchanges ? ` · ${s.exchanges} 轮问答` : ""}
                    </div>
                  </div>
                  <button
                    onClick={() => void handleDeleteSession(s)}
                    className={`${btn} border border-line bg-white text-red-600 hover:bg-red-50`}
                  >
                    删除
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </main>
    </div>
  );
}
