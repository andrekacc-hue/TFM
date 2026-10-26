/** Configuración pública del portal (variables VITE_* del .env de la raíz). */

function required(name: keyof ImportMetaEnv): string {
  const value = import.meta.env[name];
  if (!value) {
    throw new Error(`Falta la variable ${name} en el .env (ver .env.example)`);
  }
  return value;
}

export const env = {
  supabaseUrl: required("VITE_SUPABASE_URL"),
  supabaseAnonKey: required("VITE_SUPABASE_ANON_KEY"),
  gatewayUrl: required("VITE_API_GATEWAY_URL").replace(/\/$/, ""),
  appName: import.meta.env.VITE_APP_NAME ?? "Soporte TI Producción",
  azureEnabled: import.meta.env.VITE_AZURE_ENABLED === "true",
} as const;
