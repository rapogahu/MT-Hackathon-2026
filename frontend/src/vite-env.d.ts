/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DATA_SOURCE?: "api" | "fixtures";
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_FIXTURE_SCENARIO?:
    | "default"
    | "empty-runs"
    | "error"
    | "degenerate";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
