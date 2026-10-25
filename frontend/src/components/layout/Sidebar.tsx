import * as Dialog from "@radix-ui/react-dialog";
import { Bot, X } from "lucide-react";
import { NavLink } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { env } from "@/lib/env";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import { hasRole } from "@/types/auth";

import { NAV_ITEMS } from "./navigation";

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
        <Bot className="size-5" aria-hidden />
      </div>
      <div className="leading-tight">
        <p className="text-sm font-semibold">{env.appName}</p>
        <p className="text-xs text-muted-foreground">Base de conocimientos IA</p>
      </div>
    </div>
  );
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const { me } = useAuth();
  const items = NAV_ITEMS.filter((item) => hasRole(me?.role, item.minRole));
  return (
    <nav aria-label="Navegación principal" className="flex flex-col gap-1">
      {items.map(({ to, label, icon: Icon, description }) => (
        <NavLink
          key={to}
          to={to}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "group flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              isActive ? "bg-primary text-primary-foreground shadow-sm" : "text-sidebar-foreground/80 hover:bg-accent hover:text-accent-foreground",
            )
          }
        >
          <Icon className="size-4 shrink-0" aria-hidden />
          <span className="flex-1">{label}</span>
          <span className="sr-only">: {description}</span>
        </NavLink>
      ))}
    </nav>
  );
}

function Footer() {
  return (
    <p className="px-2 text-[11px] leading-snug text-muted-foreground">
      TFM · Máster en IA (UNIR)
      <br />
      Respuestas con fuentes verificables
    </p>
  );
}

/** Lateral fijo en escritorio; cajón accesible (Radix Dialog) en móvil. */
export function Sidebar() {
  const open = useUiStore((s) => s.sidebarOpen);
  const setOpen = useUiStore((s) => s.setSidebarOpen);

  return (
    <>
      <aside className="hidden w-64 shrink-0 flex-col gap-6 border-r bg-sidebar px-3 py-5 lg:flex">
        <Brand />
        <NavList />
        <div className="mt-auto">
          <Footer />
        </div>
      </aside>

      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40 lg:hidden" />
          <Dialog.Content
            className="fixed inset-y-0 left-0 z-50 flex w-72 flex-col gap-6 border-r bg-sidebar px-3 py-5 shadow-xl data-[state=open]:animate-in data-[state=open]:slide-in-from-left lg:hidden"
            aria-describedby={undefined}
          >
            <Dialog.Title className="sr-only">Menú</Dialog.Title>
            <div className="flex items-center justify-between">
              <Brand />
              <Dialog.Close className="rounded-md p-1.5 hover:bg-accent" aria-label="Cerrar menú">
                <X className="size-5" />
              </Dialog.Close>
            </div>
            <NavList onNavigate={() => setOpen(false)} />
            <div className="mt-auto">
              <Footer />
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
