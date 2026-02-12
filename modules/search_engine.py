"""
Модуль для поиска и извлечения информации из веб-страниц.
Использует DuckDuckGo для поиска и базовый scraping для сбора фактов.
"""
import re
import html
import socket
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import List, Dict, Optional

from ddgs import DDGS

from core.logger import logger
from core.cache import cache


class SearchEngine:
    """Провайдер поиска и извлечения данных из Интернета."""

    def __init__(self, max_results: int = 5, request_timeout: int = 10):
        self.max_results = max_results
        self.request_timeout = request_timeout

    def search(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, str]]:
        """Выполняет поиск в веб-сети."""
        limit = max_results or self.max_results

        cache_key = f"search_{query}_{limit}"
        cached_results = cache.get(cache_key)
        if cached_results:
            logger.info(f"Результаты поиска для '{query}' взяты из кэша")
            return cached_results

        try:
            logger.info(f"Выполнение веб-поиска: {query}")
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=limit))
                cache.set(results, cache_key, ttl=1800)
                return results
        except Exception as e:
            logger.error(f"Ошибка при выполнении поиска: {e}")
            return []

    def fetch_page_text(self, url: str, max_chars: int = 6000) -> str:
        """Скачивает страницу и извлекает из неё основной текст."""
        cache_key = f"page_text_{url}_{max_chars}"
        cached_text = cache.get(cache_key)
        if cached_text:
            return cached_text

        try:
            request = Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"
                    )
                }
            )

            with urlopen(request, timeout=self.request_timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                    return ""

                raw_html = response.read().decode("utf-8", errors="ignore")

            text = self._extract_text_from_html(raw_html)
            text = re.sub(r"\s+", " ", text).strip()
            text = text[:max_chars]

            cache.set(text, cache_key, ttl=1800)
            return text

        except (TimeoutError, socket.timeout):
            logger.warning(f"Таймаут при открытии страницы: {url}")
            return ""
        except Exception as e:
            logger.warning(f"Не удалось извлечь страницу {url}: {e}")
            return ""

    def scrape_search_results(
        self,
        results: List[Dict[str, str]],
        max_pages: int = 3,
        per_page_chars: int = 4000
    ) -> List[Dict[str, str]]:
        """Открывает несколько найденных страниц и извлекает текст."""
        scraped: List[Dict[str, str]] = []

        for result in results:
            if len(scraped) >= max_pages:
                break

            url = result.get("href", "")
            title = result.get("title", "Без названия")
            snippet = result.get("body", "")
            if not url or not url.startswith(("http://", "https://")):
                continue

            page_text = self.fetch_page_text(url, max_chars=per_page_chars)
            if not page_text:
                continue

            scraped.append(
                {
                    "title": title,
                    "href": url,
                    "domain": urlparse(url).netloc,
                    "snippet": snippet,
                    "content": page_text,
                }
            )

        return scraped

    def should_use_web_search(self, question: str, mode: str = "auto", triggers: Optional[List[str]] = None) -> bool:
        """Решает, нужен ли веб-поиск для вопроса."""
        normalized_mode = str(mode or "auto").lower().strip()
        if normalized_mode == "always":
            return True
        if normalized_mode == "off":
            return False

        q = question.lower().strip()
        if not q:
            return False

        quick_signals = ["http://", "https://", "ссылка", "источник", "пруф", "последние", "сегодня", "сейчас"]
        if any(signal in q for signal in quick_signals):
            return True

        trigger_words = triggers or []
        return any(word in q for word in trigger_words)

    def gather_web_context(
        self,
        question: str,
        max_results: int = 7,
        max_pages: int = 3,
        per_page_chars: int = 3500
    ) -> Dict[str, object]:
        """Полный цикл: поиск -> скрапинг -> форматирование контекста."""
        try:
            search_results = self.search(question, max_results=max_results)
        except TypeError:
            # Совместимость с возможными старыми сигнатурами после merge-конфликтов
            search_results = self.search(question)

        scraped_pages: List[Dict[str, str]] = []
        if search_results:
            try:
                scraped_pages = self.scrape_search_results(
                    search_results,
                    max_pages=max_pages,
                    per_page_chars=per_page_chars
                )
            except TypeError:
                scraped_pages = self.scrape_search_results(search_results)

        source_urls = [page["href"] for page in scraped_pages[:5]]
        if not source_urls:
            source_urls = [res.get("href", "") for res in search_results[:3] if res.get("href")]

        return {
            "search_results": search_results,
            "scraped_pages": scraped_pages,
            "web_context": self.format_results_for_ai(search_results),
            "scraped_context": self.format_scraped_for_ai(scraped_pages),
            "memory_summary": self.build_memory_summary(question, scraped_pages),
            "source_urls": source_urls,
        }

    def format_results_for_ai(self, results: List[Dict[str, str]]) -> str:
        """Преобразует результаты поиска в текстовый блок для промпта."""
        if not results:
            return "Результаты поиска отсутствуют."

        formatted = ["🌐 **РЕЗУЛЬТАТЫ ПОИСКА В СЕТИ:**"]
        for i, res in enumerate(results, 1):
            formatted.append(f"{i}. **{res.get('title', 'Без названия')}**")
            formatted.append(f"   Ссылка: {res.get('href', '-')}")
            formatted.append(f"   Описание: {res.get('body', '')}\n")

        return "\n".join(formatted)

    def format_scraped_for_ai(self, scraped_pages: List[Dict[str, str]], max_chars_total: int = 12000) -> str:
        """Форматирует скраповый контент из нескольких страниц для AI."""
        if not scraped_pages:
            return "Не удалось загрузить содержимое веб-страниц."

        parts: List[str] = ["📚 **ИЗВЛЕЧЕННЫЕ ДАННЫЕ СО СТРАНИЦ:**"]
        used = 0

        for i, page in enumerate(scraped_pages, 1):
            block = (
                f"\n[{i}] {page['title']}\n"
                f"URL: {page['href']}\n"
                f"Домен: {page['domain']}\n"
                f"Сниппет: {page['snippet']}\n"
                f"Текст: {page['content'][:3500]}\n"
            )

            if used + len(block) > max_chars_total:
                break

            parts.append(block)
            used += len(block)

        return "\n".join(parts)

    def build_memory_summary(self, query: str, scraped_pages: List[Dict[str, str]], max_points: int = 5) -> str:
        """Строит компактную выжимку для сохранения в контексте диалога."""
        if not scraped_pages:
            return f"Запрос: {query}. Страницы не удалось извлечь."

        lines = [f"Запрос: {query}", "Ключевые источники:"]
        for i, page in enumerate(scraped_pages[:max_points], 1):
            short_text = page["content"][:240].replace("\n", " ")
            lines.append(
                f"{i}) {page['title']} ({page['domain']}) — {short_text}..."
            )

        return "\n".join(lines)

    def _extract_text_from_html(self, raw_html: str) -> str:
        """Грубое извлечение видимого текста из HTML без внешних зависимостей."""
        cleaned = re.sub(r"<script[\s\S]*?</script>", " ", raw_html, flags=re.IGNORECASE)
        cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<noscript[\s\S]*?</noscript>", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = html.unescape(cleaned)
        return cleaned


# Глобальный экземпляр
search_engine = SearchEngine()
