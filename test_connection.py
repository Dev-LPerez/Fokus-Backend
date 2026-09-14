import asyncio
import sys
from uuid import uuid4
from sqlalchemy import select
from app.db.session import engine, AsyncSessionLocal, Base
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.reminder import Reminder
from app.core.config import settings

# Ensure utf-8 encoding on Windows standard output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


async def run_test():
    print(f"[*] Probando conexión a base de datos...")
    print(f"[*] Entorno: {settings.ENVIRONMENT}")
    print(f"[*] Host: {settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else settings.DATABASE_URL}")

    try:
        # Create tables if not present
        async with engine.begin() as conn:
            print("[*] Verificando / creando tablas en la base de datos...")
            await conn.run_sync(Base.metadata.create_all)
            print("[OK] Tablas verificadas exitosamente en Supabase.")

        # Test insert into Conversation
        async with AsyncSessionLocal() as session:
            test_id = uuid4()
            test_title = f"Test Conversation {test_id}"
            test_conv = Conversation(id=test_id, user_id=uuid4(), title=test_title)
            session.add(test_conv)
            await session.commit()
            print(f"[OK] Registro insertado en 'conversations' con ID: {test_id}")

            # Test query
            stmt = select(Conversation).where(Conversation.id == test_id)
            res = await session.execute(stmt)
            fetched = res.scalar_one_or_none()

            if fetched and fetched.title == test_title:
                print(f"[OK] Registro consultado exitosamente: {fetched.title}")
            else:
                print("[ERROR] No se pudo recuperar el registro insertado.")
                sys.exit(1)

            # Cleanup test record
            await session.delete(fetched)
            await session.commit()
            print("[OK] Registro de prueba limpiado correctamente.")

        print("\n=== ¡Prueba de conexión a Supabase y modelos completada con EXITO! ===")
    except Exception as e:
        print(f"\n[ERROR] Error al conectar con la base de datos: {str(e)}")
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_test())
