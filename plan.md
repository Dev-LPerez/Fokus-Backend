# Plan de Desarrollo — Backend del Agente de IA

**Rol:** Este documento está escrito para que se lo entregues directamente a tu asistente de IA de código (Claude Code u otro). Cada fase es una instrucción autocontenida — dile "ejecuta la Fase 1" y así sucesivamente.

**Stack confirmado:** FastAPI + Gemini API + Supabase (PostgreSQL) + despliegue en Render.

---

## Fase 0 — Estructura del proyecto

**Instrucción para el asistente:**
> Crea la estructura de carpetas de un proyecto FastAPI siguiendo el patrón de separación por capas (routers, services, models, schemas). Inicializa un entorno virtual, un `requirements.txt` con las dependencias listadas abajo, y un `.env.example` con las variables de entorno necesarias (sin valores reales).

```
backend/
├── app/
│   ├── main.py                # entrypoint FastAPI
│   ├── core/
│   │   ├── config.py           # carga de variables de entorno (pydantic-settings)
│   │   └── database.py         # conexión a Supabase/PostgreSQL (SQLAlchemy async)
│   ├── models/                 # modelos SQLAlchemy (tablas)
│   │   ├── conversation.py
│   │   ├── message.py
│   │   └── reminder.py
│   ├── schemas/                # esquemas Pydantic (request/response)
│   │   ├── chat.py
│   │   └── reminder.py
│   ├── routers/                # endpoints agrupados por dominio
│   │   ├── chat.py
│   │   ├── conversations.py
│   │   └── tools.py
│   ├── services/
│   │   ├── agent.py            # orquestador: lógica de function calling
│   │   ├── gemini_client.py    # wrapper del SDK de Gemini
│   │   └── tools/              # cada función/tool en su propio archivo
│   │       ├── weather.py
│   │       ├── reminders.py
│   │       └── web_search.py
│   └── db/
│       └── session.py          # sesión async de SQLAlchemy
├── tests/
├── .env.example
├── requirements.txt
└── README.md
```

**Dependencias (`requirements.txt`):**
```
fastapi
uvicorn[standard]
google-generativeai
sqlalchemy[asyncio]
asyncpg
pydantic-settings
python-dotenv
httpx
tenacity
beautifulsoup4
```

**Variables de entorno (`.env.example`):**
```
GEMINI_API_KEY=
DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname
OPENWEATHER_API_KEY=
ENVIRONMENT=development
```

---

## Fase 1 — Conexión a base de datos y modelos

**Instrucción para el asistente:**
> Configura la conexión asíncrona a Supabase usando SQLAlchemy (`asyncpg`). Define los modelos `Conversation`, `Message` y `Reminder` según el esquema de abajo. Genera las migraciones (usa Alembic) y verifica que la conexión funcione con un script simple de prueba.

**Esquema de tablas:**

```sql
-- conversations
id UUID PRIMARY KEY DEFAULT gen_random_uuid()
title TEXT
created_at TIMESTAMPTZ DEFAULT now()

-- messages
id UUID PRIMARY KEY DEFAULT gen_random_uuid()
conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE
role TEXT CHECK (role IN ('user', 'assistant', 'tool'))
content TEXT
tool_name TEXT NULL
created_at TIMESTAMPTZ DEFAULT now()

-- reminders
id UUID PRIMARY KEY DEFAULT gen_random_uuid()
description TEXT NOT NULL
due_date TIMESTAMPTZ
created_at TIMESTAMPTZ DEFAULT now()
```

> Nota: se deja fuera `user_id` por ahora — la Fase 5 (opcional) añade autenticación con Supabase Auth si decides ir multiusuario.

**Criterio de aceptación:** un script `test_connection.py` que inserte y lea un registro de prueba en `conversations` contra la base de Supabase real.

---

## Fase 2 — Cliente de Gemini y primer endpoint sin tools

