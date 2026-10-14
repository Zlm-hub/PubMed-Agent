/**
 * 统一的 API 基址与「登录/访问口令」处理（自包含，不改既有业务逻辑）。
 *
 * 为什么这样设计：
 *  - **生产（单端口部署）**：FastAPI 同时托管前端页面与 /api，前后端同源，此时
 *    API_BASE 应为空串，所有请求走相对路径 `/api/...`。因此构建时不注入
 *    VITE_API_BASE 即可（vite 的 production 模式不会加载 .env.development）。
 *  - **本地开发**：Vite dev server 把 /api 代理到 127.0.0.1:8000（见 vite.config.ts），
 *    API_BASE 同样为空串=同源。2026-09-21 前这里是 http://localhost:8000 直连——
 *    跨端口属于跨源，fetch 默认不携带也不保存 cookie：登录"成功"后所有请求 401
 *    （生产同源不受影响，此坑只在本地暴露，实测踩过）。
 *  - **登录态**：登录成功后由服务端下发签名 cookie（`pa_session`），此后所有请求
 *    自动携带，无需在前端逐处塞 token。fetch 统一加 `credentials: "include"`：
 *    同源时无害，将来若真出现跨源部署也能带上凭证。
 */

/** 显式覆盖（可选）：构建时用 VITE_API_BASE 指定后端地址，留空按下方默认推导。 */
const OVERRIDE = String(import.meta.env.VITE_API_BASE ?? "").trim();

/**
 * 实际基址：
 *  - 显式设了 VITE_API_BASE → 用它；
 *  - 否则开发/生产都是 ""（同源：开发走 vite 代理，生产走 FastAPI 托管的 /api）。
 */
export const API_BASE = OVERRIDE.replace(/\/+$/, "");

/** 当前登录用户（服务端从 cookie 解出，前端只读、不参与鉴权判断） */
export interface AuthUser {
  id: string;
  username: string;
  role: "admin" | "user";
  display_name?: string | null;
}

/**
 * 后端鉴权模式（服务端自动切换，前端据此弹哪种登录门）：
 *  user —— 用户体系激活：用户名 + 密码登录
 *  code —— 旧共享口令模式（未建用户但配置了 ACCESS_CODE，部署过渡期兼容）
 *  open —— 无鉴权（本地开发）
 */
export type AuthMode = "user" | "code" | "open";

export interface AuthStatus {
  auth_required: boolean;
  authorized: boolean;
  mode: AuthMode;
  user: AuthUser | null;
  /** 是否开放自助注册（后端 ALLOW_REGISTRATION 开关） */
  allow_registration?: boolean;
  /** 首次引导：系统里还没有任何账号，此页可将第一个注册者设为管理员 */
  can_bootstrap?: boolean;
  /** 试用额度（未启用 / 管理员豁免 = null） */
  trial?: TrialQuota | null;
}

/** 试用额度（服务器版「每个账号免费试用 N 次」；未启用或管理员豁免时后端返回 null） */
export interface TrialQuota {
  limit: number;
  used: number;
  remaining: number;
  contact?: string | null;
}

export interface TrialStatus {
  enabled: boolean;
  /** 额度总数（顶层，管理员也拿得到；用于管理面板显示「已用 / 总次数」） */
  limit?: number;
  contact?: string | null;
  /** 管理员/运维通道豁免（不受限、不计数） */
  exempt: boolean;
  quota: TrialQuota | null;
}

/** 查询鉴权状态。后端不可达时按「无需登录」处理，避免卡死页面。 */
export async function authStatus(): Promise<AuthStatus> {
  try {
    const r = await fetch(`${API_BASE}/api/auth`, { credentials: "include" });
    if (!r.ok) return { auth_required: false, authorized: true, mode: "open", user: null };
    const j = (await r.json()) as AuthStatus;
    return {
      auth_required: !!j.auth_required,
      authorized: !!j.authorized,
      mode: j.mode ?? "open",
      user: j.user ?? null,
      allow_registration: !!j.allow_registration,
      can_bootstrap: !!j.can_bootstrap,
      trial: j.trial ?? null,
    };
  } catch {
    return { auth_required: false, authorized: true, mode: "open", user: null };
  }
}

/** 当前账号的试用额度（每次分析后刷新：后端是唯一事实来源，前端只负责展示）。 */
export async function fetchTrial(): Promise<TrialStatus | null> {
  try {
    const r = await fetch(`${API_BASE}/api/trial`, { credentials: "include" });
    if (!r.ok) return null;
    return (await r.json()) as TrialStatus;
  } catch {
    return null;
  }
}

/** 用户名 + 密码登录；成功返回用户信息（服务端已下发 cookie），失败返回 null。 */
export async function login(username: string, password: string): Promise<AuthUser | null> {
  try {
    const r = await fetch(`${API_BASE}/api/auth`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!r.ok) return null;
    const j = (await r.json()) as { user?: AuthUser };
    return j.user ?? null;
  } catch {
    return null;
  }
}

/** 提交旧共享口令（code 模式过渡兼容）；成功则服务端下发 cookie，返回 true。 */
export async function submitCode(code: string): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/api/auth`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    return r.ok;
  } catch {
    return false;
  }
}

/** 自助注册（需后端开放注册）；成功即登录（服务端同时下发 cookie）。
 *  失败返回错误文案：后端已给出「用户名已存在」这类可读 detail，直接展示比笼统报错有用。 */
export async function register(
  username: string,
  password: string,
  displayName?: string
): Promise<{ ok: true; user: AuthUser; bootstrap: boolean } | { ok: false; error: string }> {
  try {
    const r = await fetch(`${API_BASE}/api/auth/register`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, display_name: displayName ?? null }),
    });
    const j = (await r.json().catch(() => ({}))) as {
      user?: AuthUser;
      detail?: string;
      bootstrap?: boolean;
    };
    if (!r.ok) return { ok: false, error: j.detail ?? `注册失败（${r.status}）` };
    if (!j.user) return { ok: false, error: "注册失败：服务端未返回账号信息" };
    return { ok: true, user: j.user, bootstrap: !!j.bootstrap };
  } catch {
    return { ok: false, error: "网络错误，注册失败" };
  }
}

/** 退出登录：清登录 cookie。 */
export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/api/auth/logout`, { method: "POST", credentials: "include" });
  } catch {
    /* 网络失败也照常走本地清理（刷新页面） */
  }
}
