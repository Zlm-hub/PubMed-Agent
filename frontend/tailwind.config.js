/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#2196F3", hover: "#1565C0" },
        accent: "#E91E4E",
        ink: "#0F172A",
        muted: "#64748B",
        line: "#E5E7EB",
        appbg: "#F7F8FA",
      },
      borderRadius: { sm: "8px", md: "12px", lg: "16px" },
      fontFamily: {
        sans: [
          'Inter',
          '"HarmonyOS Sans SC"',
          '"MiSans"',
          '"Noto Sans SC"',
          '"Microsoft YaHei UI"',
          'system-ui',
          'sans-serif',
        ],
        mono: [
          '"JetBrains Mono"',
          'ui-monospace',
          '"Cascadia Code"',
          'Consolas',
          'monospace',
        ],
      },
      boxShadow: {
        // 卡片常态：极轻的投影替代"纯描边"，边框保留作边界
        card: "0 1px 2px 0 rgb(15 23 42 / 0.04)",
        // 可交互卡片 hover：轻微上浮感
        lift: "0 6px 20px -6px rgb(15 23 42 / 0.12)",
      },
    },
  },
  plugins: [],
};
