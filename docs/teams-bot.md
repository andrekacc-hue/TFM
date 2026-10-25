# Bot de Microsoft Teams — Registro, despliegue y pruebas

El bot (`teams-bot/`) usa el **Microsoft 365 Agents SDK**, sucesor oficial del Bot Framework SDK
(el repositorio `botbuilder-python` fue archivado en enero de 2026 y Microsoft dejó de dar soporte
el 31/12/2025). El protocolo con Teams (Azure Bot Service + *Activities*) es el mismo.

```
Teams ──► Azure Bot Service ──► https://<túnel>/api/messages ──► teams-bot (:3978)
                                                                     │  X-Internal-Api-Key
                                                                     │  X-User-Email (correo del usuario de Teams)
                                                                     ▼
                                                              api-gateway ──► rag-service ──► Supabase
```

El bot actúa **en nombre del usuario de Teams**: obtiene su correo corporativo de la conversación y el
gateway aplica su rol y su área de `tfm.profiles`, igual que en el portal. Si el correo no está
registrado, el bot responde que pida acceso a un administrador.

---

## 0. Prueba local sin Azure (opcional)

El bot funciona en **modo anónimo** cuando `MICROSOFT_APP_ID` está vacío:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d teams-bot
Invoke-RestMethod http://localhost:3978/health      # "mode": "anonymous"
```

Con el **Bot Framework Emulator** (`winget install Microsoft.BotFrameworkEmulator`): *Open Bot* →
`http://localhost:3978/api/messages`, sin App ID. Para que el Emulator actúe con un usuario registrado,
define `BOT_DEFAULT_USER_EMAIL` en `.env` (p. ej. tu correo del portal) y reinicia el bot.

---

## 1. Requisitos

| Necesitas | Para qué | Coste |
|-----------|----------|-------|
| Cuenta de Azure | Registrar el bot (Azure Bot, plan **F0**) | Gratis. Con correo de UNIR: *Azure for Students* (sin tarjeta) |
| Teams con permiso para **cargar apps personalizadas** | Instalar el bot | Ver nota abajo |
| Cuenta de ngrok | Exponer `localhost:3978` con HTTPS | Gratis (incluye un dominio estático) |

> **Teams y apps personalizadas.** Las cuentas personales de Teams no permiten cargar apps propias. Opciones:
> el *sandbox* del Microsoft 365 Developer Program (si tu cuenta es elegible), una prueba gratuita de
> Microsoft 365 Business, o un tenant corporativo cuyo administrador habilite *"Upload custom apps"*
> (Teams Admin Center → Teams apps → Setup policies). Sin Teams, la prueba **Test in Web Chat** de Azure
> (paso 6) demuestra el bot igualmente.

---

## 2. ngrok: URL pública con HTTPS

```powershell
ngrok update                                   # la versión de winget es antigua
ngrok config add-authtoken <TU_AUTHTOKEN>      # https://dashboard.ngrok.com/get-started/your-authtoken
ngrok http 3978 --url=<tu-dominio>.ngrok-free.app   # dominio estático: Dashboard → Domains
```

Usa el **dominio estático** gratuito: así el endpoint de Azure no cambia cada vez que reinicias ngrok.
Guarda en `.env`: `BOT_PUBLIC_URL=https://<tu-dominio>.ngrok-free.app`.

---

## 3. Crear el Azure Bot

1. https://portal.azure.com → **Create a resource** → busca **Azure Bot** → *Create*.
2. Completa:
   - **Bot handle:** `soporte-ti-produbanco-tfm` (único global).
   - **Subscription / Resource group:** la tuya / nuevo `rg-soporte-tfm`.
   - **Pricing tier:** **F0 (Free)** (*Change plan*).
   - **Type of App:** **Single Tenant** (Microsoft ya no permite crear bots multitenant nuevos).
   - **Creation type:** *Create new Microsoft App ID*.
3. *Review + create* → *Create*. Al terminar, *Go to resource*.

## 4. Credenciales en `.env`

En el recurso: **Settings → Configuration**.

