# Backend — Agente de IA con Function Calling

Backend desarrollado en **FastAPI** para un agente conversacional de Inteligencia Artificial que ejecuta herramientas (function calling) de manera autónoma con **Google Gemini (`google-genai`)**, persistencia y autenticación multiusuario en **Supabase (PostgreSQL & Supabase Auth)** y despliegue en **Render**.

---

## 🛠️ Stack Tecnológico

- **Framework Web:** FastAPI (Python 3.10+)
- **LLM & Function Calling:** Google Gemini API (`google-genai==2.19.0`)
- **Autenticación:** Supabase Auth (Verificación asimétrica local vía JWKS / ES256 & RS256 con PyJWT)
- **Base de Datos:** PostgreSQL en Supabase gestionado vía SQLAlchemy (Asyncio + Asyncpg)
- **Migraciones:** Alembic
- **Peticiones HTTP & Scraping:** HTTPX, BeautifulSoup4
- **Resiliencia & Rate Limiting:** Tenacity (Retry con backoff exponencial y Fallback de modelo)
- **Zona Horaria:** Colombia (`America/Bogota` / UTC-5)
- **Despliegue:** Render (Web Service Free Tier)

---

## 📂 Estructura del Proyecto

```
Backend/
├── app/
│   ├── main.py                 # Punto de entrada FastAPI, middlewares y rutas
│   ├── core/
│   │   ├── config.py           # Configuración y variables de entorno (Pydantic Settings)
│   │   ├── auth.py             # Verificación de JWT con JWKS y dependencia get_current_user
│   │   └── timezone.py         # Manejo de zona horaria Colombia (America/Bogota)
│   ├── db/
│   │   └── session.py          # Sesión asíncrona y motor SQLAlchemy
│   ├── models/                 # Modelos SQLAlchemy (Conversations, Messages, Reminders)
│   │   ├── conversation.py
│   │   ├── message.py
│   │   └── reminder.py
│   ├── schemas/                # Esquemas Pydantic para request/response y streaming
│   │   ├── chat.py
│   │   ├── conversation.py
│   │   ├── reminder.py
│   │   └── tool.py
│   ├── routers/                # Endpoints protegidos y públicos
│   │   ├── chat.py             # Chat con streaming SSE o JSON (Protegido)
│   │   ├── conversations.py    # CRUD de conversaciones con aislamiento por usuario (Protegido)
│   │   ├── tools.py            # Catálogo de tools registradas (Público)
│   │   └── health.py           # Health check del servicio y DB (Público)
│   └── services/
│       ├── gemini_client.py    # Cliente Gemini con retry asíncrono
│       ├── agent.py            # Orquestador del agente, function calling y fallback de modelo
│       └── tools/              # Tools modulares con registro desacoplado
│           ├── base.py
│           ├── registry.py
│           ├── weather.py      # Consulta clima vía OpenWeatherMap
│           ├── reminders.py    # Persistencia de recordatorios asociados a user_id
│           └── web_search.py   # Búsqueda web scraping DuckDuckGo
├── migrations/                 # Migraciones Alembic
├── tests/                      # Suite de pruebas automatizadas (100% aisladas con mocks)
├── .env.example                # Plantilla de variables de entorno
├── Procfile                    # Comando de inicio para Render
├── render.yaml                 # Blueprint de infraestructura en Render
├── requirements.txt            # Dependencias fijadas
└── README.md
```

---

## ⚙️ Variables de Entorno

Crea un archivo `.env` en la raíz del proyecto tomando como base `.env.example`:

| Variable | Descripción | Ejemplo / Default |
|---|---|---|
| `GEMINI_API_KEY` | API Key de Google AI Studio | `AIzaSy...` |
| `DATABASE_URL` | String de conexión asíncrono a PostgreSQL (Supabase) | `postgresql+asyncpg://postgres:pass@db.supabase.co:5432/postgres` |
| `OPENWEATHER_API_KEY` | API Key de OpenWeatherMap | `a1b2c3d4...` |
| `SUPABASE_URL` | URL de tu proyecto en Supabase para JWKS | `https://xxxx.supabase.co` |
| `ENVIRONMENT` | Entorno de ejecución (`development` / `production`) | `development` |
| `FRONTEND_URL` | URL del frontend en Next.js (Vercel) para CORS | `http://localhost:3000` |
| `GEMINI_MODEL` | Modelo de Gemini principal | `gemini-3.5-flash-lite` |
| `GEMINI_FALLBACK_MODEL` | Modelo de Gemini fallback | `gemini-3.1-flash-lite` |

---

## 🔒 Autenticación y Aislamiento de Usuarios

El backend utiliza **Supabase Auth**:
1. El frontend gestiona el registro/login directamente con Supabase y obtiene un token JWT.
2. El frontend incluye el token en el header `Authorization: Bearer <token>`.
3. El backend verifica la firma del token localmente mediante **JWKS (`/auth/v1/.well-known/jwks.json`)** cacheado en memoria, extrayendo el `user_id`.
4. Cada usuario solo puede ver, consultar o eliminar sus propias conversaciones y recordatorios. Intentos no autorizados retornan `404 Not Found`.

---

## 📡 Endpoints de la API

| Método | Ruta | Auth Requerida | Descripción |
|---|---|---|---|
| `POST` | `/chat` | `Bearer JWT` | Envía mensaje al agente. Soporta streaming SSE (`?stream=true`) y JSON (`?stream=false`). |
| `GET` | `/conversations` | `Bearer JWT` | Lista las conversaciones del usuario autenticado. |
| `GET` | `/conversations/{id}` | `Bearer JWT` | Historial completo de una conversación del usuario. |
| `DELETE` | `/conversations/{id}` | `Bearer JWT` | Elimina una conversación y sus mensajes asociados en cascada. |
| `GET` | `/tools` | Ninguna | Lista el catálogo de herramientas disponibles para el agente. |
| `GET` | `/health` | Ninguna | Health check del backend y verificación de conexión a PostgreSQL. |

---

## 🧪 Pruebas Automatizadas

Para ejecutar las pruebas aisladas (sin requerir red ni credenciales externas):
```bash
pytest -v
```

---

## ☁️ Despliegue en Render

1. **Subir el código a GitHub:**
   Asegúrate de incluir `requirements.txt`, `Procfile`, `render.yaml` y la carpeta `app/`.

2. **Crear Web Service en Render:**
   - Conecta tu repositorio de GitHub en [Render Dashboard](https://dashboard.render.com).
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

3. **Configurar Variables de Entorno en Render:**
   - `GEMINI_API_KEY`: Tu clave de Google AI Studio.
   - `DATABASE_URL`: Cadena asíncrona de Supabase (`postgresql+asyncpg://...`).
   - `OPENWEATHER_API_KEY`: Tu clave de OpenWeatherMap.
   - `SUPABASE_URL`: `https://<tu-proyecto>.supabase.co`
   - `ENVIRONMENT`: `production`
   - `FRONTEND_URL`: URL del frontend en Vercel.
