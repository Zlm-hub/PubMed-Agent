/**
 * 登录 / 注册门（用户与管理员功能，2026-09-20；同日补自助注册）。
 *
 * 后端三种模式自动切换（GET /api/auth 的 mode 字段）：
 *  user —— 用户名 + 密码登录（用户体系激活后的常态）
 *  code —— 旧共享口令（部署过渡期兼容，未建用户时）
 *  open —— 无鉴权（本地开发），直通且用户无感
 *
 * 注册入口只在 `allow_registration` 为真时出现（后端 ALLOW_REGISTRATION=1）。
 * 另有 `can_bootstrap`：系统里一个账号都没有时（全新部署），第一个注册者即管理员，
 * 否则全新部署会彻底锁死——这个例外会在按钮下方如实标注。
 *
 * 2026-09-20 晚：整页重排为「左品牌区 + 右登录卡」分栏（用户给的参考图风格）——
 * 左侧 logo / 主标语 / 三条卖点 / 手绘蓝色系插画（自绘 SVG，非参考图素材），
 * 右侧白卡承载原有全部表单逻辑（一行未改），小屏退化为单卡 + 顶部品牌条。
 *
 * 登录/注册成功后把当前用户（含角色）交给 children 渲染函数，供外壳显示
 * 用户名 / 管理后台入口。退出 = 清 cookie + 整页刷新，回到本门。
 */
import { useEffect, useState, type ReactNode } from "react";
import { authStatus, login, register, submitCode, type AuthUser } from "./apiBase";
import { LogoMark } from "./agent/Sidebar";

type State = "checking" | "open" | "locked";
type Mode = "login" | "register";

