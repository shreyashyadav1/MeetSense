/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend base URL. See `resolveApiConfig` in src/config.ts and .env.example. */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
