import { ChatInterface } from "@/components/chat/ChatInterface";
import { PageHeader } from "@/components/layout/AppLayout";
import { useAuth } from "@/hooks/useAuth";

export default function ConsultaIA() {
  const { me } = useAuth();
  return (
    <>
      <PageHeader
        title="Consulta IA"
        description={`Asistente de soporte técnico · busca en la documentación de ${me?.area === "general" ? "todas las áreas permitidas" : `${me?.area} y general`}`}
      />
      <ChatInterface />
    </>
  );
}
