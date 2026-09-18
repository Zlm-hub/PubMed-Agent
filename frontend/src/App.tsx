/**
 * 应用入口。
 *
 * 升级说明：原报告视图已整体迁到 src/ReportView.tsx（逻辑零改动），
 * 这里改为挂载三栏 Agent 外壳，新增「对话 / 报告 / 设计思考」三个视图。
 */
import AgentShell from "./agent/AgentShell";

export default function App() {
  return <AgentShell />;
}