/** 登录页插画：蓝色系自绘 SVG（文档 + 图表卡 + 放大镜 + 云 + 环形），装饰用途 */
function GateArt() {
  return (
    <svg viewBox="0 0 560 440" className="h-auto w-full" aria-hidden="true">
      <defs>
        <linearGradient id="gate-blue" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#60A5FA" />
          <stop offset="1" stopColor="#2563EB" />
        </linearGradient>
        <linearGradient id="gate-blue2" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#93C5FD" />
          <stop offset="1" stopColor="#3B82F6" />
        </linearGradient>
        <linearGradient id="gate-soft" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#DBEAFE" />
          <stop offset="1" stopColor="#BFDBFE" />
        </linearGradient>
        <linearGradient id="gate-yellow" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#FDE68A" />
          <stop offset="1" stopColor="#FBBF24" />
        </linearGradient>
      </defs>

      {/* 背景光斑 + 轨道 */}
      <circle cx="290" cy="215" r="152" fill="#EFF5FF" />
      <ellipse
        cx="300"
        cy="225"
        rx="238"
        ry="130"
        fill="none"
        stroke="#BFDBFE"
        strokeWidth="1.5"
        strokeDasharray="5 7"
        transform="rotate(-12 300 225)"
      />

      {/* 环形（右上） */}
      <circle cx="432" cy="86" r="30" fill="none" stroke="url(#gate-blue)" strokeWidth="15" />
      <circle cx="410" cy="70" r="6" fill="#ffffff" fillOpacity="0.5" />

      {/* 主文档卡 */}
      <g>
        <rect x="196" y="88" width="176" height="228" rx="14" fill="#ffffff" stroke="#BFDBFE" strokeWidth="2" />
        <rect x="216" y="112" width="86" height="14" rx="7" fill="url(#gate-blue2)" />
        <rect x="216" y="142" width="136" height="8" rx="4" fill="#E2E8F0" />
        <rect x="216" y="158" width="112" height="8" rx="4" fill="#E2E8F0" />
        <rect x="216" y="174" width="124" height="8" rx="4" fill="#E2E8F0" />
        <rect x="216" y="198" width="136" height="94" rx="8" fill="#F0F6FF" />
        <path
          d="M228 272 252 246 272 258 296 226 316 240 340 210"
          fill="none"
          stroke="url(#gate-blue)"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="340" cy="210" r="4.5" fill="#2563EB" />
      </g>

      {/* 柱状图小卡 */}
      <g>
        <rect x="372" y="196" width="118" height="104" rx="12" fill="#ffffff" stroke="#BFDBFE" strokeWidth="2" />
        <rect x="390" y="252" width="14" height="30" rx="3" fill="#BFDBFE" />
        <rect x="412" y="236" width="14" height="46" rx="3" fill="url(#gate-blue2)" />
        <rect x="434" y="246" width="14" height="36" rx="3" fill="#BFDBFE" />
        <rect x="456" y="224" width="14" height="58" rx="3" fill="url(#gate-blue)" />
      </g>

      {/* 放大镜（左下） */}
      <g>
        <circle cx="128" cy="300" r="52" fill="url(#gate-soft)" fillOpacity="0.35" stroke="url(#gate-blue)" strokeWidth="10" />
        <circle cx="110" cy="282" r="14" fill="#ffffff" fillOpacity="0.55" />
        <rect
          x="76"
          y="338"
          width="16"
          height="62"
          rx="8"
          fill="url(#gate-blue)"
          transform="rotate(45 84 338)"
        />
      </g>

      {/* 云（右下 + 左上） */}
      <g fill="#BFDBFE">
        <circle cx="406" cy="338" r="20" />
        <circle cx="432" cy="326" r="26" />
        <circle cx="458" cy="340" r="18" />
        <rect x="398" y="336" width="72" height="20" rx="10" />
      </g>
      <g fill="#DBEAFE">
        <circle cx="142" cy="112" r="14" />
        <circle cx="160" cy="104" r="18" />
        <circle cx="180" cy="114" r="12" />
        <rect x="136" y="108" width="56" height="16" rx="8" />
      </g>

      {/* 点缀小球与加号 */}
      <circle cx="80" cy="182" r="12" fill="url(#gate-yellow)" />
      <circle cx="502" cy="162" r="9" fill="url(#gate-blue2)" />
      <circle cx="60" cy="80" r="6" fill="#BFDBFE" />
      <circle cx="484" cy="42" r="5" fill="#FBBF24" />
      <circle cx="242" cy="42" r="7" fill="#DBEAFE" />
      <circle cx="530" cy="256" r="5" fill="#93C5FD" />
      <path d="M166 138v12M160 144h12" stroke="#93C5FD" strokeWidth="2.5" strokeLinecap="round" fill="none" />
      <path d="M508 296v10M503 301h10" stroke="#BFDBFE" strokeWidth="2.5" strokeLinecap="round" fill="none" />
    </svg>
  );
}

