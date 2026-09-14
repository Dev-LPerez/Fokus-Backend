# Plan de Implementación — Gestión de Usuarios (Autenticación)

**Enfoque elegido:** Supabase Auth. El registro/login lo maneja Supabase directamente (gratis, sin límite relevante para este proyecto); el backend en FastAPI solo **verifica el token JWT** que Supabase emite y usa el `user_id` que contiene para aislar los datos de cada usuario. No se escribe lógica de hashing de contraseñas, recuperación de cuenta, etc. — eso ya lo resuelve Supabase.

**Por qué esta ruta y no un sistema de auth propio:** menos código que mantener, cero costo adicional, y el frontend en Next.js ya se va a conectar a Supabase de todas formas para otras cosas. Un sistema de auth casero (bcrypt + JWT propio) sería más trabajo para el mismo resultado.

---

## Fase A0 — Actualización de requerimientos (RF-11 / RF-12)

**Instrucción para el asistente:**
> Actualiza `requerimientos-backend.md`: RF-11 y RF-12 pasan de "opcional" a implementados. Añade esta sección de requerimientos técnicos de autenticación:
> - RF-14: Todo endpoint que exponga datos (`/chat`, `/conversations/*`) debe requerir un token JWT válido de Supabase en el header `Authorization: Bearer <token>`.
> - RF-15: Cada conversación y cada recordatorio deben quedar asociados al `user_id` del usuario que los creó.
> - RF-16: Un usuario solo puede ver, listar o eliminar sus propias conversaciones — nunca las de otro usuario.
> - RNF-10: La verificación del JWT debe hacerse localmente en el backend (sin llamar a la API de Supabase en cada petición) usando el secreto de firma, para no añadir latencia ni depender de un tercero en cada request.

---

## Fase A1 — Configurar Supabase Auth (sin código, en el panel de Supabase)

> **Nota:** desde octubre de 2025, todo proyecto nuevo de Supabase usa por defecto **JWT Signing Keys** (firma asimétrica, ES256) en vez del antiguo "JWT Secret" (HMAC simétrico). Como tu proyecto es reciente, casi seguro ya estás en el sistema nuevo — lo confirmamos abajo. Esto en realidad simplifica las cosas: **no hay ningún secreto que copiar ni proteger** en el backend, porque la verificación se hace contra una clave pública.

**Esto lo haces tú directamente en el dashboard de Supabase, no tu asistente de IA:**
1. En tu proyecto de Supabase → **Authentication** → habilita el proveedor **Email** (usuario/contraseña). Si quieres login social (Google, GitHub) más adelante, se añade después sin romper nada de lo que sigue.
2. Ve a **Authentication → Settings → JWT**. Confirma qué ves:
   - Si aparece **"Signing Keys"** (con estados Active/Standby) → estás en el sistema nuevo, sigue con el punto 3.
   - Si aparece explícitamente **"Legacy JWT secret"** como lo único disponible → tu proyecto es más antiguo; en ese caso sí necesitas copiar ese secreto y usarlo como `SUPABASE_JWT_SECRET` con verificación HS256 (avísame y ajusto la Fase A3 a ese caso).
3. Con Signing Keys, no necesitas copiar nada — solo anota tu **Project URL** (ej. `https://xxxx.supabase.co`), porque de ahí se arma el endpoint público de verificación:
   ```
   https://<tu-project-ref>.supabase.co/auth/v1/.well-known/jwks.json
   ```
4. Anota también la **anon public key** — la necesitará el frontend más adelante para el login (no el backend).

**Nueva variable de entorno para el backend:**
```
SUPABASE_URL=https://<tu-project-ref>.supabase.co
```
(ya no hace falta `SUPABASE_JWT_SECRET` si estás en el sistema de Signing Keys — el backend obtiene las claves públicas del endpoint JWKS, no de una variable de entorno secreta).

---

## Fase A2 — Migración: añadir `user_id` a las tablas

**Instrucción para el asistente:**
> Añade una columna `user_id UUID NOT NULL` a las tablas `conversations` y `reminders` (referencia lógica al `id` de `auth.users` que gestiona Supabase — no hace falta una FK física entre schemas, basta con el tipo UUID). Genera la migración con Alembic. Actualiza los modelos SQLAlchemy `Conversation` y `Reminder` en consecuencia.
>
> Nota: la tabla `messages` no necesita `user_id` propio — ya hereda el dueño a través de `conversation_id`.

```sql
ALTER TABLE conversations ADD COLUMN user_id UUID NOT NULL;
ALTER TABLE reminders ADD COLUMN user_id UUID NOT NULL;
CREATE INDEX idx_conversations_user_id ON conversations(user_id);
CREATE INDEX idx_reminders_user_id ON reminders(user_id);
```

**Criterio de aceptación:** la migración corre limpio con `alembic upgrade head` contra una base de datos de prueba, y los modelos reflejan la nueva columna.

---

## Fase A3 — Verificación de JWT vía JWKS y dependencia `get_current_user`

