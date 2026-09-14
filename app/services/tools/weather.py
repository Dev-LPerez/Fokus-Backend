import httpx
from typing import Any, Dict, Optional
from app.core.config import settings
from .base import BaseTool


class WeatherTool(BaseTool):
    name = "get_weather"
    description = "Obtiene el clima actual y pronóstico básico para una ciudad dada o mediante coordenadas geográficas (latitud y longitud)."
    parameters = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "Nombre de la ciudad (por ejemplo, 'Montería', 'Bogotá', 'Medellín', 'Madrid', 'Ciudad de México'). Opcional si se proporcionan coordenadas."
            },
            "latitude": {
                "type": "number",
                "description": "Latitud geográfica del usuario (ej. 8.7479). Opcional si se proporciona ciudad."
            },
            "longitude": {
                "type": "number",
                "description": "Longitud geográfica del usuario (ej. -75.8814). Opcional si se proporciona ciudad."
            }
        },
        "required": []
    }

    async def execute(
        self,
        city: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        api_key = settings.OPENWEATHER_API_KEY
        if not api_key:
            return {
                "error": "API key de OpenWeatherMap no configurada.",
                "city": city or "Ubicación desconocida",
                "status": "unavailable"
            }

        url = "https://api.openweathermap.org/data/2.5/weather"
        params: Dict[str, Any] = {
            "appid": api_key,
            "units": "metric",
            "lang": "es"
        }

        if latitude is not None and longitude is not None:
            params["lat"] = latitude
            params["lon"] = longitude
        elif city and city.strip():
            params["q"] = city.strip()
        else:
            return {
                "error": "Debes proporcionar una ciudad o coordenadas (latitud y longitud) para consultar el clima.",
                "status": "missing_location"
            }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params)

                if response.status_code == 200:
                    data = response.json()
                    detected_city = data.get("name") or city or "Ubicación detectada"
                    return {
                        "city": detected_city,
                        "country": data.get("sys", {}).get("country", ""),
                        "temperature": data.get("main", {}).get("temp"),
                        "feels_like": data.get("main", {}).get("feels_like"),
                        "temp_min": data.get("main", {}).get("temp_min"),
                        "temp_max": data.get("main", {}).get("temp_max"),
                        "humidity": data.get("main", {}).get("humidity"),
                        "description": data.get("weather", [{}])[0].get("description", ""),
                        "wind_speed": data.get("wind", {}).get("speed")
                    }
                elif response.status_code == 404:
                    loc_name = city or f"coordenadas ({latitude}, {longitude})"
                    return {"error": f"No se encontró la ciudad o ubicación '{loc_name}'.", "city": city}
                else:
                    return {
                        "error": f"Error al consultar el clima (código {response.status_code}).",
                        "city": city
                    }
        except httpx.RequestError as exc:
            return {
                "error": f"Error de conexión con el servicio de clima: {str(exc)}",
                "city": city
            }
        except Exception as exc:
            return {
                "error": f"Error inesperado al obtener el clima: {str(exc)}",
                "city": city
            }

