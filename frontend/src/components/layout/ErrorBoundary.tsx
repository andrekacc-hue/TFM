import { Component, type ErrorInfo, type ReactNode } from "react";

import { ErrorState } from "@/components/ui/feedback";

interface State {
  error: Error | null;
}

/** Captura errores de renderizado de una página sin tumbar toda la aplicación. */
export class ErrorBoundary extends Component<{ children: ReactNode; fallback?: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Error de interfaz", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        this.props.fallback ?? (
          <ErrorState
            message="Ocurrió un error inesperado al mostrar esta sección."
            onRetry={() => this.setState({ error: null })}
          />
        )
      );
    }
    return this.props.children;
  }
}
