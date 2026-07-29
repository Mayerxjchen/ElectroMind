import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const backendHost = process.env.ELECTROMIND_HTTP_HOST ?? "127.0.0.1";
const backendPort = process.env.ELECTROMIND_HTTP_PORT ?? "8848";
const proxyHost = backendHost === "0.0.0.0" ? "127.0.0.1" : backendHost;
const backendTarget = `http://${proxyHost}:${backendPort}`;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/health": {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
});
