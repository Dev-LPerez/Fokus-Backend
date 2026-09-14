# Plan de Desarrollo — Executive Chief of Staff (Backend)

**Rol:** Entrégale este documento a tu asistente de IA de código, fase por fase. Cada fase está estructurada con contexto técnico exacto, instrucciones directas y criterios de aceptación verificables.

**Visión del Proyecto:** Transformar el agente de un chatbot conversacional reactivo a un **Executive Chief of Staff (Director de Operaciones Personal y Profesional)** proactivo. El sistema audita la agenda profesional del usuario en Google Calendar, previene colisiones con reuniones, ejecuta el Daily Standup matutino, gestiona tareas por proyecto/cliente con prioridad ejecutiva y programa bloques de *Deep Work* (trabajo enfocado) en su calendario real.

---

## Fase ECS-B0 — Extensión del Modelo de Datos para Contexto Profesional y Proyectos

**Contexto:**
Las tareas actuales en `reminders` solo tienen `description`, `due_date`, `completed` y `google_event_id`. Para organizar la vida laboral y ejecutar priorización ejecutiva (Matriz de Eisenhower), necesitamos clasificar por proyecto o cliente, nivel de prioridad y estimación de tiempo.

**Instrucción para el asistente:**
> 1. Modifica `app/models/reminder.py` agregando tres nuevas columnas:
>    - `project`: `Column(String, nullable=True)` — Nombre del proyecto, cliente o área (ej. "Backend API", "Cliente Acme", "Finanzas", "Personal").
>    - `priority`: `Column(String, nullable=False, default="medium")` — Nivel de prioridad: `"high"` (urgente/crítico), `"medium"` (importante), `"low"` (rutina/secundario).
>    - `estimated_minutes`: `Column(Integer, nullable=True)` — Estimación de duración en minutos para completar la tarea o el bloque de enfoque.
> 2. Actualiza `app/schemas/reminder.py` con los nuevos campos en `ReminderCreate`, `ReminderUpdate` y `ReminderResponse`.
> 3. Genera y aplica la migración correspondiente con Alembic:
>    `alembic revision --autogenerate -m "add professional fields to reminders"`
> 4. Actualiza los fixtures y helpers en `tests/conftest.py` si es necesario para SQLite en memoria.

**Criterio de aceptación:**
- La migración de Alembic corre limpiamente con `alembic upgrade head`.
- La suite de tests actual sigue pasando al 100% sin regresiones (`pytest tests/ -v`).

---

## Fase ECS-B1 — Visibilidad de Agenda: Lectura de Reuniones y Detección de Huecos en Google Calendar

**Contexto:**
Actualmente `app/services/google_calendar.py` solo implementa `create_event` y `delete_event`. El agente no puede ver qué llamadas, reuniones o citas tiene el usuario hoy, por lo que no puede advertir sobre colisiones ni sugerir horarios de trabajo libre.

**Instrucción para el asistente:**
> Amplía `GoogleCalendarService` en `app/services/google_calendar.py` con dos métodos esenciales:
> 1. `list_events(user_id: UUID, time_min: datetime, time_max: datetime, db: AsyncSession) -> List[Dict[str, Any]]`:
>    - Obtiene y refresca tokens OAuth si es necesario.
>    - Llama a `service.events().list()` con `timeMin` y `timeMax` formateados en RFC3339.
>    - Retorna lista estructurada: `[{"id": ..., "summary": ..., "start": ..., "end": ..., "description": ...}]`.
> 2. `find_free_slots(user_id: UUID, target_date: date, min_duration_minutes: int, db: AsyncSession, workday_start_hour: int = 8, workday_end_hour: int = 19) -> List[Dict[str, Any]]`:
>    - Consulta los eventos del día `target_date`.
>    - Calcula los intervalos libres entre `workday_start_hour` y `workday_end_hour` (en zona horaria `America/Bogota`) que tengan al menos `min_duration_minutes` de duración disponible.
>    - Retorna lista de bloques libres: `[{"start": "2026-05-10 10:30", "end": "2026-05-10 13:00", "duration_minutes": 150}]`.
> 3. Si Google Calendar no está conectado, lanza `GoogleCalendarNotConnected`.

**Criterio de aceptación:**
- Tests unitarios en `tests/test_google_calendar.py` con mocks de Google API que verifiquen:
  - Listado exitoso de reuniones/eventos en un rango horario.
  - Cálculo matemático exacto de huecos libres entre eventos.
  - Comportamiento controlado ante usuario sin integración.

---

## Fase ECS-B2 — Tools Ejecutivas: Agenda, Detección de Conflictos y Deep Work

**Contexto:**
El orquestador en `app/services/tools/` necesita exponer las capacidades ejecutivas a Gemini a través de Function Calling.

**Instrucción para el asistente:**
> 1. En `app/services/tools/calendar_agenda.py`, crea y registra:
>    - `GetCalendarAgendaTool` (`get_calendar_agenda`):
>      - Parámetros: `date_str` (opcional, por defecto fecha actual 'YYYY-MM-DD').
>      - Retorna las reuniones y compromisos del usuario para ese día.
>    - `FindFreeWorkSlotsTool` (`find_free_work_slots`):
>      - Parámetros: `date_str` (str), `duration_minutes` (int, default 60).
>      - Retorna los bloques de tiempo libres en la jornada para agendar trabajo o llamadas.
>    - `ScheduleDeepWorkTool` (`schedule_deep_work`):
>      - Parámetros: `task_description` (str), `project` (str opcional), `duration_minutes` (int, default 90), `target_date` (str opcional).
>      - Lógica: Busca el mejor hueco libre disponible en Google Calendar y agenda un bloque titulado `"[Deep Work] {task_description}"`, además de registrar la tarea en `reminders` con `project={project}`, `priority='high'`, `estimated_minutes=duration_minutes`.
> 2. Actualiza `create_reminder` y `list_reminders` en `app/services/tools/reminders.py` para aceptar los parámetros opcionales `project` y `priority` (permitiendo filtrar tareas por proyecto).
> 3. Registra todas las nuevas tools en `app/services/tools/registry.py`.

