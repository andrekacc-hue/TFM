-- =====================================================================
-- seed.sql — Datos de ejemplo (idempotente)
-- Los documentos y el golden dataset se cargan en fases posteriores
-- (scripts/seed_corpus.py y tests/golden_dataset.json).
-- =====================================================================

insert into tfm.incidents (code, system_affected, symptom, diagnosis, resolution, severity, resolved_at)
values
  ('INC-2026-0001', 'Core bancario',
   'El proceso batch de cierre diario no finaliza y queda en estado RUNNING después de las 02:00.',
   'Bloqueo en la tabla de saldos por una transacción de conciliación no confirmada.',
   'Identificar la sesión bloqueante, coordinar con el DBA de turno su cancelación y relanzar el paso de cierre desde el último checkpoint.',
   'critica', now() - interval '20 days'),
  ('INC-2026-0002', 'Banca en línea',
   'Usuarios reportan error HTTP 502 al iniciar sesión en la banca web.',
   'Pool de conexiones del servicio de autenticación agotado tras un despliegue.',
   'Reiniciar ordenadamente los nodos del servicio de autenticación y aumentar el tamaño del pool según el procedimiento de capacidad.',
   'alta', now() - interval '12 days'),
  ('INC-2026-0003', 'Cajeros automáticos (ATM)',
   'Retiros rechazados con código de respuesta 91 en una red de cajeros.',
   'Caída del enlace con el switch transaccional del proveedor.',
   'Activar el enlace de contingencia y escalar al proveedor según la matriz de escalamiento.',
   'alta', now() - interval '7 days'),
  ('INC-2026-0004', 'Transferencias interbancarias',
   'Lote de transferencias SPI queda pendiente de envío.',
   'Certificado de firma digital próximo a expirar no fue renovado.',
   'Renovar el certificado con el área de Seguridad y reenviar el lote desde la consola de pagos.',
   'media', now() - interval '3 days'),
  ('INC-2026-0005', 'Reportería regulatoria',
   'El reporte diario para el ente de control se genera vacío.',
   'Cambio de esquema en la vista de origen sin actualización del ETL.',
   'Actualizar el mapeo del ETL, regenerar el reporte y validar totales de control con Riesgos.',
   'baja', null)
on conflict (code) do nothing;
