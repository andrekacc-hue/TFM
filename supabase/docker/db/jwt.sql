-- Publica el secreto JWT como setting de la BD (lo usan funciones internas).
-- Se ejecuta una sola vez, al inicializar el volumen de la BD.
\set jwt_secret `echo "$JWT_SECRET"`
\set jwt_exp `echo "$JWT_EXP"`

ALTER DATABASE postgres SET "app.settings.jwt_secret" TO :'jwt_secret';
ALTER DATABASE postgres SET "app.settings.jwt_exp" TO :'jwt_exp';
