export type Role = "viewer" | "editor" | "admin";

/** Usuario según /api/v1/me: rol y área vigentes en tfm.profiles. */
export interface Me {
  user_id: string | null;
  email: string | null;
  role: Role | null;
  area: string | null;
}

const RANK: Record<Role, number> = { viewer: 1, editor: 2, admin: 3 };

/** ¿El rol cumple el mínimo? (viewer < editor < admin) */
export function hasRole(role: Role | null | undefined, minimum: Role): boolean {
  return !!role && RANK[role] >= RANK[minimum];
}

export const ROLE_LABELS: Record<Role, string> = {
  viewer: "Consulta",
  editor: "Editor",
  admin: "Administrador",
};
