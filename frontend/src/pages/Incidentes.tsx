import { Plus } from "lucide-react";
import { useState } from "react";

import { IncidentForm } from "@/components/incidents/IncidentForm";
import { IncidentTable } from "@/components/incidents/IncidentTable";
import { PageHeader } from "@/components/layout/AppLayout";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import type { Incident } from "@/types/domain";

export default function Incidentes() {
  const { can } = useAuth();
  const [editing, setEditing] = useState<Incident | undefined>();
  const [open, setOpen] = useState(false);

  return (
    <>
      <PageHeader
        title="Incidentes"
        description="Histórico de incidentes de TI Producción con su diagnóstico y resolución"
        actions={
          can("editor") && (
            <Button
              onClick={() => {
                setEditing(undefined);
                setOpen(true);
              }}
            >
              <Plus /> Registrar incidente
            </Button>
          )
        }
      />
      <IncidentTable
        onEdit={(incident) => {
          setEditing(incident);
          setOpen(true);
        }}
      />
      <IncidentForm open={open} onOpenChange={setOpen} incident={editing} />
    </>
  );
}
