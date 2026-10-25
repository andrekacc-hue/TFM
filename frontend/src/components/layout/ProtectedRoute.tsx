import { Loader2, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/ui/feedback";
import { useAuth } from "@/hooks/useAuth";
import { hasRole, type Role } from "@/types/auth";

function FullScreenLoader() {
  return (
    <div className="flex min-h-screen items-center justify-center" role="status" aria-label="Cargando sesión">
      <Loader2 className="size-6 animate-spin text-primary" />
    </div>
  );
}

/** Exige sesión y perfil de aplicación; si no, redirige al login conservando el destino. */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { session, me, loading, meError, signOut } = useAuth();
  const location = useLocation();

  if (loading) return <FullScreenLoader />;
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (meError || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="w-full max-w-md space-y-3">
          <ErrorState message={meError?.message ?? "No se pudo cargar tu perfil de usuario."} />
          <Button variant="outline" className="w-full" onClick={() => void signOut()}>
            Volver al inicio de sesión
          </Button>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}

/** Restringe una página a un rol mínimo (el gateway aplica la misma regla en el servidor). */
export function RequireRole({ minimum, children }: { minimum: Role; children: ReactNode }) {
  const { me } = useAuth();
  if (!hasRole(me?.role, minimum)) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Acceso restringido"
        description={`Esta sección requiere el rol ${minimum === "admin" ? "Administrador" : "Editor"} o superior.`}
      />
    );
  }
  return <>{children}</>;
}

/** Página de inicio según el rol: los editores ven el dashboard; los usuarios de consulta, el chat. */
export function HomeRedirect() {
  const { me } = useAuth();
  return <Navigate to={hasRole(me?.role, "editor") ? "/dashboard" : "/consulta"} replace />;
}
