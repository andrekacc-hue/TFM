# FAQ-VPN-001 Acceso remoto para guardias de TI

## ¿Quién puede usar la VPN de guardia?

Solo el personal de TI Producción incluido en el rol de guardia vigente. El acceso se habilita
automáticamente al inicio del turno y se revoca al finalizarlo.

## ¿Qué hago si la VPN rechaza mi conexión con el error VPN-403?

El error **VPN-403** indica que tu usuario no está en el rol de guardia activo. Verifica en el
calendario de guardias que el turno esté asignado a tu nombre. Si es correcto, solicita al
coordinador de guardia que actualice el rol; el cambio se aplica en un máximo de 10 minutos.

## ¿Y si el error es VPN-TIMEOUT?

Indica que el concentrador VPN no respondió. Comprueba tu conexión a internet y reintenta con
el perfil secundario `vpn-guardia-2`. Si ambos perfiles fallan, reporta el incidente a la Mesa
de Servicio indicando la hora y el perfil utilizado.

## ¿Puedo compartir mi segundo factor (MFA) con otro guardia?

No. El segundo factor es personal e intransferible y su uso compartido es una falta grave según
la política de seguridad de la información.
