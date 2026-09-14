# Plan de Desarrollo — Gestor de Tareas + Integración Google Calendar (Backend)

**Rol:** entrégale este documento a tu asistente de IA de código, fase por fase.

**Resumen de lo que se construye:**
1. El gestor de tareas ampliado (CRUD completo sobre `reminders`).
2. La integración con Google Calendar, para que cada tarea con fecha límite cree un evento real en el calendario del usuario, con notificación nativa (Google se encarga de avisar — tu backend ya no necesita ningún cron ni servicio de email).

---

## Fase T0 — Actualización de requerimientos

**Instrucción para el asistente:**
> Actualiza `requerimientos-backend.md` añadiendo:
> - RF-17: El usuario debe poder listar, marcar como completada y eliminar sus tareas/recordatorios (no solo crearlos).
> - RF-18: El usuario debe poder conectar y desconectar su cuenta de Google Calendar desde el backend.
> - RF-19: Al crear una tarea con fecha límite, si el usuario tiene Google Calendar conectado, debe crearse automáticamente un evento en su calendario con notificación configurada.
> - RF-20: Si el usuario NO tiene Google Calendar conectado, la tarea debe seguir creándose con normalidad (solo en la base de datos local), sin bloquear ni fallar.
> - RNF-11: Los tokens de acceso/refresco de Google deben almacenarse cifrados en la base de datos, nunca en texto plano.

---

## Fase T1 — Configuración en Google Cloud Console (manual, no código)

