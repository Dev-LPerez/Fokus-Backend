# Contexto General del Proyecto — Executive Chief of Staff (AI Agent)

> Documento de referencia rápida. Da la visión completa del proyecto antes de entrar en detalle técnico (ver `requerimientos-backend.md` para el detalle del backend).

---

## 1. ¿Qué es este proyecto?

Un **Executive Chief of Staff (Director de Operaciones Personal y Estratega de Productividad)** impulsado por IA conversacional que no solo responde preguntas, sino que ejecuta acciones reales a partir del lenguaje natural del usuario. 

A diferencia de un chatbot reactivo tradicional, este sistema actúa como el guardián de la agenda profesional y personal del usuario:
- Audita su calendario real en Google Calendar para prevenir colisiones de reuniones.
- Detecta y agenda bloques protegidos de **Deep Work** (trabajo enfocado) sin cruces de horarios.
- Ejecuta priorización ejecutiva (Matriz de Eisenhower) clasificando tareas por proyecto, cliente, nivel de urgencia/importancia y duración estimada.
- Entrega un **Daily Standup & Executive Briefing** matutino (`/briefing`) consolidando clima, agenda del día, tareas críticas y disponibilidad.
- Realiza investigación de mercado y contexto en tiempo real mediante búsqueda web.

Es un proyecto universitario, con presupuesto $0, construido enteramente sobre tecnologías con tier gratuito.

---

## 2. Problema que resuelve / motivación

Los profesionales y líderes sufren de fatiga de decisiones, saturación de reuniones (*meeting overload*) y dispersión de tareas. Los chatbots convencionales basados únicamente en texto no tienen visibilidad de la agenda en tiempo real ni pueden tomar acciones proactivas sobre el calendario. Este proyecto implementa la arquitectura de **Executive Agentic AI con Function Calling**: un LLM de Google Gemini que orquesta herramientas especializadas para optimizar y defender el tiempo del usuario.

---

## 3. Objetivo del proyecto

Construir un agente ejecutivo funcional, desplegado y accesible públicamente, que:
- Opere con mentalidad y asertividad de Executive Chief of Staff.
- Audite la agenda en Google Calendar y proteja bloques de trabajo profundo (Deep Work).
- Gestione tareas organizadas por proyecto, prioridad y tiempo estimado.
- Ofrezca un endpoint de resumen ejecutivo diario (`GET /briefing`) para widgets o dashboards matutinos.
- Autentique a los usuarios mediante Supabase Auth y aísle completamente sus datos (`user_id`).
- Todo esto sin incurrir en ningún costo ($0 budget).

---

## 4. Alcance funcional (resumen)

- **Autenticación multiusuario:** Registro e inicio de sesión gestionado por Supabase Auth en el frontend, con validación de tokens JWT (ES256/RS256 vía JWKS) en el backend.
- **Aislamiento estricto de datos:** Cada conversación, tarea y recordatorio pertenece a un `user_id`; los usuarios solo pueden acceder y operar sobre su propia información.
- **Chat interactivo con streaming:** Respuestas en tiempo real (Server-Sent Events) con notificación de llamadas a herramientas.
- **Tools ejecutivas especializadas:**
  - Clima local (`get_weather`).
  - Gestor de tareas con matriz de priorización (`create_reminder`, `list_reminders`, `complete_reminder`, `delete_reminder`).
  - Auditoría de agenda en Google Calendar (`get_calendar_agenda`).
  - Detección matemática de intervalos libres en la jornada laboral (`find_free_work_slots`).
  - Bloqueo y protección de tiempo de concentración (`schedule_deep_work`).
  - Búsqueda web e inteligencia rápida (`search_web`).
- **Daily Standup & Executive Briefing:** Endpoint `GET /briefing` que consolida agenda, tareas de alta prioridad, clima y bloques libres del día.
- **Integración con Google Calendar:** Conexión OAuth 2.0 con tokens cifrados con Fernet, renovación automática de sesión y sincronización bidireccional.
- **Historial persistente:** Persistencia en PostgreSQL (Supabase) separada por usuario y conversación.

*(El detalle completo de requerimientos funcionales y no funcionales del backend está en `requerimientos-backend.md`.)*

---

## 5. Arquitectura general

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   Frontend       │ ──Bearer JWT─▶│   Backend        │ ──API──▶│  Gemini API      │
│   Next.js        │ ──HTTP/SSE──▶│   FastAPI        │         │  (LLM + function │
│   (Vercel)       │◀────────────│   (Render)       │         │   calling)        │
└────────┬────────┘         └────────┬─────────┘         └─────────────────┘
         │                             │
         │ Auth (login/signup)         ├──────────────┬──────────────┬──────────────┐
         ▼                             ▼              ▼              ▼              ▼
   ┌──────────┐                  ┌──────────┐  ┌────────────┐  ┌──────────────┐  ┌──────────────┐
   │ Supabase │◀──JWKS (keys)────│ Supabase │  │OpenWeather │  │ DuckDuckGo   │  │Google Calendar
   │   Auth   │                  │(Postgres)│  │    Map     │  │  (scraping)  │  │  (OAuth/API) │
   └──────────┘                  └──────────┘  └────────────┘  └──────────────┘  └──────────────┘
```

El **backend es el cerebro del sistema**: verifica el token JWT del usuario, recibe el mensaje, decide junto con Gemini si hay que ejecutar una función, la ejecuta asociándola al `user_id`, y transmite la respuesta en streaming al frontend. El **frontend es la capa de presentación**: autentica con Supabase y muestra la conversación.

---

## 6. Stack tecnológico

| Capa | Tecnología | Despliegue |
|---|---|---|
| Frontend | Next.js | Vercel |
| Backend | FastAPI (Python) | Render |
| Autenticación | Supabase Auth (JWT ES256/RS256 vía JWKS) | Supabase (cloud) |
| LLM / Agente | Google Gemini API (`google-genai` function calling) | — |
| Base de datos | PostgreSQL vía Supabase | Supabase (cloud) |

**Restricción de diseño transversal:** todo el stack debe operar en tier gratuito, sin tarjeta de crédito. Esto condiciona decisiones como el manejo de rate limits de Gemini, el "cold start" de Render tras inactividad, y la ausencia de backups automáticos en Supabase.

---

## 7. Estado actual del proyecto

- ✅ Definición de alcance, stack y arquitectura
- ✅ Requerimientos del backend documentados (incluyendo RF-14/15/16 y RNF-10)
- ✅ Implementación de autenticación JWT y aislamiento por `user_id`
- ✅ Plan de desarrollo del backend por fases (ver `plan.md` y `plan-implementacion-usuarios.md`)
- ✅ Desarrollo y tests del backend completados
- 🔲 Desarrollo del frontend (pendiente)
- 🔲 Despliegue e integración final

---

## 8. Documentos relacionados en este proyecto

- `requerimientos-backend.md` — requerimientos funcionales, no funcionales y técnicos del backend
- `plan.md` — plan de desarrollo del backend por fases
- `plan-implementacion-usuarios.md` — especificación de la integración de Supabase Auth