**Criterio de aceptación:**
- Tests en `tests/test_executive_tools.py` que validen la ejecución de `get_calendar_agenda`, `find_free_work_slots` y `schedule_deep_work`.

---

## Fase ECS-B3 — Endpoint de Daily Standup & Executive Briefing (`GET /briefing`)

**Contexto:**
El Chief of Staff debe ser capaz de entregar un resumen ejecutivo inmediato de cómo viene el día sin obligar al usuario a escribir un mensaje largo. El frontend puede invocar este endpoint para renderizar un widget matutino.

**Instrucción para el asistente:**
> 1. Crea el router `app/routers/briefing.py` con endpoint `GET /briefing` (protegido con `get_current_user`):
>    - Obtiene la fecha actual en `America/Bogota`.
>    - Consulta en paralelo (`asyncio.gather`):
>      a) Reuniones de Google Calendar de hoy (si está conectado).
>      b) Tareas pendientes y críticas (`priority='high'`) en `reminders` para el usuario.
>      c) Clima actual de la ciudad configurada con `get_weather`.
>      d) Huecos disponibles de Deep Work hoy.
>    - Retorna JSON estructurado:
>      ```json
>      {
>        "date": "2026-05-15",
>        "weather": { "temp": 28, "description": "cielo claro" },
>        "calendar_connected": true,
>        "events_today": [...],
>        "critical_tasks": [...],
>        "pending_tasks_count": 4,
>        "free_slots_summary": "Tienes 2.5 horas libres entre 10:30 AM y 1:00 PM para Deep Work."
>      }
>      ```
> 2. Incluye `briefing_router` en `app/main.py`.

**Criterio de aceptación:**
- Test en `tests/test_briefing.py` que verifique la respuesta 200 con la estructura JSON completa para usuarios con y sin Google Calendar.

---

## Fase ECS-B4 — Rediseño del System Prompt: Mentalidad Executive Chief of Staff

**Contexto:**
El prompt actual en `agent.py` es el de un chatbot generalista. Debe transformarse en la identidad del **Executive Chief of Staff**.

**Instrucción para el asistente:**
> Actualiza la función `_get_generate_config` en `app/services/agent.py`:
> 1. Rediseña `system_instruction` estableciendo el rol:
>    - **Identidad:** *"Eres el Executive Chief of Staff del usuario: su director de operaciones personal, estratega de productividad y protector de su tiempo."*
>    - **Principios de Acción:**
>      - **Protección de Tiempo & Deep Work:** Defiende la agenda contra reuniones innecesarias. Si el usuario tiene tareas complejas, ofrece agendar bloques protegidos de concentración (`schedule_deep_work`).
>      - **Auditoría de Conflictos:** Antes de agendar una reunión o tarea con horario fijo, revisa la agenda con `get_calendar_agenda` para evitar cruces.
>      - **Matriz de Eisenhower:** Clasifica prioridades en Urgentes vs Importantes. Nunca permitas que lo urgente opaque las metas de alto impacto.
>      - **Inteligencia Rápida:** Si el usuario tiene una reunión o investigación de mercado, utiliza `search_web` para entregar síntesis ejecutivas accionables.
>      - **Tono:** Profesional, conciso, asertivo, orientado a la acción y con formato estructurado (viñetas y negritas).

**Criterio de aceptación:**
- Tests en `tests/test_agent.py` confirmando que ante preguntas como *"¿Cómo viene mi día hoy?"* o *"Bloquea 2 horas para trabajar en el informe del cliente"*, el agente invoque las herramientas correspondientes.

---

## Fase ECS-B5 — Suite de Regresión y Documentación Final

**Instrucción para el asistente:**
> 1. Ejecuta la suite completa de tests (`pytest tests/ -v`). Confirma que no haya regresiones y que todos los tests pasen al 100%.
> 2. Actualiza `requerimientos-backend.md` documentando los nuevos requerimientos funcionales:
>    - RF-21: Lectura de reuniones y eventos en Google Calendar.
>    - RF-22: Planificación y bloqueo de tiempo para Deep Work (`schedule_deep_work`).
>    - RF-23: Endpoint de resumen ejecutivo diario (`/briefing`).
> 3. Actualiza `contexto-general.md` con la nueva identidad de Executive Chief of Staff.

**Criterio de aceptación:**
- 100% de tests pasando en entorno de pruebas.
- Documentación sincronizada y lista para despliegue.

---

## Resumen de Fases y Dependencias (Backend)

| Fase | Descripción | Dependencias |
|---|---|---|
| **ECS-B0** | Columnas `project`, `priority`, `estimated_minutes` en `reminders` + Migración Alembic | — |
| **ECS-B1** | Lectura de reuniones y huecos libres en `GoogleCalendarService` | ECS-B0 |
| **ECS-B2** | Tools: `get_calendar_agenda`, `find_free_work_slots`, `schedule_deep_work` | ECS-B1 |
| **ECS-B3** | Endpoint `GET /briefing` (Daily Standup) | ECS-B1, ECS-B2 |
| **ECS-B4** | System Instruction: Mentalidad Executive Chief of Staff | ECS-B2 |
| **ECS-B5** | Tests de integración finales y actualización de docs | ECS-B0 a ECS-B4 |