**Instrucción para el asistente:**
> Implementa `gemini_client.py` como wrapper del SDK `google-generativeai`, con manejo de errores y retry (usa `tenacity` con backoff exponencial para el rate limit de 15 req/min). Crea el endpoint `POST /chat` que reciba un mensaje, lo envíe a Gemini SIN function calling todavía, y devuelva la respuesta completa (sin streaming aún — eso es la Fase 4). Guarda el mensaje del usuario y la respuesta del asistente en la tabla `messages`.

**Criterio de aceptación:** `POST /chat` con `{"message": "hola"}` responde con el texto generado por Gemini y ambos mensajes quedan persistidos en la base de datos.

---

## Fase 3 — Function calling y primeras tools

**Instrucción para el asistente:**
> Implementa el orquestador en `services/agent.py`: debe declarar las funciones disponibles en el formato que espera la API de Gemini para function calling, enviarlas junto con el mensaje del usuario, interpretar si el modelo pide ejecutar una función, ejecutarla, y devolver el resultado al modelo para obtener la respuesta final. Implementa las primeras dos tools:
> 1. `get_weather(city: str)` — consulta OpenWeatherMap
> 2. `create_reminder(description: str, due_date: str)` — inserta en la tabla `reminders`
>
> Cada tool va en su propio archivo dentro de `services/tools/`, con una función `execute()` y un `schema` (descripción en formato JSON que Gemini necesita para saber cuándo llamarla).

**Criterio de aceptación:** enviar `"¿Qué clima hace en Montería?"` a `/chat` debe disparar la tool `get_weather` y devolver una respuesta con el dato real, no inventado.

---

## Fase 4 — Streaming de respuestas (SSE)

**Instrucción para el asistente:**
> Convierte el endpoint `/chat` para que responda usando Server-Sent Events (`StreamingResponse` de FastAPI), emitiendo: (a) eventos de "tool_start" cuando el agente decide ejecutar una función, (b) el texto de la respuesta token a token, (c) un evento final de cierre. Define un formato de evento simple en JSON para que el frontend lo pueda parsear fácilmente.

**Criterio de aceptación:** un cliente de prueba (curl o script Python) recibe los eventos en orden y puede reconstruir la respuesta completa.

---

## Fase 5 — Tercera tool (búsqueda web) + endpoints de soporte

**Instrucción para el asistente:**
> Implementa la tool `search_web(query: str)` usando scraping simple (BeautifulSoup) sobre resultados de DuckDuckGo, sin necesidad de API key. Añade los endpoints:
> - `GET /conversations` — lista las conversaciones existentes
> - `GET /conversations/{id}` — historial completo de una conversación
> - `DELETE /conversations/{id}` — elimina una conversación y sus mensajes (cascade)
> - `GET /tools` — devuelve la lista de tools disponibles con su descripción (para mostrarlas en el frontend)

---

## Fase 6 — Preparación para despliegue en Render

**Instrucción para el asistente:**
> Añade un `Procfile` o configura el `start command` para Render (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`). Verifica que todas las variables de entorno se lean correctamente desde el entorno (no hardcodeadas). Añade un endpoint `GET /health` que responda `200 OK` para que Render pueda hacer health checks. Documenta en el `README.md` los pasos exactos para desplegar: crear el Web Service en Render, conectar el repo de GitHub, configurar las variables de entorno, y el build/start command.

---

## Orden recomendado de ejecución

| Fase | Qué entrega | Depende de |
|---|---|---|
| 0 | Estructura del proyecto | — |
| 1 | BD conectada y modelos | Fase 0 |
| 2 | Chat básico sin tools | Fase 1 |
| 3 | Function calling + 2 tools | Fase 2 |
| 4 | Streaming (SSE) | Fase 3 |
| 5 | Tercera tool + endpoints de soporte | Fase 3 (puede ir en paralelo con Fase 4) |
| 6 | Despliegue en Render | Fase 4 y 5 |

**Recomendación:** ejecuta las fases una por una y verifica el criterio de aceptación de cada una antes de avanzar a la siguiente — así detectas errores temprano en vez de acumularlos.