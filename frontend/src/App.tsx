import { QueryClientProvider } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Suspense } from "react";
import { RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";

import { ErrorBoundary } from "@/components/layout/ErrorBoundary";
import { AuthProvider } from "@/hooks/useAuth";
import { queryClient } from "@/lib/query-client";
import { router } from "@/routes";
import { useUiStore } from "@/stores/ui-store";

export default function App() {
  const theme = useUiStore((s) => s.theme);
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Suspense
            fallback={
              <div className="flex min-h-screen items-center justify-center" role="status" aria-label="Cargando">
                <Loader2 className="size-6 animate-spin text-primary" />
              </div>
            }
          >
            <RouterProvider router={router} />
          </Suspense>
          <Toaster richColors closeButton position="top-right" theme={theme} />
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
