import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({ supabase: {} }));

import { stablePeriod } from "@/hooks/useMetrics";
import { plural } from "@/lib/utils";
import type { TimeseriesPoint } from "@/types/api";

import { bucketLabel, fillBuckets } from "./UsageChart";

describe("stablePeriod", () => {
  it("redondea el final HACIA ARRIBA: incluye las consultas del minuto en curso", () => {
    const now = new Date("2026-10-25T15:42:37.500Z");
    const { from, to } = stablePeriod(7, now);
    expect(to).toBe("2026-10-25T15:43:00.000Z");
    expect(new Date(to).getTime()).toBeGreaterThan(now.getTime());
    expect(from).toBe("2026-10-18T15:43:00.000Z");
  });

  it("es estable dentro del mismo minuto (clave de caché)", () => {
    expect(stablePeriod(7, new Date("2026-10-25T15:42:01Z"))).toEqual(stablePeriod(7, new Date("2026-10-25T15:42:59Z")));
  });
});

describe("fillBuckets", () => {
  const point = (bucket: string, queries: number): TimeseriesPoint => ({
    bucket,
    queries,
    abstained: 0,
    avg_latency_ms: 2000,
    p95_latency_ms: 3000,
    positive_feedback: 0,
    negative_feedback: 0,
  });

  it("completa los días sin consultas con ceros y conserva los datos", () => {
    const now = new Date("2026-10-25T12:00:00Z");
    const filled = fillBuckets([point("2026-10-24T00:00:00+00:00", 8)], 7, now);
    expect(filled).toHaveLength(7);
    expect(filled[0]?.bucket).toBe("2026-10-19T00:00:00.000Z");
    expect(filled[5]?.queries).toBe(8);
    expect(filled.filter((p) => p.queries === 0)).toHaveLength(6);
  });

  it("24 intervalos horarios para el último día", () => {
    expect(fillBuckets([], 1, new Date("2026-10-25T12:30:00Z"))).toHaveLength(24);
  });

  it("las etiquetas de día se muestran en UTC (como agrupa PostgreSQL)", () => {
    expect(bucketLabel("2026-10-24T00:00:00Z", false)).toMatch(/24/);
  });
});

describe("plural", () => {
  it("singular y plural", () => {
    expect(plural(1, "usuario")).toBe("1 usuario");
    expect(plural(3, "usuario")).toBe("3 usuarios");
    expect(plural(1, "valoración", "valoraciones")).toBe("1 valoración");
    expect(plural(0, "valoración", "valoraciones")).toBe("0 valoraciones");
  });
});
