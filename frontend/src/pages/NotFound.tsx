import { Compass } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/feedback";

export default function NotFound() {
  return (
    <EmptyState
      icon={Compass}
      title="Página no encontrada"
      description="La dirección no existe o fue movida."
      action={
        <Button asChild variant="outline" className="mt-2">
          <Link to="/">Volver al inicio</Link>
        </Button>
      }
    />
  );
}