**Instrucción para el asistente:**
> Añade `pyjwt[crypto]` a `requirements.txt` (el extra `crypto` es necesario para verificar firmas ES256/RSA, no solo HS256). Crea `app/core/auth.py` con:
> 1. Un cliente JWKS usando `jwt.PyJWKClient(f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json")`, instanciado una sola vez (a nivel de módulo) para que cachee las claves públicas en memoria y no las vuelva a pedir en cada request — solo cuando aparece un `kid` que no tiene cacheado.
> 2. Una función `verify_token(token: str) -> dict` que use `PyJWKClient.get_signing_key_from_jwt(token)` para obtener la clave pública correspondiente al `kid` del header del JWT, y luego `jwt.decode(token, signing_key.key, algorithms=["ES256", "RS256"])` para validar firma y expiración. Debe devolver el payload decodificado (incluye `sub` = user_id).
> 3. Una dependencia de FastAPI `get_current_user` que:
>    - Extraiga el token del header `Authorization: Bearer <token>`.
>    - Llame a `verify_token`.
>    - Si el token es inválido, expiró, o el `kid` no se encuentra en el JWKS, lance `HTTPException(401)`.
>    - Si es válido, devuelva el `user_id` (UUID) para usarlo en los endpoints.
>
> Para los tests, no llames al JWKS real de Supabase: genera un par de claves ES256 de prueba con la librería `cryptography` dentro de un fixture, firma JWTs de prueba con la clave privada, y mockea `PyJWKClient.get_signing_key_from_jwt` para que devuelva la clave pública de prueba. Así cubres válido/expirado/inválido sin red ni credenciales reales.

**Criterio de aceptación:** tests que cubran token válido (pasa), token expirado (401), token con firma inválida (401), `kid` desconocido (401), y ausencia de header (401) — todos sin llamar a Supabase real.

---

## Fase A4 — Proteger endpoints y filtrar por usuario

**Instrucción para el asistente:**
> Aplica `Depends(get_current_user)` a todos los endpoints de `/chat`, `/conversations`, `/conversations/{id}` y `DELETE /conversations/{id}`. Ajusta la lógica:
> - `POST /chat`: al crear o continuar una conversación, asigna/verifica el `user_id` del token. Si el usuario intenta continuar una conversación (`conversation_id`) que no le pertenece, devuelve `404` (no `403`, para no filtrar la existencia de conversaciones ajenas).
> - `GET /conversations`: filtra por `user_id == current_user`.
> - `GET /conversations/{id}` y `DELETE /conversations/{id}`: verifica que la conversación pertenezca al usuario antes de devolverla o borrarla; si no, `404`.
> - La tool `create_reminder` debe recibir también el `user_id` del usuario actual y guardarlo en el recordatorio creado.
>
> `GET /health` y `GET /tools` quedan **sin protección** — no exponen datos de usuario.

**Criterio de aceptación:** un test que confirme que el usuario A no puede ver ni borrar una conversación creada por el usuario B (debe recibir 404), y que `GET /conversations` de A nunca incluye conversaciones de B.

---

## Fase A5 — Ajustar el orquestador del agente

**Instrucción para el asistente:**
> Propaga el `user_id` del usuario autenticado a través de `agent_service.process_message` y `process_message_stream` (nuevo parámetro `user_id: UUID`). Al crear una conversación nueva, guarda el `user_id`. Al pasar `db=db` a las tools, pasa también `user_id=user_id` para que `ReminderTool` lo use al crear el recordatorio.

**Criterio de aceptación:** test end-to-end (mockeado) que confirme que una conversación y un recordatorio creados a través de `/chat` quedan correctamente asociados al `user_id` del token usado en la petición.

---

## Fase A6 — Documentación y variables de entorno para despliegue

**Instrucción para el asistente:**
> Actualiza `contexto-general.md` y `requerimientos-backend.md` para reflejar que la autenticación ya está implementada (no "fuera de alcance"). Añade `SUPABASE_URL` a `.env.example` (como placeholder, no es secreto pero mantiene el patrón) y a la lista de variables de entorno a configurar en Render (`render.yaml`).

---

## Resumen del flujo final (para que lo tengas claro)

1. El usuario se registra/inicia sesión **desde el frontend**, directamente contra Supabase Auth (el backend no participa en esto).
2. Supabase le devuelve al frontend un JWT.
3. El frontend incluye ese JWT en cada petición al backend (`Authorization: Bearer <token>`).
4. El backend verifica el JWT localmente (sin llamar a Supabase) y extrae el `user_id`.
5. Todas las consultas a `conversations`, `messages` (vía la conversación) y `reminders` quedan automáticamente filtradas por ese `user_id`.

## Orden recomendado

| Fase | Depende de |
|---|---|
| A0 (requerimientos) | — |
| A1 (config Supabase, manual) | — |
| A2 (migración `user_id`) | A1 |
| A3 (verificación JWT) | A1 |
| A4 (proteger endpoints) | A2, A3 |
| A5 (orquestador) | A4 |
| A6 (documentación) | A5 |

**Nota sobre el frontend:** cuando lleguemos al plan del frontend, la Fase A1 ya te da todo lo necesario (Project URL + anon key) para integrar el login de Supabase ahí — no hace falta volver a tocar el backend para eso.