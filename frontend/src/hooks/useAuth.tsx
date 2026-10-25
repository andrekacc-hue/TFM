/**
 * Sesión (Supabase Auth) y perfil de aplicación (/api/v1/me: rol y área vigentes).
 */
import type { Session } from "@supabase/supabase-js";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { apiRequest } from "@/lib/api-client";
import { supabase } from "@/lib/supabase";
import { useChatStore } from "@/stores/chat-store";
import { hasRole, type Me, type Role } from "@/types/auth";

interface AuthContextValue {
  session: Session | null;
  me: Me | undefined;
  loading: boolean;
  meError: Error | null;
  can: (minimum: Role) => boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signInWithMicrosoft: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [session, setSession] = useState<Session | null>(null);
  const [sessionLoading, setSessionLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setSessionLoading(false);
    });
    const { data } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => data.subscription.unsubscribe();
  }, []);

  const userId = session?.user.id;
  const meQuery = useQuery({
    queryKey: ["me", userId],
    queryFn: () => apiRequest<Me>("/api/v1/me"),
    enabled: !!userId,
    staleTime: 60_000,
  });

  const signIn = useCallback(async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) {
      throw new Error(error.message === "Invalid login credentials" ? "Correo o contraseña incorrectos" : error.message);
    }
  }, []);

  const signInWithMicrosoft = useCallback(async () => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "azure",
      options: { scopes: "email", redirectTo: window.location.origin },
    });
    if (error) throw new Error(error.message);
  }, []);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    queryClient.clear();
    useChatStore.getState().clear();
  }, [queryClient]);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      me: meQuery.data,
      loading: sessionLoading || (!!userId && meQuery.isLoading),
      meError: meQuery.error,
      can: (minimum) => hasRole(meQuery.data?.role, minimum),
      signIn,
      signInWithMicrosoft,
      signOut,
    }),
    [session, meQuery.data, meQuery.isLoading, meQuery.error, sessionLoading, userId, signIn, signInWithMicrosoft, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return context;
}
