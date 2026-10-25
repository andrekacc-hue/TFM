/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string;
  readonly VITE_SUPABASE_ANON_KEY: string;
  readonly VITE_API_GATEWAY_URL: string;
  readonly VITE_APP_NAME?: string;
  readonly VITE_AZURE_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
