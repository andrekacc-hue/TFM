import { BarChart3, FileText, FlaskConical, LifeBuoy, MessageSquareText, Settings, type LucideIcon } from "lucide-react";

import type { Role } from "@/types/auth";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Rol mínimo para ver la sección (coincide con la autorización del gateway). */
  minRole: Role;
  description: string;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: BarChart3, minRole: "editor", description: "Uso, latencia y satisfacción" },
  { to: "/consulta", label: "Consulta IA", icon: MessageSquareText, minRole: "viewer", description: "Pregunta al asistente" },
  { to: "/documentos", label: "Documentos", icon: FileText, minRole: "viewer", description: "Base de conocimientos" },
  { to: "/incidentes", label: "Incidentes", icon: LifeBuoy, minRole: "viewer", description: "Histórico de incidentes" },
  { to: "/evaluacion", label: "Evaluación", icon: FlaskConical, minRole: "editor", description: "Calidad del asistente" },
  { to: "/configuracion", label: "Configuración", icon: Settings, minRole: "viewer", description: "Cuenta y usuarios" },
];
