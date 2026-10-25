import { zodResolver } from "@hookform/resolvers/zod";
import { Bot, FileSearch, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useLocation } from "react-router-dom";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/form-controls";
import { useAuth } from "@/hooks/useAuth";
import { env } from "@/lib/env";

export const loginSchema = z.object({
  email: z.string().trim().min(1, "Ingresa tu correo").email("Correo no válido"),
  password: z.string().min(6, "Mínimo 6 caracteres"),
});
type LoginValues = z.infer<typeof loginSchema>;

const FEATURES = [
  { icon: FileSearch, text: "Respuestas basadas solo en documentación autorizada" },
  { icon: Sparkles, text: "Cada respuesta cita su fuente: documento, sección y página" },
  { icon: ShieldCheck, text: "Acceso por rol y área con trazabilidad completa" },
];

function MicrosoftLogo() {
  return (
    <svg viewBox="0 0 21 21" className="size-4" aria-hidden>
      <rect x="1" y="1" width="9" height="9" fill="#f25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
      <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
      <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
    </svg>
  );
}

export default function Login() {
  const { session, signIn, signInWithMicrosoft } = useAuth();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<LoginValues>({ resolver: zodResolver(loginSchema), defaultValues: { email: "", password: "" } });
  const { errors, isSubmitting } = form.formState;

  if (session) {
    const from = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={from} replace />;
  }

  const onSubmit = form.handleSubmit(async ({ email, password }) => {
    setError(null);
    try {
      await signIn(email, password);
    } catch (e) {
      setError((e as Error).message);
    }
  });

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <section className="relative hidden flex-col justify-between overflow-hidden bg-primary p-10 text-primary-foreground lg:flex">
        <div className="absolute -right-24 -top-24 size-96 rounded-full bg-white/10 blur-2xl" aria-hidden />
        <div className="absolute -bottom-32 -left-16 size-96 rounded-full bg-black/10 blur-2xl" aria-hidden />
        <div className="relative flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-lg bg-white/15">
            <Bot className="size-5" aria-hidden />
          </div>
          <span className="text-lg font-semibold">{env.appName}</span>
        </div>
        <div className="relative max-w-md space-y-6">
          <h2 className="text-3xl font-semibold leading-tight">Base de conocimientos inteligente para TI Producción</h2>
          <ul className="space-y-3">
            {FEATURES.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-start gap-3 text-primary-foreground/90">
                <Icon className="mt-0.5 size-5 shrink-0" aria-hidden />
                {text}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-sm text-primary-foreground/70">Trabajo Fin de Máster · Máster en Inteligencia Artificial · UNIR</p>
      </section>

      <main className="flex items-center justify-center p-6">
        <Card className="w-full max-w-sm border-0 shadow-none sm:border sm:shadow-sm">
          <CardHeader className="space-y-1">
            <div className="mb-2 flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground lg:hidden">
              <Bot className="size-5" aria-hidden />
            </div>
            <CardTitle className="text-xl">Iniciar sesión</CardTitle>
            <CardDescription>Accede con tu cuenta corporativa</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {env.azureEnabled && (
              <>
                <Button variant="outline" className="w-full" onClick={() => void signInWithMicrosoft().catch((e: Error) => setError(e.message))}>
                  <MicrosoftLogo /> Continuar con Microsoft
                </Button>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="h-px flex-1 bg-border" /> o con correo <span className="h-px flex-1 bg-border" />
                </div>
              </>
            )}
            <form onSubmit={onSubmit} className="space-y-4" noValidate>
              <Field id="email" label="Correo electrónico" error={errors.email?.message}>
                <Input type="email" autoComplete="email" placeholder="nombre@produbanco.com" {...form.register("email")} />
              </Field>
              <Field id="password" label="Contraseña" error={errors.password?.message}>
                <Input type="password" autoComplete="current-password" {...form.register("password")} />
              </Field>
              {error && (
                <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  {error}
                </p>
              )}
              <Button type="submit" className="w-full" loading={isSubmitting}>
                Entrar
              </Button>
            </form>
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
