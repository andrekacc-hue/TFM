import { Suspense, type ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { Skeleton } from "@/components/ui/feedback";

import { ErrorBoundary } from "./ErrorBoundary";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

function PageFallback() {
  return (
    <div className="space-y-4" aria-busy aria-label="Cargando">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-80" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
      <Skeleton className="h-72" />
    </div>
  );
}

export function AppLayout() {
  const { pathname } = useLocation();
  return (
    <div className="flex min-h-screen">
      <a
        href="#contenido"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Saltar al contenido
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main id="contenido" className="flex-1 px-4 py-6 lg:px-8" tabIndex={-1}>
          {/* key: un error en una página no deja rota la navegación al cambiar de ruta */}
          <ErrorBoundary key={pathname}>
            <Suspense fallback={<PageFallback />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
