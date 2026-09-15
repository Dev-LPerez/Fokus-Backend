import logging
from typing import Any, Dict, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.user_preference import UserPreference
from .base import BaseTool

logger = logging.getLogger(__name__)


class SetUserLocationTool(BaseTool):
    name = "set_user_location"
    description = "Establece y memoriza la ciudad habitual de residencia del usuario en sus preferencias para futuras consultas de clima, Daily Briefing y planificación local sin tener que volver a preguntarla."
    parameters = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "Nombre de la ciudad del usuario (ej. 'Medellín', 'Cali', 'Montería', 'Barranquilla', 'Madrid')."
            }
        },
        "required": ["city"]
    }

    async def execute(
        self,
        city: str,
        db: Optional[AsyncSession] = None,
        user_id: Optional[UUID] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        if user_id is None:
            return {
                "success": False,
                "error": "user_id es requerido para guardar la ciudad del usuario."
            }

        cleaned_city = city.strip().title()

        async def _run(session: AsyncSession) -> Dict[str, Any]:
            stmt = select(UserPreference).where(UserPreference.user_id == user_id)
            res = await session.execute(stmt)
            pref = res.scalar_one_or_none()

            if pref:
                pref.city = cleaned_city
            else:
                pref = UserPreference(
                    user_id=user_id,
                    city=cleaned_city
                )
                session.add(pref)

            await session.commit()
            await session.refresh(pref)

            return {
                "success": True,
                "city": cleaned_city,
                "message": f"Ubicación preferida configurada con éxito: {cleaned_city}. Ahora Fokus utilizará esta ciudad automáticamente para tu Daily Briefing y clima."
            }

        if db is not None:
            return await _run(db)
        async with AsyncSessionLocal() as session:
            return await _run(session)
