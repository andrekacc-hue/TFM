import { Activity, UsersRound } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/AppLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, Skeleton, Table, Td, Th } from "@/components/ui/feedback";
import { Input, Select } from "@/components/ui/form-controls";
import { useProfiles, useUpdateProfile } from "@/hooks/useAdmin";
import { useAuth } from "@/hooks/useAuth";
import { useSystemHealth } from "@/hooks/useMetrics";
import { AREA_PATTERN, cn } from "@/lib/utils";
import { useUiStore, type Theme } from "@/stores/ui-store";
import { ROLE_LABELS, type Role } from "@/types/auth";
import type { Profile } from "@/types/domain";

function ProfileRow({ profile, isSelf }: { profile: Profile; isSelf: boolean }) {
  const update = useUpdateProfile();
  const [role, setRole] = useState<Role>(profile.role);
  const [area, setArea] = useState(profile.area);
  const dirty = role !== profile.role || area !== profile.area;
  const areaValid = AREA_PATTERN.test(area);

  return (
    <tr>
      <Td>
        <p className="font-medium">{profile.full_name || profile.email}</p>
        <p className="text-xs text-muted-foreground">{profile.email}</p>
      </Td>
      <Td>
        <Select aria-label={`Rol de ${profile.email}`} value={role} disabled={isSelf} onChange={(e) => setRole(e.target.value as Role)} className="w-44">
          {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}
            </option>
          ))}
        </Select>
      </Td>
      <Td>
        <Input aria-label={`Área de ${profile.email}`} aria-invalid={!areaValid} value={area} onChange={(e) => setArea(e.target.value.toLowerCase())} className="w-36" />
      </Td>
      <Td className="text-right">
        <Button
          size="sm"
          disabled={!dirty || !areaValid}
          loading={update.isPending}
          onClick={() =>
            update.mutate(
              { id: profile.id, role, area },
              { onSuccess: () => toast.success(`Permisos de ${profile.email} actualizados`), onError: (e) => toast.error(e.message) },
            )
          }
        >
          Guardar
        </Button>
      </Td>
    </tr>
  );
}

function UsersAdmin() {
  const { me } = useAuth();
  const { data, isLoading, error } = useProfiles(true);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <UsersRound className="size-4 text-primary" aria-hidden /> Usuarios y permisos
        </CardTitle>
        <CardDescription>
          El rol define qué puede hacer cada usuario; el área, qué documentos ve. Los cambios se aplican en menos de un minuto.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-32" />
        ) : error ? (
          <ErrorState message={error.message} />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Usuario</Th>
                <Th>Rol</Th>
                <Th>Área</Th>
                <Th className="w-0">
                  <span className="sr-only">Acciones</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {data?.map((profile) => (
                <ProfileRow key={profile.id} profile={profile} isSelf={profile.id === me?.user_id} />
              ))}
            </tbody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function SystemStatus() {
  const { data, isLoading } = useSystemHealth();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="size-4 text-primary" aria-hidden /> Estado del sistema
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-24" />
        ) : (
          <ul className="space-y-2">
            {Object.entries(data?.checks ?? {}).map(([name, status]) => (
              <li key={name} className="flex items-center justify-between text-sm">
                <span>{name}</span>
                <Badge variant={status.startsWith("ok") ? "success" : "destructive"}>{status.startsWith("ok") ? "Operativo" : "Error"}</Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

const THEMES: { value: Theme; label: string }[] = [
  { value: "light", label: "Claro" },
  { value: "dark", label: "Oscuro" },
  { value: "system", label: "Según el sistema" },
];

export default function Configuracion() {
  const { me, can } = useAuth();
  const { theme, setTheme } = useUiStore();
  return (
    <>
      <PageHeader title="Configuración" description="Tu cuenta, preferencias y administración" />
      <div className="space-y-6">
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Mi cuenta</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-[7rem_1fr] gap-y-2 text-sm">
                <dt className="text-muted-foreground">Correo</dt>
                <dd className="truncate">{me?.email}</dd>
                <dt className="text-muted-foreground">Rol</dt>
                <dd>{me?.role && <Badge>{ROLE_LABELS[me.role]}</Badge>}</dd>
                <dt className="text-muted-foreground">Área</dt>
                <dd>{me?.area}</dd>
              </dl>
              <fieldset className="mt-5">
                <legend className="mb-2 text-sm font-medium">Tema</legend>
                <div className="flex gap-2">
                  {THEMES.map((t) => (
                    <Button key={t.value} type="button" variant="outline" size="sm" aria-pressed={theme === t.value} onClick={() => setTheme(t.value)} className={cn(theme === t.value && "border-primary bg-accent")}>
                      {t.label}
                    </Button>
                  ))}
                </div>
              </fieldset>
            </CardContent>
          </Card>
          <SystemStatus />
        </div>
        {can("admin") && <UsersAdmin />}
      </div>
    </>
  );
}
