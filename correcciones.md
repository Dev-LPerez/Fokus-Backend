# Correcciones pendientes — Backend Agente de IA

> Instrucciones para el asistente de IA de código. Ejecutar los 3 puntos en orden; cada uno tiene su criterio de aceptación. No se debe reportar "completado" sin verificar el criterio corriendo la suite de tests en un entorno limpio.

---

## Corrección 1 — Inyección de sesión de BD en `ReminderTool`

**Problema:** `app/services/tools/reminders.py` crea su propia sesión (`AsyncSessionLocal`) en vez de recibir la sesión activa de la petición. Esto hace que la tool siempre escriba contra la base de datos real de producción (Supabase), incluso cuando se ejecuta desde un test con SQLite en memoria — rompiendo el aislamiento de los tests y ensuciando la BD real en cada corrida.

**Instrucción:**
> Modifica `ReminderTool.execute()` para que reciba la sesión de base de datos (`AsyncSession`) como parámetro en vez de crear una nueva internamente con `AsyncSessionLocal`. Ajusta la interfaz `BaseTool` si es necesario para que las tools que requieren acceso a BD puedan recibir la sesión desde el orquestador (`agent.py`), que ya tiene la sesión inyectada por FastAPI vía `Depends(get_db)`. Actualiza `agent.py` para pasar la sesión a `tool.execute()` cuando la tool lo requiera (puedes usar `inspect` para detectar el parámetro `db` opcional, o simplemente pasar `db=db` a todas las tools y que las que no lo necesiten lo ignoren vía `**kwargs`). Actualiza el test `test_reminder_tool_execution` en `tests/test_tools.py` para que use la fixture `db_session` (SQLite en memoria) en vez de conectar a la base de datos real.

**Criterio de aceptación:** correr `pytest tests/ -v` en un entorno limpio (sin `.env` con credenciales reales, o con `DATABASE_URL` apuntando a algo inalcanzable) — el test de recordatorios debe pasar usando exclusivamente la sesión de prueba, sin intentar conectarse a Supabase.

---

## Corrección 2 — Reconectar el retry de rate-limiting

**Problema:** `gemini_retry` sigue definido en `gemini_client.py` pero ya no se aplica en ninguna llamada a Gemini dentro de `agent.py`. Esto significa que el manejo de rate limits del tier gratuito (~15 req/min) ya no funciona: la primera petición que choque con el límite falla directamente, sin reintento.

**Instrucción:**
> Aplica el decorador `gemini_retry` (o su equivalente adaptado al cliente async de `google-genai`) a las llamadas `await chat.send_message(...)` y `await chat.send_message_stream(...)` en `agent.py`, tanto en `process_message` como en `process_message_stream`. Ajusta la condición del retry: en vez de `retry_if_exception_type((APIError, Exception))` (que reintenta ante cualquier error, incluso bugs de código), filtra específicamente por las excepciones de rate-limit/servicio no disponible que expone `google.genai.errors` (revisa la documentación del SDK para identificar el tipo exacto — probablemente algo equivalente a un error 429/503 dentro de `APIError`, verificable por código de estado en la excepción). Verifica que `tenacity` funcione correctamente con corutinas async (puede que necesites usar `AsyncRetrying` en vez del decorador síncrono `retry`, ya que las llamadas ahora son `await`).

**Criterio de aceptación:** un test (puede ser con mock) que simule una excepción de rate-limit en el primer intento y confirme que la llamada se reintenta y eventualmente responde exitosamente, sin reintentar ante un error no relacionado (ej. un `ValueError` genérico).

---

## Corrección 3 — Resolver la variable de modelo fallback huérfana

**Problema:** `GEMINI_FALLBACK_MODEL` está declarada en `config.py` pero no se usa en ningún lugar del código. El reporte previo afirmó que el fallback estaba "preservado", pero no hay lógica que lo active.

**Instrucción:**
> - **implementar el fallback real:** en `agent.py`, si la llamada a `settings.GEMINI_MODEL` falla de forma persistente (agotó los reintentos de la Corrección 2, o devuelve un error no recuperable), reintenta una vez usando `settings.GEMINI_FALLBACK_MODEL` antes de propagar el error al usuario.


**Criterio de aceptación:** si se elige la Opción A, un test que simule fallo del modelo principal y confirme que se usa el fallback. Si se elige la Opción B, confirmar que no quedan referencias a `GEMINI_FALLBACK_MODEL` en el código ni en la configuración de Render.

---

## Verificación final

Antes de reportar estas correcciones como completadas:
1. Correr `pytest tests/ -v` en un entorno con dependencias recién instaladas desde `requirements.txt` (no reusar un venv con caché).
2. Confirmar el tiempo real de ejecución y el conteo de tests pasados/fallados en el reporte — no asumir cifras de una corrida anterior.
3. Si algún test depende de una variable de entorno o servicio externo, dejarlo explícito en el reporte (no presentarlo como "aislado" si no lo es).