| Campo en Azure | Variable en `.env` |
|----------------|--------------------|
| Microsoft App ID | `MICROSOFT_APP_ID` |
| App Tenant ID | `MICROSOFT_APP_TENANT_ID` |
| *Manage Password* → **Certificates & secrets → New client secret** → copia el **Value** (se muestra una sola vez) | `MICROSOFT_APP_PASSWORD` |

En la misma pantalla, **Messaging endpoint:** `https://<tu-dominio>.ngrok-free.app/api/messages` → *Apply*.

Reinicia el bot para que cargue las credenciales:

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate teams-bot
Invoke-RestMethod http://localhost:3978/health      # "mode": "azure-bot-service"
```

## 5. Canal de Teams

Recurso Azure Bot → **Settings → Channels** → **Microsoft Teams** → acepta los términos → *Apply*.

## 6. Prueba en Web Chat (sin Teams)

Recurso Azure Bot → **Settings → Test in Web Chat** → escribe `ayuda`. Si responde con la tarjeta de
bienvenida, Azure ↔ ngrok ↔ bot funciona. (Web Chat no informa el correo del usuario: con
`BOT_DEFAULT_USER_EMAIL` las consultas se hacen con ese usuario.)

## 7. Paquete de la app e instalación en Teams

```powershell
.\.venv\Scripts\python.exe scripts\package_teams_app.py
# → teams-bot\manifest\build\soporte-ti-teams.zip
```

Teams → **Apps → Manage your apps → Upload an app → Upload a custom app** → elige el `.zip` → *Add*.

## 8. Dar acceso a los usuarios de Teams

El correo del usuario de Teams debe existir en Supabase con un perfil:

1. Supabase Dashboard → **Authentication → Users → Add user** con el **mismo correo** de Teams
   (o que inicie sesión una vez en el portal con *Continuar con Microsoft* si configuras Azure AD).
2. Portal → **Configuración → Usuarios y permisos** → asigna **rol** y **área**.

Escribe `estado` al bot: muestra la salud del sistema y con qué rol y área te identifica.

---

## Uso

| Mensaje | Respuesta |
|---------|-----------|
| Cualquier pregunta | Tarjeta con la respuesta, citas 📄, fuentes (sección, página, similitud), botón *Ver extractos* y 👍/👎 (el 👎 pide un comentario opcional) |
| `ayuda` / `/ayuda` | Bienvenida con preguntas de ejemplo pulsables |
| `estado` / `/estado` | Salud de los servicios y tu cuenta (rol, área) |
| `reiniciar` / `/reiniciar` | Reinicia la conversación |

En chats de grupo y canales, menciona al bot (`@Soporte TI IA ¿cómo…?`): la mención se elimina antes
de consultar.

## Diagnóstico

| Síntoma | Causa / solución |
|---------|------------------|
| Web Chat: *"There was an error sending this message"* | ngrok no está corriendo o el *Messaging endpoint* no termina en `/api/messages` |
| Logs del bot: 401 en `/api/messages` | `MICROSOFT_APP_ID`/`PASSWORD`/`TENANT_ID` no coinciden con Azure, o el bot no se reinició tras editarlos |
| El bot responde *"Tu cuenta corporativa no está registrada"* | Crea el usuario en Supabase con el mismo correo de Teams (paso 8) |
| No aparecen 👍/👎 | Teams no informó el correo del usuario: las consultas se hacen sin perfil y no se pueden valorar |
| *Upload a custom app* no aparece | El tenant no permite apps personalizadas (ver nota de requisitos) |
| `ngrok`: *agent version too old* | `ngrok update` |

Logs: `docker compose logs -f teams-bot`.

## Tests

```powershell
cd teams-bot; ..\.venv\Scripts\python.exe -m pytest --cov=app      # 19 tests, 95 %
```

Recorren el **pipeline real del SDK**: un servidor simula el *Bot Connector* de Teams (recibe las
respuestas y resuelve el correo del miembro) y `respx` simula el gateway. Cubren bienvenida, consulta en
nombre del usuario, caché de identidad, 👍/👎, botones de ejemplo, comandos, errores del gateway, usuario
sin correo, payloads inválidos (400) y rechazo de peticiones sin token de Bot Service en modo Azure (401).
