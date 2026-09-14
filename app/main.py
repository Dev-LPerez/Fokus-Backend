from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.routers import (
    chat_router,
    conversations_router,
    tools_router,
    health_router,
    integrations_router,
    briefing_router,
    reminders_router,
    onboarding_router,
    calendar_router,
)

app = FastAPI(
    title="Fokus API — Personal & Professional Growth Platform",
    description="Backend API for Fokus: conversational AI Agent with autonomous tool execution, Google Calendar sync, and Eisenhower task management for personal and professional growth.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS (RNF-09)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins if settings.ENVIRONMENT == "production" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Exception Handler (RNF-08)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": "Ocurrió un error inesperado al procesar la solicitud." if settings.ENVIRONMENT == "production" else str(exc)
        }
    )

# Include routers
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(tools_router)
app.include_router(integrations_router)
app.include_router(briefing_router)
app.include_router(reminders_router)
app.include_router(onboarding_router)
app.include_router(calendar_router)


@app.get("/")
async def root():
    return {
        "message": "AI Agent Backend is running",
        "docs": "/docs",
        "health": "/health",
        "tools": "/tools"
    }
