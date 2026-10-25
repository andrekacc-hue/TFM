"""Genera el paquete de la app de Teams (manifest.json + iconos) listo para cargar.

    python scripts/package_teams_app.py            # usa MICROSOFT_APP_ID del .env

Salida: teams-bot/manifest/build/soporte-ti-teams.zip (no se versiona).
Con --icons regenera los iconos (color 192x192 y contorno 32x32, requisitos de Teams).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = ROOT / "teams-bot" / "manifest"
BUILD = MANIFEST_DIR / "build"
GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
TEAL = (15, 118, 110)


def make_icons() -> None:
    """Icono a color (fondo verde azulado, burbuja de chat) y contorno blanco transparente."""
    from PIL import Image, ImageDraw

    color = Image.new("RGBA", (192, 192), TEAL + (255,))
    d = ImageDraw.Draw(color)
    d.rounded_rectangle((36, 44, 156, 128), radius=22, fill="white")
    d.polygon([(64, 124), (64, 152), (92, 126)], fill="white")
    for i, width in enumerate((84, 64, 44)):
        y = 62 + i * 20
        d.rounded_rectangle((54, y, 54 + width, y + 9), radius=4, fill=TEAL + (255,))
    d.ellipse((126, 96, 146, 116), fill=(94, 234, 212, 255))
    color.save(MANIFEST_DIR / "color.png")

    outline = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    o = ImageDraw.Draw(outline)
    o.rounded_rectangle((4, 6, 28, 22), radius=4, outline="white", width=2)
    o.polygon([(9, 21), (9, 28), (15, 21)], fill="white")
    o.line((9, 12, 22, 12), fill="white", width=2)
    o.line((9, 16, 18, 16), fill="white", width=2)
    outline.save(MANIFEST_DIR / "outline.png")
    print("✔ iconos generados (color.png 192x192, outline.png 32x32)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--icons", action="store_true", help="Regenerar los iconos")
    parser.add_argument("--app-id", help="App ID de Azure Bot (por defecto MICROSOFT_APP_ID del .env)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    if args.icons:
        make_icons()

    app_id = (args.app_id or dotenv_values(ROOT / ".env").get("MICROSOFT_APP_ID") or "").strip()
    if not GUID.match(app_id):
        print("✖ Define MICROSOFT_APP_ID (GUID del registro en Azure Bot Service) en .env o con --app-id", file=sys.stderr)
        return 1

    manifest = json.loads((MANIFEST_DIR / "manifest.json").read_text(encoding="utf-8").replace("{{MICROSOFT_APP_ID}}", app_id))
    BUILD.mkdir(exist_ok=True)
    target = BUILD / "soporte-ti-teams.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.write(MANIFEST_DIR / "color.png", "color.png")
        zf.write(MANIFEST_DIR / "outline.png", "outline.png")
    print(f"✔ {target.relative_to(ROOT)} · app {manifest['name']['short']} · bot {app_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
