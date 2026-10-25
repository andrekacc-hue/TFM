"""Corpus de demostración (ficticio) para probar el rag-service antes de la Fase 3.

Los documentos están marcados con ``metadata.demo = true`` y usan UUID fijos para que
``seed-demo`` sea idempotente y ``clean-demo`` los elimine sin tocar datos reales.
"""

from __future__ import annotations

DEMO_DOCUMENTS = [
    {
        "id": "de300000-0000-4000-8000-000000000001",
        "title": "PROC-OPS-014 Reinicio del batch de cierre diario",
        "source_type": "procedimiento",
        "area": "operaciones",
        "paragraphs": [
            "Objetivo: restablecer el proceso batch de cierre diario del core bancario cuando queda "
            "en estado RUNNING más allá de la ventana de las 02:00 o finaliza con estado ABEND.",
            "Paso 1 — Diagnóstico de bloqueos: consultar en la consola de monitoreo de base de datos "
            "las sesiones bloqueantes sobre las tablas de saldos y movimientos. Si existe una "
            "transacción de conciliación sin confirmar, registrar el identificador de sesión y "
            "notificar al DBA de turno. El operador de TI Producción no debe cancelar sesiones por "
            "su cuenta.",
            "Paso 2 — Revisión de logs: revisar el log del job en el planificador (scheduler) y "
            "buscar los códigos CIE-201 (timeout de conexión) o CIE-305 (registro duplicado). "
            "CIE-201 indica problema de conectividad con la base de datos; CIE-305 requiere "
            "depuración de datos por parte de Soporte Aplicativo antes de relanzar.",
            "Paso 3 — Relanzamiento: con la aprobación del DBA, relanzar el job desde el último "
            "checkpoint confirmado usando la opción 'Restart from checkpoint' del planificador. "
            "Nunca relanzar desde el inicio, porque duplicaría los asientos contables ya procesados.",
            "Paso 4 — Validación y escalamiento: validar que los totales de control coincidan con el "
            "reporte de cuadre. Si el job vuelve a fallar o han pasado más de 45 minutos desde el "
            "incidente, escalar al nivel 2 (Soporte Aplicativo Core) y abrir un incidente de "
            "severidad crítica.",
        ],
    },
    {
        "id": "de300000-0000-4000-8000-000000000002",
        "title": "MAN-RED-007 Contingencia del enlace del switch transaccional ATM",
        "source_type": "manual",
        "area": "operaciones",
        "paragraphs": [
            "Alcance: este manual describe la actuación ante la pérdida de comunicación entre la red "
            "de cajeros automáticos (ATM) y el switch transaccional del proveedor.",
            "Síntomas: los retiros son rechazados con el código de respuesta 91 (emisor o switch no "
            "disponible) de forma masiva en varios cajeros a la vez. Si el código 91 aparece en un "
            "solo cajero, el problema es local del equipo y se gestiona con el proveedor de "
            "mantenimiento de ATM.",
            "Activación del enlace de contingencia: verificar en el panel de red el estado del enlace "
            "principal. Si está caído, activar el enlace de respaldo desde la consola de "
            "comunicaciones siguiendo la lista de verificación CL-RED-03 y confirmar que las "
            "transacciones de prueba se aprueban.",
            "Escalamiento: si el enlace de contingencia no restablece el servicio en 15 minutos, "
            "escalar al proveedor del switch según la matriz de escalamiento y notificar al Centro de "
            "Operaciones de Seguridad. Registrar el incidente con severidad alta.",
        ],
    },
    {
        "id": "de300000-0000-4000-8000-000000000003",
        "title": "FAQ-BEL-002 Errores de acceso a Banca en Línea",
        "source_type": "faq",
        "area": "general",
        "paragraphs": [
            "¿Qué significa el error HTTP 502 al iniciar sesión en la banca web? Indica que el "
            "balanceador no obtuvo respuesta del servicio de autenticación. La causa más habitual es "
            "el agotamiento del pool de conexiones tras un despliegue.",
            "¿Qué hacer ante un 502 masivo? Confirmar en el monitoreo de aplicaciones el número de "
            "conexiones activas del servicio de autenticación. Si el pool está agotado, solicitar a "
            "Soporte Aplicativo el reinicio ordenado de los nodos, uno por uno, para no cortar el "
            "servicio por completo.",
            "¿Cómo se restablece la contraseña de un cliente? El restablecimiento lo realiza el propio "
            "cliente desde la opción 'Olvidé mi contraseña' o el Contact Center tras validar su "
            "identidad. TI Producción nunca solicita ni conoce contraseñas de clientes.",
        ],
    },
]
