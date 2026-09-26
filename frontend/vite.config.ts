import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const source = process.env.VITE_DATA_SOURCE ?? env.VITE_DATA_SOURCE ?? "api";

  if (command === "build" && source !== "api") {
    throw new Error(
      "Production build rejected: VITE_DATA_SOURCE must be 'api'. Fixtures are development/test only.",
    );
  }

  return {
    plugins: [react()],
    test: {
      environment: "jsdom",
      setupFiles: "./src/test-setup.ts",
      css: true,
    },
  };
});
