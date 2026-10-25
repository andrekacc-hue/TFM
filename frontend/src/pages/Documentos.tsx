import { DocumentList } from "@/components/documents/DocumentList";
import { DocumentUploader } from "@/components/documents/DocumentUploader";
import { PageHeader } from "@/components/layout/AppLayout";
import { useAuth } from "@/hooks/useAuth";

export default function Documentos() {
  const { can } = useAuth();
  return (
    <>
      <PageHeader title="Documentos" description="Manuales, procedimientos, incidentes y FAQ indexados para el asistente" />
      <div className={can("editor") ? "grid gap-6 xl:grid-cols-[1fr_22rem]" : undefined}>
        <DocumentList />
        {can("editor") && (
          <div className="xl:order-last">
            <DocumentUploader />
          </div>
        )}
      </div>
    </>
  );
}
