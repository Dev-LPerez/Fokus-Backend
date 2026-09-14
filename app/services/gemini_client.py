import logging
from google import genai
from google.genai import types
from google.genai.errors import APIError, ServerError, ClientError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from typing import Optional, Any
from app.core.config import settings

logger = logging.getLogger(__name__)


def is_transient_gemini_error(exc: BaseException) -> bool:
    """Returns True if the exception is a rate limit or transient service error."""
    if isinstance(exc, APIError):
        code = getattr(exc, "code", None)
        if code in (429, 500, 502, 503, 504):
            return True
        # Check error message for rate limit / quota
        msg = str(exc).lower()
        if "resource_exhausted" in msg or "quota" in msg or "rate limit" in msg or "429" in msg or "503" in msg:
            return True
    return False


# Global async retry decorator for Gemini API calls to handle rate limits (~15 req/min in free tier)
gemini_retry = retry(
    retry=retry_if_exception(is_transient_gemini_error),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    reraise=True
)


class GeminiClient:
    def __init__(self):
        self._client: Optional[genai.Client] = None

    def get_client(self) -> genai.Client:
        if self._client is None:
            if not settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY no está configurada en las variables de entorno.")
            self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._client


gemini_client = GeminiClient()
