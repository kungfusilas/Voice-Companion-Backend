"""Tavily web search integration for real-time information."""
import os
import asyncio


_client = None


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return None
        try:
            from tavily import TavilyClient
            _client = TavilyClient(api_key=api_key)
        except Exception:
            return None
    return _client


def search_sync(query: str, max_results: int = 5) -> str:
    """Run a Tavily search synchronously and return formatted results as a string."""
    client = _get_client()
    if not client:
        return "Web search is unavailable (TAVILY_API_KEY not configured)."
    try:
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=max_results,
            include_answer=True,
        )
        parts = []
        answer = response.get("answer")
        if answer:
            parts.append(f"Summary: {answer}")
        for r in response.get("results", []):
            title = r.get("title", "")
            url = r.get("url", "")
            content = r.get("content", "")
            parts.append(f"**{title}**\n{url}\n{content}")
        return "\n\n---\n\n".join(parts) if parts else "No results found."
    except Exception as e:
        return f"Search failed: {str(e)}"


async def search(query: str, max_results: int = 5) -> str:
    """Async wrapper — runs the Tavily call in a thread pool."""
    return await asyncio.to_thread(search_sync, query, max_results)