export default function AccessGate({ children }: { children: (user: AuthUser | null) => ReactNode }) {
  const [state, setState] = useState<State>("checking");
  const [codeMode, setCodeMode] = useState(false);
  const [openReg, setOpenReg] = useState(false);
  const [bootstrap, setBootstrap] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [code, setCode] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    authStatus().then((s) => {
      if (!alive) return;
      setCodeMode(s.mode === "code");
      setOpenReg(!!s.allow_registration);
      setBootstrap(!!s.can_bootstrap);
      setUser(s.user);
      // 首引导例外：系统里还没有任何账号（open 模式），仍要显示注册门——
      // 否则全新部署（未配 ADMIN_*）点进去是空壳，谁也没法在系统里留下账号。
      if (s.can_bootstrap) {
        setMode("register");
        setState("locked");
        return;
      }
      setState(!s.auth_required || s.authorized ? "open" : "locked");
    });
    return () => {
      alive = false;
    };
  }, []);

  function reset(next: Mode) {
    setMode(next);
    setErr("");
    setPassword("");
    setConfirm("");
    setCode("");
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const u = username.trim();

    if (codeMode) {
      setBusy(true);
      setErr("");
      const ok = await submitCode(code.trim());
      setBusy(false);
      if (ok) setState("open");
      else setErr("访问口令不正确，请向管理员确认");
      return;
    }

    if (mode === "register") {
      if (password !== confirm) {
        setErr("两次输入的密码不一致");
        return;
      }
      setBusy(true);
      setErr("");
      const res = await register(u, password, displayName.trim() || undefined);
      setBusy(false);
      if (!res.ok) {
        setErr(res.error);
        return;
      }
      setUser(res.user);
      setState("open");
      return;
    }

    if (!u || !password) return;
    setBusy(true);
    setErr("");
    const logged = await login(u, password);
    setBusy(false);
    if (logged) {
      setUser(logged);
      setState("open");
    } else {
      setErr("用户名或密码不正确");
    }
  }

  if (state === "checking") {
    return (
      <div className="grid min-h-screen place-items-center bg-[#eef1f6] text-sm text-muted">正在连接服务…</div>
    );
  }
  if (state === "open") return <>{children(user)}</>;

  const inputCls =
    "mt-4 w-full rounded-lg border border-line bg-white px-4 py-3 text-sm outline-none transition-all focus:border-brand focus:ring-2 focus:ring-brand/15";
  const canSubmit = codeMode
    ? !!code.trim()
    : mode === "register"
      ? !!username.trim() && password.length >= 6 && !!confirm
      : !!username.trim() && !!password;

  const cardTitle = codeMode
    ? "口令登录"
    : mode === "register"
      ? bootstrap
        ? "创建管理员账号"
        : "注册账号"
      : "账号登录";
  const cardSubtitle = codeMode
    ? "请输入访问口令以继续体验"
    : mode === "register"
      ? bootstrap
        ? "首次使用：第一个注册的账号将成为管理员"
        : "创建新账号，开始使用"
      : "请登录以继续使用";

  return (
    <div className="flex min-h-screen flex-col bg-[#eef1f6]">
      {/* 页面左上角品牌行（小屏隐藏，改由卡上方品牌条承担） */}
      <header className="hidden px-10 pt-7 lg:block">
        <div className="flex items-center gap-2.5">
          <div className="grid h-9 w-9 place-items-center rounded-md bg-brand shadow-card">
            <LogoMark size={18} />
          </div>
          <span className="text-lg font-semibold tracking-tight text-ink">PubMed 文献分析助手</span>
        </div>
      </header>

      <div className="flex flex-1 items-center justify-center px-6 py-10">
        <div className="grid w-full max-w-7xl items-center gap-10 lg:grid-cols-[1.1fr_400px]">
          {/* 左：主标语 + 卖点 + 插画 */}
          <section className="hidden lg:block">
            <div className="flex items-center gap-4">
              <div className="w-[280px] shrink-0">
                <h1 className="text-[34px] font-bold leading-snug tracking-tight text-ink">
                  一句话，
                  <br />
                  完成一次文献分析
                </h1>
                <ul className="mt-9 space-y-5">
                  <li>
                    <div className="text-sm font-semibold text-ink">全面 / 真实的检索</div>
                    <div className="mt-0.5 text-[13px] leading-5 text-muted">直连 NCBI PubMed，结果可溯源</div>
                  </li>
                  <li>
                    <div className="text-sm font-semibold text-ink">开放 / 多维的统计</div>
                    <div className="mt-0.5 text-[13px] leading-5 text-muted">概览 · 词云 · 图表 · 影响力 Top100</div>
                  </li>
                  <li>
                    <div className="text-sm font-semibold text-ink">持续 / 内置的指标</div>
                    <div className="mt-0.5 text-[13px] leading-5 text-muted">2,700+ 期刊影响因子与分区</div>
                  </li>
                </ul>
              </div>
              <div className="min-w-0 flex-1">
                <GateArt />
              </div>
            </div>
          </section>

          {/* 右：登录卡（承载全部原有表单逻辑） */}
          <section className="mx-auto w-full max-w-[400px]">
            {/* 小屏品牌条 */}
            <div className="mb-6 flex items-center gap-2.5 lg:hidden">
              <div className="grid h-8 w-8 place-items-center rounded-md bg-brand shadow-card">
                <LogoMark />
              </div>
              <span className="text-base font-semibold tracking-tight text-ink">PubMed 文献分析助手</span>
            </div>

            <form onSubmit={onSubmit} className="rounded-2xl bg-white p-8 shadow-lift sm:p-9">
              <h2 className="text-xl font-bold text-brand">{cardTitle}</h2>
              <p className="mt-1.5 text-sm text-muted">{cardSubtitle}</p>

              {codeMode ? (
                <input
                  type="password"
                  autoFocus
                  value={code}
                  onChange={(e) => {
                    setCode(e.target.value);
                    if (err) setErr("");
                  }}
                  placeholder="访问口令"
                  className={inputCls}
                />
              ) : (
                <>
                  <input
                    type="text"
                    autoFocus
                    value={username}
                    onChange={(e) => {
                      setUsername(e.target.value);
                      if (err) setErr("");
                    }}
                    placeholder="用户名（2~32 位）"
                    autoComplete="username"
                    className={inputCls}
                  />
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value);
                      if (err) setErr("");
                    }}
                    placeholder={mode === "register" ? "密码（6~64 位）" : "密码"}
                    autoComplete={mode === "register" ? "new-password" : "current-password"}
                    className={inputCls}
                  />
                  {mode === "register" && (
                    <>
                      <input
                        type="password"
                        value={confirm}
                        onChange={(e) => {
                          setConfirm(e.target.value);
                          if (err) setErr("");
                        }}
                        placeholder="确认密码"
                        autoComplete="new-password"
                        className={inputCls}
                      />
                      <input
                        type="text"
                        value={displayName}
                        onChange={(e) => setDisplayName(e.target.value)}
                        placeholder="显示名（可选，默认同用户名）"
                        className={inputCls}
                      />
                    </>
                  )}
                </>
              )}

              {err && <div className="mt-3 text-xs text-red-600">{err}</div>}

              <button
                type="submit"
                disabled={busy || !canSubmit}
                className="mt-7 w-full rounded-lg bg-brand py-3 text-sm font-medium tracking-[0.3em] text-white shadow-card transition-all hover:bg-brand-hover hover:shadow-lift disabled:opacity-50 disabled:shadow-none"
              >
                <span className="ml-[0.3em]">{busy ? "处理中…" : codeMode ? "进入" : mode === "register" ? "注册并登录" : "登录"}</span>
              </button>

              {/* 登录 ⇄ 注册切换（仅在开放注册时出现；code 模式无账号概念） */}
              {!codeMode && openReg && (
                <p className="mt-5 text-center text-xs text-muted">
                  {mode === "register" ? (
                    <>
                      已有账号？
                      <button type="button" onClick={() => reset("login")} className="ml-1 text-brand hover:underline">
                        去登录
                      </button>
                    </>
                  ) : (
                    <>
                      还没有账号？
                      <button type="button" onClick={() => reset("register")} className="ml-1 text-brand hover:underline">
                        立即注册
                      </button>
                    </>
                  )}
                </p>
              )}

              {!codeMode && !openReg && (
                <p className="mt-5 text-center text-xs text-muted">账号由管理员统一创建，如需开通请联系管理员</p>
              )}

              {!codeMode && mode === "register" && bootstrap && (
                <p className="mt-2 text-center text-xs text-amber-600">
                  当前系统没有任何账号，第一个注册的账号将成为管理员
                </p>
              )}

              {!codeMode && mode === "register" && !bootstrap && (
                <p className="mt-2 text-center text-xs text-muted">注册账号为普通用户，管理权限请联系管理员</p>
              )}
            </form>
          </section>
        </div>
      </div>

      <footer className="pb-6 text-center text-xs text-muted/80">
        Copyright © 2026 PubMed 文献分析助手 · All Rights Reserved
      </footer>
    </div>
  );
}
