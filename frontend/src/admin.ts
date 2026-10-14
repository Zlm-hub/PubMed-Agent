/**
 * 管理后台 API 封装（自包含，2026-09-20 用户/管理员功能配套）。
 * 仅管理员角色可用；401/403 由调用方处理（弹提示，不打断面板）。
 */
import { API_BASE, type AuthUser } from "./apiBase";
import type { Session } from "./agent/model";

/** 管理面板的用户行：账号信息 + 会话统计（服务端一次给全） */
export interface AdminUserRow {
  id: string;
  username: string;
  role: "admin" | "user" | "-";
  display_name: string | null;
  created_at: string | null;
  last_login_at: string | null;
  disabled: number;
  chats: number;
  reports: number;
  last_active: string | null;
  /** 已用免费试用次数（服务器版启用额度后才有意义；管理员豁免恒为 0） */
  trial_used?: number;
}

export interface AdminOverview {
  users: number;
  chats: number;
  reports: number;
  per_user: AdminUserRow[];
}

async function ensureOk(r: Response): Promise<Response> {
  if (!r.ok) throw new Error(`${r.status}`);
  return r;
}

export async function fetchOverview(): Promise<AdminOverview | null> {
  try {
    return (await (await ensureOk(await fetch(`${API_BASE}/api/admin/overview`, { credentials: "include" }))).json()) as AdminOverview;
  } catch {
    return null;
  }
}

export async function fetchUsers(): Promise<AdminUserRow[]> {
  try {
    const j = (await (await ensureOk(await fetch(`${API_BASE}/api/admin/users`, { credentials: "include" }))).json()) as {
      users: AdminUserRow[];
    };
    return j.users;
  } catch {
    return [];
  }
}

export async function createUser(
  username: string,
  password: string,
  role: "admin" | "user",
  displayName?: string
): Promise<{ ok: boolean; error?: string }> {
  try {
    const r = await fetch(`${API_BASE}/api/admin/users`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, role, display_name: displayName ?? null }),
    });
    if (!r.ok) {
      const j = (await r.json().catch(() => ({}))) as { detail?: string };
      return { ok: false, error: j.detail ?? `创建失败（${r.status}）` };
    }
    return { ok: true };
  } catch {
    return { ok: false, error: "网络错误，创建失败" };
  }
}

export interface UserPatch {
  disabled?: boolean;
  password?: string;
  role?: "admin" | "user";
  display_name?: string | null;
  /** 把该账号的免费试用计数清零（客户联系后「再给几次」） */
  reset_trial?: boolean;
}

export async function patchUser(
  id: string,
  patch: UserPatch
): Promise<{ ok: boolean; error?: string }> {
  try {
    const r = await fetch(`${API_BASE}/api/admin/users/${id}`, {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!r.ok) {
      const j = (await r.json().catch(() => ({}))) as { detail?: string };
      return { ok: false, error: j.detail ?? `操作失败（${r.status}）` };
    }
    return { ok: true };
  } catch {
    return { ok: false, error: "网络错误，操作失败" };
  }
}

export async function deleteUser(
  id: string
): Promise<{ ok: boolean; error?: string; transferred?: number }> {
  try {
    const r = await fetch(`${API_BASE}/api/admin/users/${id}`, { method: "DELETE", credentials: "include" });
    if (!r.ok) {
      const j = (await r.json().catch(() => ({}))) as { detail?: string };
      return { ok: false, error: j.detail ?? `删除失败（${r.status}）` };
    }
    const j = (await r.json()) as { transferred_sessions?: number };
    return { ok: true, transferred: j.transferred_sessions ?? 0 };
  } catch {
    return { ok: false, error: "网络错误，删除失败" };
  }
}

/** 全部会话视图：user_id 缺省 = 全部用户 */
export async function fetchAllSessions(userId?: string, kind: "all" | "chat" | "report" = "all"): Promise<Session[]> {
  try {
    const qs = new URLSearchParams({ kind, limit: "50" });
    if (userId) qs.set("user_id", userId);
    const j = (await (
      await ensureOk(await fetch(`${API_BASE}/api/admin/sessions?${qs.toString()}`, { credentials: "include" }))
    ).json()) as { sessions: Record<string, unknown>[] };
    return (j.sessions ?? []).map((row) => ({
      id: String(row.id),
      kind: row.kind === "report" ? ("report" as const) : ("chat" as const),
      title: (row.title as string) ?? "",
      ts: typeof row.ts === "number" ? row.ts : Date.parse(String(row.ts)) || Date.now(),
      query: typeof row.query === "string" ? row.query : null,
      chatId: (row.chat_id as string | null) ?? null,
      exchanges: typeof row.exchanges === "number" ? row.exchanges : undefined,
      user_id: typeof row.user_id === "string" ? row.user_id : null,
    })) as Session[];
  } catch {
    return [];
  }
}

export async function deleteAnySession(id: string): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/api/admin/sessions/${id}`, { method: "DELETE", credentials: "include" });
    return r.ok;
  } catch {
    return false;
  }
}

/** 管理员身份（面板顶部显示"以 xxx 身份管理"用） */
export type { AuthUser };
