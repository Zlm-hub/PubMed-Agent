import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "127.0.0.1",
    // 本地开发把 /api 代理到后端（2026-09-21）：前端全部走同源相对路径，
    // 登录 cookie 的读写与 EventSource 流式分析都不再有跨源问题——
    // 此前 5173→8000 跨端口 fetch 不带 credentials，浏览器丢弃 Set-Cookie，
    // 登录"成功"后所有请求 401（生产单端口同源不受影响，此问题只在本地暴露）。
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