**Esto lo haces tú, no tu asistente de IA:**
1. Crea un proyecto en [Google Cloud Console](https://console.cloud.google.com/) (gratis).
2. Habilita la **Google Calendar API** para ese proyecto.
3. Configura la **pantalla de consentimiento OAuth**:
   - Tipo: Externo.
   - Estado: "Testing" — así no necesitas que Google verifique la app, y puedes añadir hasta 100 usuarios de prueba (de sobra para tu proyecto académico). Añade tu propio correo como usuario de prueba para poder probarlo tú mismo.
   - Scope necesario: `https://www.googleapis.com/auth/calendar.events` (solo eventos, no acceso completo al calendario — principio de menor privilegio).
4. Crea credenciales **OAuth 2.0 Client ID**, tipo "Aplicación web". Como URI de redirección autorizado, agrega:
   - `http://localhost:8000/integrations/google/callback` (desarrollo)
   - `https://<tu-backend-en-render>.onrender.com/integrations/google/callback` (producción, una vez tengas la URL de Render)
5. Copia el **Client ID** y **Client Secret**.

**Nuevas variables de entorno para el backend:**
```
GOOGLE_CLIENT_ID=<el que copiaste>
GOOGLE_CLIENT_SECRET=<el que copiaste>
GOOGLE_REDIRECT_URI=http://localhost:8000/integrations/google/callback
TOKEN_ENCRYPTION_KEY=<generar con Fernet.generate_key(), ver Fase T3>
```

---

## Fase T2 — Migraciones: tareas ampliadas y almacenamiento de integración

**Instrucción para el asistente:**
> Añade columnas a la tabla `reminders`:
> ```sql
> ALTER TABLE reminders ADD COLUMN completed BOOLEAN NOT NULL DEFAULT false;
> ALTER TABLE reminders ADD COLUMN google_event_id TEXT NULL;
> ```
> Crea una nueva tabla `user_integrations`:
> ```sql
> CREATE TABLE user_integrations (
>     id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
>     user_id UUID NOT NULL,
>     provider TEXT NOT NULL,           -- 'google_calendar'
>     access_token_encrypted TEXT NOT NULL,
>     refresh_token_encrypted TEXT NOT NULL,
>     token_expires_at TIMESTAMPTZ,
>     created_at TIMESTAMPTZ DEFAULT now(),
>     UNIQUE(user_id, provider)
> );
> CREATE INDEX idx_user_integrations_user_id ON user_integrations(user_id);
> ```
> Genera la migración de Alembic y actualiza los modelos SQLAlchemy correspondientes (`Reminder` y el nuevo modelo `UserIntegration`).

**Criterio de aceptación:** migración corre limpio con `alembic upgrade head` contra una base de prueba.

---

## Fase T3 — Cifrado de tokens

**Instrucción para el asistente:**
> Añade `cryptography` a `requirements.txt`. Crea `app/core/encryption.py` con dos funciones: `encrypt_token(raw: str) -> str` y `decrypt_token(encrypted: str) -> str`, usando `Fernet` con la clave `settings.TOKEN_ENCRYPTION_KEY`. Documenta en un comentario cómo generar la clave (`from cryptography.fernet import Fernet; Fernet.generate_key()`), para que el usuario la genere una vez y la guarde como variable de entorno.

**Criterio de aceptación:** test que cifre un string, lo descifre, y confirme que coincide con el original; y que confirme que el valor cifrado en la "base de datos" (mock) nunca es igual al texto plano.

---

## Fase T4 — Flujo OAuth de Google Calendar

**Instrucción para el asistente:**
> Añade `google-auth`, `google-auth-oauthlib` y `google-api-python-client` a `requirements.txt`. Crea el router `app/routers/integrations.py` con:
> - `GET /integrations/google/connect` (protegido, requiere `get_current_user`): genera la URL de autorización de Google (con el scope de Calendar) y la devuelve para que el frontend redirija al usuario.
> - `GET /integrations/google/callback`: recibe el `code` de Google, lo intercambia por `access_token`/`refresh_token`, los cifra (Fase T3), y los guarda/actualiza en `user_integrations` para el usuario correspondiente. Redirige de vuelta al frontend (`FRONTEND_URL/settings?google=connected`).
> - `DELETE /integrations/google` (protegido): elimina el registro de `user_integrations` del usuario (desconectar).
> - `GET /integrations/status` (protegido): indica si el usuario tiene Google Calendar conectado o no (para que el frontend lo muestre).
>
> **Importante sobre el `state` del OAuth:** ya que el flujo de conexión ocurre fuera del contexto normal de una petición autenticada por header (es una redirección de navegador), usa el parámetro `state` de OAuth para llevar el `user_id` de forma firmada/verificable (ej. un JWT de corta duración firmado con tu propia clave, no el de Supabase) entre el `/connect` y el `/callback`, y así saber a qué usuario pertenece la conexión cuando Google redirige de vuelta.

**Criterio de aceptación:** con credenciales de prueba mockeadas, un test que simule el intercambio de código por tokens y confirme que quedan guardados cifrados en la tabla, asociados al `user_id` correcto (extraído del `state`).

---

## Fase T5 — Cliente de Google Calendar y refresco automático de token

**Instrucción para el asistente:**
> Crea `app/services/google_calendar.py` con una clase que:
> 1. Cargue los tokens del usuario desde `user_integrations`, descifrándolos.
> 2. Si el `access_token` expiró, lo refresque automáticamente usando el `refresh_token`, y actualice el registro cifrado en la base de datos.
> 3. Exponga `create_event(user_id, title, description, due_date) -> event_id`, `delete_event(user_id, event_id)`.
> 4. El evento debe crearse con un recordatorio (`reminders`) configurado en la API de Calendar — por ejemplo, notificación por email y popup 30 minutos antes.
>
> Maneja el caso en que el usuario nunca conectó Google Calendar: estas funciones deben lanzar una excepción específica (`GoogleCalendarNotConnected`) que el llamador pueda capturar sin que la operación completa falle.

**Criterio de aceptación:** tests con la API de Google mockeada (no llamadas reales) que cubran: creación exitosa, refresco de token expirado, y el caso de usuario sin integración conectada.

---

## Fase T6 — Tools del gestor de tareas (CRUD + integración opcional con Calendar)

**Instrucción para el asistente:**
> Amplía `app/services/tools/reminders.py` con:
> - `list_reminders(user_id, db, include_completed=False)` — lista tareas del usuario.
> - `complete_reminder(reminder_id, user_id, db)` — marca como completada (verifica que la tarea pertenezca al usuario; si no, error controlado).
> - `delete_reminder(reminder_id, user_id, db)` — elimina, y si tiene `google_event_id`, también borra el evento del calendario (usando el servicio de la Fase T5; si falla el borrado en Calendar, igual completa el borrado local y lo reporta en el resultado, no lo bloquea).
> - Modifica `create_reminder` para que, tras guardar la tarea localmente, intente crear el evento en Google Calendar (Fase T5). Si el usuario no lo tiene conectado (`GoogleCalendarNotConnected`), la tarea se crea igual, y el resultado de la tool debe indicarlo claramente (ej. `{"created": true, "calendar_synced": false, "note": "Conecta tu Google Calendar para recibir notificaciones"}`) para que el agente se lo explique al usuario en su respuesta.
>
> Registra las 3 funciones nuevas en el `ToolRegistry` con sus descripciones para function calling.

**Criterio de aceptación:** tests para las 4 funciones (incluyendo `create_reminder` actualizada), cubriendo: usuario con Calendar conectado (evento se crea), usuario sin Calendar (tarea se crea igual, con el aviso correspondiente), intento de completar/borrar una tarea ajena (rechazado).

---

## Fase T7 — Documentación y variables de entorno para despliegue

**Instrucción para el asistente:**
> Actualiza `contexto-general.md` y `requerimientos-backend.md` reflejando la nueva arquitectura (ya no se necesita ni Resend ni pg_cron — Google Calendar maneja las notificaciones). Añade `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` y `TOKEN_ENCRYPTION_KEY` a `.env.example` y a `render.yaml` (todas con `sync: false` excepto `GOOGLE_REDIRECT_URI`, que sí puede ir con su valor de producción visible ya que no es secreto).

---

## Orden recomendado

| Fase | Depende de |
|---|---|
| T0 | — |
| T1 (manual, Google Cloud) | — |
| T2 (migraciones) | — |
| T3 (cifrado) | — |
| T4 (OAuth) | T1, T2, T3 |
| T5 (cliente Calendar) | T4 |
| T6 (tools) | T5 |
| T7 (docs) | T6 |

**Nota:** T1, T2 y T3 no dependen entre sí — se pueden hacer en cualquier orden o en paralelo. Lo único estrictamente secuencial es T4 → T5 → T6.