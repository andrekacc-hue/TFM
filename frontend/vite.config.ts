import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// El .env es único para todo el proyecto (raíz del repositorio): Vite solo expone las
// variables con prefijo VITE_, nunca las claves secretas del backend.
export default defineConfig({
  plugins: [react()],
  envDir: path.resolve(__dirname, ".."),
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: { port: 5173, strictPort: true },
  preview: { port: 3000 },
  build: {
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          supabase: ["@supabase/supabase-js"],
          charts: ["recharts"],
          markdown: ["react-markdown", "remark-gfm"],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    // Los tests no deben leer el .env real del proyecto
    env: {
      VITE_SUPABASE_URL: "https://test.supabase.co",
      VITE_SUPABASE_ANON_KEY: "sb_publishable_test",
      VITE_API_GATEWAY_URL: "http://gateway.test",
      VITE_APP_NAME: "Soporte TI Producción",
    },
    coverage: { provider: "v8", include: ["src/**/*.{ts,tsx}"], exclude: ["src/test/**", "src/main.tsx", "src/**/*.d.ts"] },
  },
});
