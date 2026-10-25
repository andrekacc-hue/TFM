/** Permisos por rol en la interfaz, login y validaciones de formularios. */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/fixtures";
import type { Me } from "@/types/auth";

const auth = {
  session: null as unknown,
  me: undefined as Me | undefined,
  loading: false,
  meError: null as Error | null,
  can: (min: string) => {
    const rank = { viewer: 1, editor: 2, admin: 3 } as Record<string, number>;
    return (rank[auth.me?.role ?? ""] ?? 0) >= (rank[min] ?? 99);
  },
  signIn: vi.fn(),
  signInWithMicrosoft: vi.fn(),
  signOut: vi.fn(),
};
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => auth }));
vi.mock("@/lib/supabase", () => ({ supabase: {} }));

import { DocumentStatusBadge } from "./documents/DocumentStatusBadge";
import { uploadSchema, validateFile } from "./documents/DocumentUploader";
import { incidentSchema } from "./incidents/IncidentForm";
import { ProtectedRoute, RequireRole } from "./layout/ProtectedRoute";
import { Sidebar } from "./layout/Sidebar";
import Login from "@/pages/Login";

function as(role: Me["role"], area = "operaciones") {
  auth.session = { access_token: "t" };
  auth.me = { user_id: "u1", email: "ana@banco.test", role, area };
}

beforeEach(() => {
  auth.session = null;
  auth.me = undefined;
  auth.meError = null;
  auth.signIn.mockReset();
});

describe("navegación por rol", () => {
  it("un viewer no ve Dashboard ni Evaluación", () => {
    as("viewer");
    renderWithProviders(<Sidebar />);
    const nav = screen.getByRole("navigation", { name: "Navegación principal" });
    expect(nav).toHaveTextContent("Consulta IA");
    expect(nav).not.toHaveTextContent("Dashboard");
    expect(nav).not.toHaveTextContent("Evaluación");
  });

  it("un editor ve todas las secciones", () => {
    as("editor");
    renderWithProviders(<Sidebar />);
    for (const label of ["Dashboard", "Consulta IA", "Documentos", "Incidentes", "Evaluación", "Configuración"]) {
      expect(screen.getByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
    }
  });

  it("RequireRole bloquea a quien no tiene el rol", () => {
    as("viewer");
    renderWithProviders(
      <RequireRole minimum="editor">
        <p>Contenido privado</p>
      </RequireRole>,
    );
    expect(screen.getByText("Acceso restringido")).toBeInTheDocument();
    expect(screen.queryByText("Contenido privado")).not.toBeInTheDocument();
  });
});

describe("ProtectedRoute", () => {
  it("sin sesión redirige al login", () => {
    renderWithProviders(
      <Routes>
        <Route path="/login" element={<p>Pantalla de login</p>} />
        <Route path="/documentos" element={<ProtectedRoute><p>Documentos</p></ProtectedRoute>} />
      </Routes>,
      { route: "/documentos" },
    );
    expect(screen.getByText("Pantalla de login")).toBeInTheDocument();
  });

  it("con sesión y perfil muestra el contenido", () => {
    as("viewer");
    renderWithProviders(<ProtectedRoute><p>Documentos</p></ProtectedRoute>);
    expect(screen.getByText("Documentos")).toBeInTheDocument();
  });

  it("si el perfil falla muestra el error y permite salir", () => {
    auth.session = { access_token: "t" };
    auth.meError = new Error("El usuario no tiene perfil de aplicación");
    renderWithProviders(<ProtectedRoute><p>Documentos</p></ProtectedRoute>);
    expect(screen.getByRole("alert")).toHaveTextContent("no tiene perfil");
    expect(screen.getByRole("button", { name: /Volver al inicio de sesión/ })).toBeInTheDocument();
  });
});

describe("Login", () => {
  it("valida el formulario antes de llamar a Supabase", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Login />);
    await user.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByText("Ingresa tu correo")).toBeInTheDocument();
    expect(screen.getByText("Mínimo 6 caracteres")).toBeInTheDocument();
    expect(screen.getByLabelText("Correo electrónico")).toHaveAttribute("aria-invalid", "true");
    expect(auth.signIn).not.toHaveBeenCalled();
  });

  it("muestra el error de credenciales", async () => {
    auth.signIn.mockRejectedValueOnce(new Error("Correo o contraseña incorrectos"));
    const user = userEvent.setup();
    renderWithProviders(<Login />);
    await user.type(screen.getByLabelText("Correo electrónico"), "ana@banco.test");
    await user.type(screen.getByLabelText("Contraseña"), "secreta123");
    await user.click(screen.getByRole("button", { name: "Entrar" }));
    expect(auth.signIn).toHaveBeenCalledWith("ana@banco.test", "secreta123");
    expect(await screen.findByRole("alert")).toHaveTextContent("Correo o contraseña incorrectos");
  });
});

describe("validaciones", () => {
  it("archivos admitidos", () => {
    expect(validateFile(new File(["x"], "manual.PDF"))).toBeNull();
    expect(validateFile(new File(["x"], "foto.png"))).toMatch(/no soportado/);
    expect(validateFile(new File([], "vacio.md"))).toMatch(/vacío/);
  });

  it("formulario de subida y de incidente", () => {
    expect(uploadSchema.safeParse({ sourceType: "manual", area: "operaciones" }).success).toBe(true);
    expect(uploadSchema.safeParse({ sourceType: "manual", area: "Operaciones TI" }).success).toBe(false);
    const incident = { code: "INC-2026-0042", system_affected: "Core", symptom: "El batch no termina a tiempo", severity: "alta", resolved: false };
    expect(incidentSchema.safeParse(incident).success).toBe(true);
    expect(incidentSchema.safeParse({ ...incident, code: "INC 42!" }).success).toBe(false);
  });

  it("insignias de estado", () => {
    renderWithProviders(<DocumentStatusBadge status="processing" />);
    expect(screen.getByLabelText("Estado: Procesando")).toBeInTheDocument();
  });
});
