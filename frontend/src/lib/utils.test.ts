import { describe, expect, it } from "vitest";

import { hasRole } from "@/types/auth";

import { cn, formatBytes, formatDuration, formatPercent, formatRelative, sectionLabel } from "./utils";

describe("formatos", () => {
  it("formatDuration usa ms o segundos", () => {
    expect(formatDuration(850)).toBe("850 ms");
    expect(formatDuration(2340)).toBe("2,3 s");
    expect(formatDuration(null)).toBe("—");
  });

  it("formatPercent", () => {
    expect(formatPercent(0.25)).toMatch(/25\s?%/);
    expect(formatPercent(undefined)).toBe("—");
  });

  it("formatBytes", () => {
    expect(formatBytes(1536)).toBe("1,5 KB");
    expect(formatBytes(0)).toBe("—");
  });

  it("formatRelative", () => {
    const now = new Date("2026-10-25T12:00:00Z");
    expect(formatRelative("2026-10-25T11:55:00Z", now)).toBe("hace 5 minutos");
    expect(formatRelative("2026-10-24T12:00:00Z", now)).toBe("ayer");
  });

  it("sectionLabel prioriza la sección real y añade la página", () => {
    expect(sectionLabel("Escalamiento", 2, 4)).toBe("Escalamiento (pág. 4)");
    expect(sectionLabel(null, 2, null)).toBe("fragmento 3");
    expect(sectionLabel("  ", 0, 1)).toBe("fragmento 1 (pág. 1)");
  });

  it("cn resuelve conflictos de Tailwind", () => {
    expect(cn("px-2", "px-4", false && "hidden")).toBe("px-4");
  });
});

describe("roles", () => {
  it("jerarquía viewer < editor < admin", () => {
    expect(hasRole("admin", "editor")).toBe(true);
    expect(hasRole("editor", "editor")).toBe(true);
    expect(hasRole("viewer", "editor")).toBe(false);
    expect(hasRole(null, "viewer")).toBe(false);
  });
});
