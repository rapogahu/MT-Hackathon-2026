import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const source = process.env.VITE_DATA_SOURCE ?? env.VITE_DATA_SOURCE ?? "api";
  const apiTarget = process.env.VITE_DEV_API_TARGET ?? env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8000";

  if (command === "build" && source !== "api") {
    throw new Error(
      "Production build rejected: VITE_DATA_SOURCE must be 'api'. Fixtures are development/test only.",
    );
  }

  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test-setup.ts",
      css: true,
    },
  };
});
