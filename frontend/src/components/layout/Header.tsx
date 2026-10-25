import { LogOut, Menu, Monitor, Moon, Sun, UserRound } from "lucide-react";
import { useLocation } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/hooks/useAuth";
import { useSystemHealth } from "@/hooks/useMetrics";
import { cn } from "@/lib/utils";
import { useUiStore, type Theme } from "@/stores/ui-store";
import { ROLE_LABELS } from "@/types/auth";

import { NAV_ITEMS } from "./navigation";

const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Claro", icon: Sun },
  { value: "dark", label: "Oscuro", icon: Moon },
  { value: "system", label: "Sistema", icon: Monitor },
];

function HealthIndicator() {
  const { data, isError } = useSystemHealth();
  const status = isError ? "error" : (data?.status ?? "unknown");
  const label = { ok: "Sistema operativo", degraded: "Servicio degradado", error: "Servicio no disponible", unknown: "Comprobando…" }[status];
  const failing = data ? Object.entries(data.checks).filter(([, v]) => !v.startsWith("ok")).map(([k]) => k) : [];
  return (
    <div className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex" title={failing.length ? `Fallan: ${failing.join(", ")}` : label}>
      <span
        className={cn(
          "size-2 rounded-full",
          status === "ok" && "bg-success",
          status === "degraded" && "bg-warning",
          status === "error" && "bg-destructive",
          status === "unknown" && "bg-muted-foreground",
        )}
        aria-hidden
      />
      <span role="status">{label}</span>
    </div>
  );
}

export function Header() {
  const { me, signOut } = useAuth();
  const { theme, setTheme, setSidebarOpen } = useUiStore();
  const { pathname } = useLocation();
  const current = NAV_ITEMS.find((item) => pathname.startsWith(item.to));
  const ThemeIcon = THEMES.find((t) => t.value === theme)?.icon ?? Monitor;

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/70 lg:px-6">
      <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setSidebarOpen(true)} aria-label="Abrir menú">
        <Menu />
      </Button>
      <p className="truncate text-sm font-medium text-muted-foreground lg:hidden">{current?.label}</p>

      <div className="ml-auto flex items-center gap-2">
        <HealthIndicator />

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Cambiar tema">
              <ThemeIcon />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-36">
            {THEMES.map(({ value, label, icon: Icon }) => (
              <DropdownMenuItem key={value} onSelect={() => setTheme(value)} aria-checked={theme === value} role="menuitemradio">
                <Icon /> {label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" className="gap-2 px-2.5" aria-label="Menú de usuario">
              <UserRound />
              <span className="hidden max-w-40 truncate md:inline">{me?.email}</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>
              <p className="truncate font-medium text-foreground">{me?.email}</p>
              <div className="mt-1.5 flex gap-1.5">
                {me?.role && <Badge>{ROLE_LABELS[me.role]}</Badge>}
                {me?.area && <Badge variant="outline">Área: {me.area}</Badge>}
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => void signOut()}>
              <LogOut /> Cerrar sesión
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
