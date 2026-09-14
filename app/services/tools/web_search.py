import httpx
from bs4 import BeautifulSoup
from typing import Any, Dict, List
import urllib.parse
from .base import BaseTool


class WebSearchTool(BaseTool):
    name = "search_web"
    description = "Busca información actualizada en la web usando DuckDuckGo."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Término o frase de búsqueda (ej. 'noticias inteligencia artificial hoy')"
            }
        },
        "required": ["query"]
    }

    async def execute(self, query: str, **kwargs: Any) -> Dict[str, Any]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0.0.0 Safari/537.36"
            )
        }
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
                if response.status_code != 200:
                    return {
                        "query": query,
                        "results": [],
                        "error": f"DuckDuckGo respondió con código {response.status_code}"
                    }

                soup = BeautifulSoup(response.text, "html.parser")
                results: List[Dict[str, str]] = []

                result_elements = soup.find_all("div", class_="result")
                for el in result_elements[:4]:
                    title_el = el.find("a", class_="result__a")
                    snippet_el = el.find("a", class_="result__snippet")
                    if title_el:
                        title = title_el.get_text(strip=True)
                        raw_link = title_el.get("href", "")
                        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

                        # Extract actual URL if it's a DuckDuckGo redirect
                        link = raw_link
                        if "uddg=" in raw_link:
                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_link).query)
                            if "uddg" in parsed:
                                link = parsed["uddg"][0]

                        results.append({
                            "title": title,
                            "snippet": snippet,
                            "link": link
                        })

                return {
                    "query": query,
                    "results_count": len(results),
                    "results": results
                }
        except httpx.RequestError as exc:
            return {
                "query": query,
                "results": [],
                "error": f"Error de conexión al buscar en la web: {str(exc)}"
            }
        except Exception as exc:
            return {
                "query": query,
                "results": [],
                "error": f"Error inesperado al procesar la búsqueda: {str(exc)}"
            }
