/**
 * Conversación con el asistente.
 *
 * Se guarda en sessionStorage (no localStorage): las preguntas pueden contener información
 * operativa del banco y no deben sobrevivir al cierre del navegador.
 */
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { QueryResponse } from "@/types/api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  response?: QueryResponse;
  error?: string;
  pending?: boolean;
  rating?: 1 | -1;
}

interface ChatState {
  messages: ChatMessage[];
  ask: (question: string) => { questionId: string; answerId: string };
  resolve: (answerId: string, response: QueryResponse) => void;
  fail: (answerId: string, error: string) => void;
  rate: (answerId: string, rating: 1 | -1) => void;
  clear: () => void;
}

const id = () => crypto.randomUUID();

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      messages: [],
      ask: (question) => {
        const questionId = id();
        const answerId = id();
        const now = new Date().toISOString();
        set((state) => ({
          messages: [
            ...state.messages,
            { id: questionId, role: "user", content: question, createdAt: now },
            { id: answerId, role: "assistant", content: "", createdAt: now, pending: true },
          ],
        }));
        return { questionId, answerId };
      },
      resolve: (answerId, response) =>
        set((state) => ({
          messages: state.messages.map((m) =>
            m.id === answerId ? { ...m, pending: false, content: response.answer, response, createdAt: new Date().toISOString() } : m,
          ),
        })),
      fail: (answerId, error) =>
        set((state) => ({ messages: state.messages.map((m) => (m.id === answerId ? { ...m, pending: false, error } : m)) })),
      rate: (answerId, rating) =>
        set((state) => ({ messages: state.messages.map((m) => (m.id === answerId ? { ...m, rating } : m)) })),
      clear: () => set({ messages: [] }),
    }),
    {
      name: "chat-store",
      storage: createJSONStorage(() => sessionStorage),
      // Una respuesta "pendiente" no se puede retomar tras recargar
      partialize: (state) => ({ messages: state.messages.filter((m) => !m.pending) }),
    },
  ),
);
