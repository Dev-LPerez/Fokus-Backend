"""
Google Calendar Service: Handles OAuth token refresh, event creation and event deletion.
"""

from datetime import datetime, timezone, timedelta, date, time
from typing import Optional, Dict, Any, List
from uuid import UUID
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.encryption import encrypt_token, decrypt_token
from app.core.timezone import COLOMBIA_TZ
from app.models.user_integration import UserIntegration


class GoogleCalendarNotConnected(Exception):
    """Raised when an operation is attempted for a user without an active Google Calendar integration."""
    pass


class GoogleCalendarError(Exception):
    """Raised when Google Calendar API returns an error."""
    pass


class GoogleCalendarService:
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

    async def get_user_integration(
        self,
        user_id: UUID,
        db: AsyncSession
    ) -> Optional[UserIntegration]:
        stmt = select(UserIntegration).where(
            UserIntegration.user_id == user_id,
            UserIntegration.provider == "google_calendar"
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_valid_access_token(
        self,
        user_id: UUID,
        db: AsyncSession
    ) -> str:
        integration = await self.get_user_integration(user_id, db)
        if not integration:
            raise GoogleCalendarNotConnected(f"El usuario {user_id} no tiene Google Calendar conectado.")

        now_utc = datetime.now(timezone.utc)
        # Refresh if token is expired or will expire in less than 2 minutes
        needs_refresh = (
            integration.token_expires_at is None or
            integration.token_expires_at <= now_utc + timedelta(minutes=2)
        )

        if not needs_refresh:
            return decrypt_token(integration.access_token_encrypted)

        refresh_token = decrypt_token(integration.refresh_token_encrypted)
        if not refresh_token:
            raise GoogleCalendarError("No se encontró refresh_token para renovar la sesión de Google.")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }
            )

        if resp.status_code != 200:
            raise GoogleCalendarError(
                f"Error al refrescar token de Google ({resp.status_code}): {resp.text}"
            )

        data = resp.json()
        new_access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)

        if not new_access_token:
            raise GoogleCalendarError("Google no retornó access_token en el refresco.")

        integration.access_token_encrypted = encrypt_token(new_access_token)
        integration.token_expires_at = now_utc + timedelta(seconds=expires_in)

        # Update refresh_token if Google rotated it
        if "refresh_token" in data:
            integration.refresh_token_encrypted = encrypt_token(data["refresh_token"])

        await db.commit()
        await db.refresh(integration)

        return new_access_token

    async def create_event(
        self,
        user_id: UUID,
        title: str,
        description: str,
        due_date: datetime,
        db: AsyncSession,
        duration_minutes: int = 60,
        end_date: Optional[datetime] = None
    ) -> str:
        """
        Creates an event in the user's primary Google Calendar with notifications.
        Returns the created Google Calendar event ID.
        """
        access_token = await self.get_valid_access_token(user_id, db)

        # Ensure datetime is localized or timezone-aware
        if due_date.tzinfo is None:
            due_date = due_date.replace(tzinfo=COLOMBIA_TZ)

        if end_date is not None:
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=COLOMBIA_TZ)
        else:
            end_date = due_date + timedelta(minutes=duration_minutes)

        start_time_iso = due_date.isoformat()
        end_time_iso = end_date.isoformat()

        event_payload: Dict[str, Any] = {
            "summary": title,
            "description": description,
            "start": {
                "dateTime": start_time_iso,
                "timeZone": "America/Bogota"
            },
            "end": {
                "dateTime": end_time_iso,
                "timeZone": "America/Bogota"
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 30},
                    {"method": "popup", "minutes": 30}
                ]
            }
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.CALENDAR_API_BASE,
                headers={"Authorization": f"Bearer {access_token}"},
                json=event_payload
            )

        if resp.status_code not in (200, 201):
            raise GoogleCalendarError(
                f"Error al crear evento en Google Calendar ({resp.status_code}): {resp.text}"
            )

        event_data = resp.json()
        event_id = event_data.get("id")
        if not event_id:
            raise GoogleCalendarError("Respuesta de Google Calendar no contiene ID del evento.")

        return event_id

    async def list_events(
        self,
        user_id: UUID,
        time_min: datetime,
        time_max: datetime,
        db: AsyncSession
    ) -> List[Dict[str, Any]]:
        """
        Lists events from user's primary Google Calendar between time_min and time_max.
        Returns structured list of events.
        """
        access_token = await self.get_valid_access_token(user_id, db)

        if time_min.tzinfo is None:
            time_min = time_min.replace(tzinfo=COLOMBIA_TZ)
        if time_max.tzinfo is None:
            time_max = time_max.replace(tzinfo=COLOMBIA_TZ)

        params = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime"
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                self.CALENDAR_API_BASE,
                headers={"Authorization": f"Bearer {access_token}"},
                params=params
            )

        if resp.status_code != 200:
            raise GoogleCalendarError(
                f"Error al listar eventos de Google Calendar ({resp.status_code}): {resp.text}"
            )

        data = resp.json()
        raw_items = data.get("items", [])

        events = []
        for item in raw_items:
            if item.get("status") == "cancelled":
                continue

            start_obj = item.get("start", {})
            end_obj = item.get("end", {})

            start_val = start_obj.get("dateTime") or start_obj.get("date")
            end_val = end_obj.get("dateTime") or end_obj.get("date")
            summ = item.get("summary", "Sin título") or "Sin título"
            desc = item.get("description", "") or ""

            # Key meeting heuristics
            is_key_meeting = False
            priority_reasons = []
            lower_comb = f"{summ} {desc}".lower()
            if any(platform in lower_comb for platform in ["meet.google.com", "zoom.us", "teams.microsoft.com", "webex.com"]):
                is_key_meeting = True
                priority_reasons.append("Videollamada con enlace")

            key_keywords = ["cliente", "client", "demo", "entrevista", "interview", "comité", "junta", "directiva", "review", "1:1", "one-on-one", "lanzamiento", "urgente", "evaluación"]
            for kw in key_keywords:
                if kw in lower_comb:
                    is_key_meeting = True
                    priority_reasons.append(f"Palabra clave: '{kw}'")
                    break

            events.append({
                "id": item.get("id"),
                "summary": summ,
                "start": start_val,
                "end": end_val,
                "description": desc,
                "is_key_meeting": is_key_meeting,
                "priority_reasons": priority_reasons
            })

        return events

    def detect_conflicts(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Detects overlapping events in the provided list of events.
        Returns a list of conflict objects with event pairs and overlap intervals.
        """
        parsed_events = []
        for ev in events:
            raw_start = ev.get("start")
            raw_end = ev.get("end")
            if not raw_start or not raw_end:
                continue
            try:
                if len(raw_start) == 10:
                    start_dt = datetime.combine(date.fromisoformat(raw_start), time.min).replace(tzinfo=COLOMBIA_TZ)
                else:
                    start_dt = datetime.fromisoformat(raw_start)
                    start_dt = start_dt.replace(tzinfo=COLOMBIA_TZ) if start_dt.tzinfo is None else start_dt.astimezone(COLOMBIA_TZ)

                if len(raw_end) == 10:
                    end_dt = datetime.combine(date.fromisoformat(raw_end), time.max).replace(tzinfo=COLOMBIA_TZ)
                else:
                    end_dt = datetime.fromisoformat(raw_end)
                    end_dt = end_dt.replace(tzinfo=COLOMBIA_TZ) if end_dt.tzinfo is None else end_dt.astimezone(COLOMBIA_TZ)

                parsed_events.append({
                    "id": ev.get("id"),
                    "summary": ev.get("summary", "Sin título"),
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "start_str": ev.get("start"),
                    "end_str": ev.get("end")
                })
            except Exception:
                continue

        conflicts = []
        n = len(parsed_events)
        for i in range(n):
            for j in range(i + 1, n):
                ev1 = parsed_events[i]
                ev2 = parsed_events[j]
                overlap_start = max(ev1["start_dt"], ev2["start_dt"])
                overlap_end = min(ev1["end_dt"], ev2["end_dt"])
                if overlap_start < overlap_end:
                    overlap_minutes = int((overlap_end - overlap_start).total_seconds() / 60)
                    if overlap_minutes > 0:
                        conflicts.append({
                            "event_a": {"id": ev1["id"], "summary": ev1["summary"], "start": ev1["start_str"], "end": ev1["end_str"]},
                            "event_b": {"id": ev2["id"], "summary": ev2["summary"], "start": ev2["start_str"], "end": ev2["end_str"]},
                            "overlap_start": overlap_start.strftime("%Y-%m-%d %H:%M"),
                            "overlap_end": overlap_end.strftime("%Y-%m-%d %H:%M"),
                            "overlap_minutes": overlap_minutes,
                            "warning": f"Conflicto de horario entre '{ev1['summary']}' y '{ev2['summary']}' ({overlap_minutes} min de cruce)."
                        })
        return conflicts

    async def find_free_slots(
        self,
        user_id: UUID,
        target_date: Any,
        min_duration_minutes: int,
        db: Optional[AsyncSession] = None,
        workday_start_hour: int = 8,
        workday_end_hour: int = 19,
        buffer_minutes: int = 0,
        events: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Calculates free time blocks between workday_start_hour and workday_end_hour
        for target_date that meet or exceed min_duration_minutes.
        Optional buffer_minutes applies margin between busy intervals.
        """
        # Ensure target_date is a date object
        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)
        elif isinstance(target_date, datetime):
            target_date = target_date.date()

        day_start = datetime(
            target_date.year, target_date.month, target_date.day,
            workday_start_hour, 0, 0, tzinfo=COLOMBIA_TZ
        )
        day_end = datetime(
            target_date.year, target_date.month, target_date.day,
            workday_end_hour, 0, 0, tzinfo=COLOMBIA_TZ
        )

        if events is None:
            if db is None:
                raise ValueError("db session is required when events are not provided.")
            # list_events checks if calendar is connected
            events = await self.list_events(
                user_id=user_id,
                time_min=day_start,
                time_max=day_end,
                db=db
            )

        # Collect and parse busy intervals
        busy_intervals = []
        for ev in events:
            raw_start = ev.get("start")
            raw_end = ev.get("end")
            if not raw_start or not raw_end:
                continue

            try:
                # Handle all-day dates (YYYY-MM-DD)
                if len(raw_start) == 10:
                    start_dt = datetime.combine(date.fromisoformat(raw_start), time.min).replace(tzinfo=COLOMBIA_TZ)
                else:
                    start_dt = datetime.fromisoformat(raw_start)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=COLOMBIA_TZ)
                    else:
                        start_dt = start_dt.astimezone(COLOMBIA_TZ)

                if len(raw_end) == 10:
                    end_dt = datetime.combine(date.fromisoformat(raw_end), time.min).replace(tzinfo=COLOMBIA_TZ)
                else:
                    end_dt = datetime.fromisoformat(raw_end)
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=COLOMBIA_TZ)
                    else:
                        end_dt = end_dt.astimezone(COLOMBIA_TZ)
            except Exception:
                continue

            # Apply smart buffer if requested
            if buffer_minutes > 0:
                buffered_start = start_dt - timedelta(minutes=buffer_minutes)
                buffered_end = end_dt + timedelta(minutes=buffer_minutes)
            else:
                buffered_start = start_dt
                buffered_end = end_dt

            # Clip interval to workday bounds
            if buffered_end <= day_start or buffered_start >= day_end:
                continue

            clamped_start = max(day_start, buffered_start)
            clamped_end = min(day_end, buffered_end)

            if clamped_start < clamped_end:
                busy_intervals.append((clamped_start, clamped_end))

        # Merge overlapping/contiguous busy intervals
        busy_intervals.sort(key=lambda x: x[0])
        merged_busy = []
        for interval in busy_intervals:
            if not merged_busy:
                merged_busy.append([interval[0], interval[1]])
            else:
                last_start, last_end = merged_busy[-1]
                if interval[0] <= last_end:
                    merged_busy[-1][1] = max(last_end, interval[1])
                else:
                    merged_busy.append([interval[0], interval[1]])

        # Find free slots between day_start and day_end
        free_slots = []
        current = day_start

        for b_start, b_end in merged_busy:
            if b_start > current:
                duration = int((b_start - current).total_seconds() / 60)
                if duration >= min_duration_minutes:
                    free_slots.append({
                        "start": current.strftime("%Y-%m-%d %H:%M"),
                        "end": b_start.strftime("%Y-%m-%d %H:%M"),
                        "duration_minutes": duration
                    })
            current = max(current, b_end)

        if current < day_end:
            duration = int((day_end - current).total_seconds() / 60)
            if duration >= min_duration_minutes:
                free_slots.append({
                    "start": current.strftime("%Y-%m-%d %H:%M"),
                    "end": day_end.strftime("%Y-%m-%d %H:%M"),
                    "duration_minutes": duration
                })

        return free_slots

    async def delete_event(
        self,
        user_id: UUID,
        event_id: str,
        db: AsyncSession
    ) -> bool:
        """
        Deletes an event from the user's primary Google Calendar.
        Returns True if deleted or already gone (404/410).
        """
        try:
            access_token = await self.get_valid_access_token(user_id, db)
        except GoogleCalendarNotConnected:
            return False

        url = f"{self.CALENDAR_API_BASE}/{event_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                url,
                headers={"Authorization": f"Bearer {access_token}"}
            )

        # 204 No Content is success; 404 or 410 means already deleted
        if resp.status_code in (200, 204, 404, 410):
            return True

        raise GoogleCalendarError(
            f"Error al eliminar evento en Google Calendar ({resp.status_code}): {resp.text}"
        )


google_calendar_service = GoogleCalendarService()
