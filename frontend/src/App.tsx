/**
 * 应用入口。
 *
 * 升级说明：原报告视图已整体迁到 src/ReportView.tsx（逻辑零改动），
 * 这里改为挂载三栏 Agent 外壳。
 * 2026-09-20：登录门通过后把当前用户（含角色）交给外壳，供顶栏显示与管理后台入口。
 */
import AgentShell from "./agent/AgentShell";
import AccessGate from "./AccessGate";
import type { AuthUser } from "./apiBase";

export default function App() {
  // AccessGate 只在后端要求登录时生效（本地开发/未建用户时直通，用户无感）。
  // 通过后以 children 函数下发当前用户：admin 可见「管理后台」，普通用户只看到自己。
  return (
    <AccessGate>
      {(user: AuthUser | null) => <AgentShell user={user} />}
    </AccessGate>
  );
}
