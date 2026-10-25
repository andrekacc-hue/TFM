"""Guardrails de entrada y salida.

Entrada:
  * bloquea intentos de *prompt injection* y de eludir controles de seguridad;
  * enmascara datos sensibles antes de que salgan hacia el LLM o se persistan
    (números de tarjeta válidos por Luhn, credenciales escritas en la pregunta).

Salida:
  * detecta la abstención del modelo;
  * redacta secretos que el modelo pudiera reproducir;
  * avisa si la respuesta no cita fuentes.

Son heurísticas deterministas y auditables (no un segundo LLM), adecuadas para un
entorno bancario donde cada bloqueo debe poder explicarse.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.core.prompts import ABSTENTION_MESSAGE

MAX_QUESTION_CHARS = 2000

# Patrones sobre texto normalizado (minúsculas, sin tildes)
_INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignorar_instrucciones": re.compile(
        r"\b(ignora|olvida|omite|descarta)\w*\s+(todas?\s+)?(las\s+|tus\s+)?"
        r"(instrucciones|reglas|indicaciones|restricciones)"
    ),
    "ignore_instructions": re.compile(r"\b(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above|your)\s+"),
    "revelar_prompt": re.compile(
        r"\b(revela|muestra|imprime|dime|reveal|show|print)\w*\s+(\w+\s+){0,3}(system\s*prompt|prompt\s+del?\s+sistema|tus\s+instrucciones)"
    ),
    "jailbreak": re.compile(r"\b(jailbreak|modo\s+desarrollador|developer\s+mode|\bdan\b\s+mode|sin\s+restricciones)\b"),
    "suplantar_rol": re.compile(r"\b(actua|act|comportate)\s+(como|as)\s+(si\s+fueras\s+)?(un\s+)?(administrador|root|admin|dba)\b"),
}

# Raíces verbales (\w*) para cubrir conjugaciones: "desactivo", "borré", "saltarme"...
_SECURITY_EVASION_PATTERNS: dict[str, re.Pattern[str]] = {
    "eludir_control": re.compile(
        r"\b(salt|evad|elud|burl|bypass|deshabilit|desactiv|apag)\w*\s+"
        r"(\w+\s+){0,3}(control|autenticacion|2fa|mfa|doble\s+factor|auditoria|firewall|antivirus|edr|dlp|monitoreo)"
    ),
    "borrar_rastro": re.compile(
        r"\b(borr|elimin|ocult|limpi)\w*\s+(\w+\s+){0,3}(rastro|evidencia|huellas|logs?\s+de\s+auditoria)"
    ),
    "obtener_credenciales": re.compile(
        r"\b(dame|dime|pasame|obten\w*|consegu\w*|consig\w*|cual\s+es)\s+(\w+\s+){0,3}"
        r"(contrasena|password|clave|credencial(es)?|token)\s+(\w+\s+){0,2}(de\s+)?(produccion|root|admin|administrador|dba|servidor|base\s+de\s+datos)"
    ),
    "escalar_privilegios": re.compile(r"\b(escal|elev)\w*\s+(mis\s+|los\s+)?privilegios\b"),
}

_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
# Solo con separador explícito (":" o "=") para no enmascarar frases como "la clave es reiniciar"
_INLINE_SECRET = re.compile(
    r"(?i)\b(contrase(?:ñ|n)a|password|passwd|pwd|clave|token|api[_-]?key|secret)\b(\s*[:=]\s*)(\S+)"
)
_OUTPUT_SECRETS = [
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT
    re.compile(r"\b(sk|sb_secret|sk-ant)[-_][A-Za-z0-9_-]{16,}\b"),  # claves de API
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def normalize(text: str) -> str:
    """Minúsculas, sin tildes y espacios colapsados (para comparar patrones)."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", without_accents).strip()


def _luhn_valid(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        n = int(ch)
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def mask_sensitive(text: str) -> tuple[str, list[str]]:
    """Enmascara tarjetas (Luhn) y credenciales escritas en línea.

    Returns:
        Texto enmascarado y lista de tipos de dato enmascarados.
    """
    found: list[str] = []

    def _card(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            found.append("tarjeta")
            return f"[TARJETA ****{digits[-4:]}]"
        return match.group(0)

    def _secret(match: re.Match[str]) -> str:
        found.append("credencial")
        return f"{match.group(1)}{match.group(2)}[REDACTADO]"

    masked = _CARD_CANDIDATE.sub(_card, text)
    masked = _INLINE_SECRET.sub(_secret, masked)
    return masked, sorted(set(found))


@dataclass
class InputCheck:
    """Resultado del guardrail de entrada."""

    allowed: bool
    question: str
    reason: str | None = None
    masked: list[str] = field(default_factory=list)


@dataclass
class OutputCheck:
    """Resultado del guardrail de salida."""

    answer: str
    abstained: bool
    has_citation: bool
    warnings: list[str] = field(default_factory=list)


def check_input(question: str) -> InputCheck:
    """Valida y sanea la pregunta del usuario.

    Args:
        question: Pregunta original.

    Returns:
        :class:`InputCheck`; si ``allowed`` es ``False``, ``reason`` indica la regla.
    """
    stripped = question.strip()
    if not stripped:
        return InputCheck(False, stripped, "pregunta_vacia")
    if len(stripped) > MAX_QUESTION_CHARS:
        return InputCheck(False, stripped[:MAX_QUESTION_CHARS], "pregunta_demasiado_larga")

    normalized = normalize(stripped)
    for name, pattern in _INJECTION_PATTERNS.items():
        if pattern.search(normalized):
            return InputCheck(False, stripped, f"prompt_injection:{name}")
    for name, pattern in _SECURITY_EVASION_PATTERNS.items():
        if pattern.search(normalized):
            return InputCheck(False, stripped, f"evasion_seguridad:{name}")

    masked, kinds = mask_sensitive(stripped)
    return InputCheck(True, masked, masked=kinds)


def is_abstention(answer: str) -> bool:
    """Indica si la respuesta es la frase de abstención (tolerando formato)."""
    return normalize(ABSTENTION_MESSAGE.split("\n")[0]) in normalize(answer)


def check_output(answer: str) -> OutputCheck:
    """Revisa la respuesta del LLM antes de entregarla.

    Args:
        answer: Texto generado.

    Returns:
        :class:`OutputCheck` con la respuesta (posiblemente redactada) y avisos.
    """
    warnings: list[str] = []
    text = answer.strip()

    if not text:
        return OutputCheck(ABSTENTION_MESSAGE, abstained=True, has_citation=False, warnings=["respuesta_vacia"])

    for pattern in _OUTPUT_SECRETS:
        if pattern.search(text):
            text = pattern.sub("[REDACTADO]", text)
            warnings.append("secreto_redactado")

    abstained = is_abstention(text)
    if abstained:
        # Normaliza a la frase exacta exigida por el prompt de sistema
        return OutputCheck(ABSTENTION_MESSAGE, abstained=True, has_citation=False, warnings=warnings)

    has_citation = "[fuente:" in text.lower()
    if not has_citation:
        warnings.append("sin_citas")
    return OutputCheck(text, abstained=False, has_citation=has_citation, warnings=warnings)
