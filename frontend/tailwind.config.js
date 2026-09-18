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
        sans: ['Inter', '"Noto Sans SC"', "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
