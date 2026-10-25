import { lazy } from "react";
import { createBrowserRouter, type RouteObject } from "react-router-dom";

import { AppLayout } from "@/components/layout/AppLayout";
import { HomeRedirect, ProtectedRoute } from "@/components/layout/ProtectedRoute";

// Carga diferida por página: el bundle inicial solo incluye el login y el layout
const Login = lazy(() => import("@/pages/Login"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const ConsultaIA = lazy(() => import("@/pages/ConsultaIA"));
const Documentos = lazy(() => import("@/pages/Documentos"));
const Incidentes = lazy(() => import("@/pages/Incidentes"));
const Evaluacion = lazy(() => import("@/pages/Evaluacion"));
const Configuracion = lazy(() => import("@/pages/Configuracion"));
const NotFound = lazy(() => import("@/pages/NotFound"));

export const routes: RouteObject[] = [
  { path: "/login", element: <Login /> },
  {
    path: "/",
    element: (
      <ProtectedRoute>
        <AppLayout />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <HomeRedirect /> },
      { path: "dashboard", element: <Dashboard /> },
      { path: "consulta", element: <ConsultaIA /> },
      { path: "documentos", element: <Documentos /> },
      { path: "incidentes", element: <Incidentes /> },
      { path: "evaluacion", element: <Evaluacion /> },
      { path: "configuracion", element: <Configuracion /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
