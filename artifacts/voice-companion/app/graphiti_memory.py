"""
Graphiti knowledge-graph memory layer.

add_episode  — fire-and-forget: persist a conversation turn as a graph episode
search_graph — retrieve relevant graph facts for a query; returns formatted
               string or '' on any error / when Neo4j is not configured

Both functions are safe to call unconditionally.  They short-circuit
immediately when NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD are absent, and
wrap every API call in try/except so no exception ever reaches the caller.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Lazy singleton — None = not yet attempted, False = init failed, else instance
_graphiti_instance = None
_init_lock: asyncio.Lock | None = None


def _neo4j_configured() -> bool:
    return bool(
        os.environ.get("NEO4J_URI")
        and os.environ.get("NEO4J_USERNAME")
        and os.environ.get("NEO4J_PASSWORD")
    )


async def _get_graphiti():
    """Return the shared Graphiti instance, initialising it on first call."""
    global _graphiti_instance, _init_lock
    if _graphiti_instance is False:
        return None
    if _graphiti_instance is not None:
        return _graphiti_instance
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    async with _init_lock:
        # Re-check under the lock (another coroutine may have raced us)
        if _graphiti_instance is not None:
            return _graphiti_instance if _graphiti_instance is not False else None
        try:
            from graphiti_core import Graphiti  # noqa: PLC0415
            from graphiti_core.llm_client.anthropic_client import AnthropicClient
            from graphiti_core.embedder.openai import OpenAIEmbedder

            llm = AnthropicClient(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
            embedder = OpenAIEmbedder(api_key=os.environ.get("OPENAI_API_KEY", ""))
            g = Graphiti(
                os.environ["NEO4J_URI"],
                os.environ["NEO4J_USERNAME"],
                os.environ["NEO4J_PASSWORD"],
                llm_client=llm,
                embedder=embedder,
            )
            await g.build_indices_and_constraints()
            _graphiti_instance = g
            logger.info("[graphiti] initialised successfully")
        except Exception as exc:
            logger.warning("[graphiti] init failed — graph memory disabled: %r", exc)
            _graphiti_instance = False
            return None
    return _graphiti_instance


async def add_episode(user_id: str, user_msg: str, ai_msg: str) -> None:
    """
    Persist a conversation turn as a Graphiti graph episode.
    Fire-and-forget — never raises, returns None on any error.
    """
    if not _neo4j_configured():
        return
    try:
        g = await _get_graphiti()
        if g is None:
            return
        from graphiti_core.nodes import EpisodeType  # noqa: PLC0415
        await g.add_episode(
            name=f"bondai_{user_id}_{datetime.now(timezone.utc).isoformat()}",
            episode_body=f"User: {user_msg}\nCompanion: {ai_msg}",
            source_description="BondAI conversation",
            reference_time=datetime.now(timezone.utc),
            source=EpisodeType.text,
            group_id=user_id,
        )
        logger.debug("[graphiti] add_episode ok user=%s", user_id[:8])
    except Exception as exc:
        logger.warning("[graphiti] add_episode failed user=%s: %r", user_id[:8], exc)


async def search_graph(user_id: str, query: str) -> str:
    """
    Search the knowledge graph for facts relevant to *query* scoped to *user_id*.
    Returns a newline-separated list of fact strings, or '' on any error.
    """
    if not _neo4j_configured():
        return ""
    try:
        g = await _get_graphiti()
        if g is None:
            return ""
        results = await g.search(query, group_ids=[user_id], num_results=5)
        if not results:
            return ""
        lines: list[str] = []
        for r in results:
            fact = getattr(r, "fact", None) or getattr(r, "name", None) or str(r)
            if fact and fact.strip():
                lines.append(f"- {fact.strip()}")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("[graphiti] search_graph failed user=%s: %r", user_id[:8], exc)
        return ""
