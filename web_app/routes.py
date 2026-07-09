import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .cache import cache_get, cache_key, cache_set
from .clients import close_clients
from .config import config, get_cfg, llm_provider, load_config
from .llm import llm_chat_full, llm_chat_stream
from .models import ChatRequest, ResearchWithKeyRequest, SearchRequest
from .search import _search_rvtdocs, build_context, search_qdrant

from portable.paths import get_base_dir


def _safe_format(template: str, **kwargs) -> str:
    try:
        return template.format(**kwargs)
    except KeyError:
        return template

_logger: logging.Logger = None
STATIC_DIR = get_base_dir() / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, _logger
    config.update(load_config())
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(name)s: %(message)s")
    _logger = logging.getLogger("revitnavis-web")
    provider = llm_provider()
    _logger.info("Web App config loaded. Qdrant: %s", get_cfg("qdrant", "url"))
    _logger.info("LLM provider: %s", provider)
    if provider == "ollama":
        _logger.info("Ollama: %s | embed=%s, chat=%s",
            get_cfg("ollama", "base_url"),
            get_cfg("ollama", "embedding_model"),
            get_cfg("ollama", "chat_model"),
        )
    else:
        _logger.info("Models: embed=%s, llm=%s", get_cfg("llm", "embedding_model"), get_cfg("llm", "chat_model"))
        if not os.environ.get("ROUTERAI_API_KEY"):
            _logger.warning("ROUTERAI_API_KEY not set — LLM endpoints will fail")
    yield
    await close_clients()


app = FastAPI(
    title="RevitNavis Researcher",
    description="Поиск по документации Revit API и Navisworks API",
    version="1.0.0",
    lifespan=lifespan,
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        content = index_path.read_text(encoding="utf-8")
        return HTMLResponse(content)
    return HTMLResponse("<h1>RevitNavis Researcher</h1><p>Frontend not found. Run with static/index.html</p>")


@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    chat_path = STATIC_DIR / "chat.html"
    if chat_path.exists():
        content = chat_path.read_text(encoding="utf-8")
        return HTMLResponse(content)
    return HTMLResponse("<h1>Chat page not found</h1>")


@app.get("/api/config")
async def api_config():
    provider = llm_provider()
    return {
        "collections": [
            {"name": "revit_api_knowledge", "label": "Revit API"},
            {"name": "Revit_SDK_Samples", "label": "Revit SDK Samples"},
            {"name": "navisworks_api_bge", "label": "Navisworks API"},
        ],
        "revit_versions": ["all (2022-2027)"],
        "llm_provider": provider,
        "llm_model": get_cfg("ollama" if provider == "ollama" else "llm", "chat_model"),
        "embedding_model": get_cfg("ollama" if provider == "ollama" else "llm", "embedding_model"),
        "has_api_key": bool(os.environ.get("ROUTERAI_API_KEY")),
    }


@app.post("/api/search/qdrant")
async def api_search_qdrant(req: SearchRequest):
    return await search_qdrant(req)


@app.post("/api/search/rvtdocs")
async def api_search_rvtdocs(req: SearchRequest):
    from .search import search_rvtdocs_endpoint
    return await search_rvtdocs_endpoint(req)


@app.post("/api/research")
async def api_research(req: SearchRequest):
    if llm_provider() != "ollama" and not os.environ.get("ROUTERAI_API_KEY"):
        raise HTTPException(400, "ROUTERAI_API_KEY not set (or set LLM_PROVIDER=ollama)")
    try:
        qdrant_results, rvtdocs_results, context = await build_context(req)

        analysis = await llm_chat_full(
            [{"role": "user", "content": f"## Question\n{req.query}\n\n## Search Results\n{context}"}],
            system=_safe_format(
                get_cfg("prompts", "web_research", default=""),
                revit_version=req.revit_version,
            ),
        )
        return {
            "query": req.query, "revit_version": req.revit_version, "collections": req.collections,
            "qdrant_count": qdrant_results.get("count", 0),
            "rvtdocs_count": rvtdocs_results.get("count", 0),
            "qdrant_results": qdrant_results.get("results", [])[:8],
            "rvtdocs_results": rvtdocs_results.get("results", [])[:5],
            "analysis": analysis,
        }
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("research failed: %s", e, exc_info=True)
        raise HTTPException(500, str(e))


@app.post("/api/research/stream")
async def api_research_stream(req: SearchRequest):
    """SSE endpoint: Qdrant -> rvtdocs -> streaming LLM"""
    if llm_provider() != "ollama" and not os.environ.get("ROUTERAI_API_KEY"):
        raise HTTPException(400, "ROUTERAI_API_KEY not set (or set LLM_PROVIDER=ollama)")

    async def _event_stream():
        try:
            yield "event: status\ndata: {\"msg\":\"Поиск в Qdrant...\"}\n\n"
            qdrant_results, rvtdocs_results, context = await build_context(req)
            qdrant_json = {
                "qdrant_count": qdrant_results.get("count", 0),
                "qdrant_results": qdrant_results.get("results", [])[:8],
            }
            yield f"event: qdrant\ndata: {json.dumps(qdrant_json, ensure_ascii=False)}\n\n"

            yield "event: status\ndata: {\"msg\":\"Поиск в локальной БД...\"}\n\n"
            rvtdocs_json = {
                "rvtdocs_count": rvtdocs_results.get("count", 0),
                "rvtdocs_results": rvtdocs_results.get("results", [])[:5],
                "source": "revit_api.db (local)",
            }
            yield f"event: rvtdocs\ndata: {json.dumps(rvtdocs_json, ensure_ascii=False)}\n\n"

            yield "event: status\ndata: {\"msg\":\"Генерация ответа...\"}\n\n"

            system = _safe_format(
                get_cfg("prompts", "web_research", default=""),
                revit_version=req.revit_version,
            )
            async for chunk in llm_chat_stream(
                [{"role": "user", "content": f"## Question\n{req.query}\n\n## Search Results\n{context}"}],
                system=system,
            ):
                yield f"event: token\ndata: {json.dumps({'token': chunk}, ensure_ascii=False)}\n\n"

            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            _logger.error("research stream failed: %s", e, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/research/with-key")
async def api_research_with_key(req: ResearchWithKeyRequest):
    """Research endpoint with per-request RouterAI API key."""
    try:
        if llm_provider() == "ollama":
            raise HTTPException(400, "This endpoint is only for RouterAI provider (not ollama)")

        qdrant_results, rvtdocs_results, context = await build_context(req, api_key=req.api_key)

        analysis = await llm_chat_full(
            [{"role": "user", "content": f"## Question\n{req.query}\n\n## Search Results\n{context}"}],
            system=_safe_format(
                get_cfg("prompts", "web_research", default=""),
                revit_version=req.revit_version,
            ),
            api_key=req.api_key,
        )
        return {
            "query": req.query, "revit_version": req.revit_version, "collections": req.collections,
            "qdrant_count": qdrant_results.get("count", 0),
            "rvtdocs_count": rvtdocs_results.get("count", 0),
            "qdrant_results": qdrant_results.get("results", [])[:8],
            "rvtdocs_results": rvtdocs_results.get("results", [])[:5],
            "analysis": analysis,
        }
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("research with key failed: %s", e, exc_info=True)
        raise HTTPException(500, str(e))


@app.post("/api/research/with-key/stream")
async def api_research_with_key_stream(req: ResearchWithKeyRequest):
    """SSE endpoint with per-request RouterAI API key."""
    if llm_provider() == "ollama":
        raise HTTPException(400, "This endpoint is only for RouterAI provider (not ollama)")

    async def _event_stream():
        try:
            yield "event: status\ndata: {\"msg\":\"Поиск в Qdrant...\"}\n\n"
            qdrant_results, rvtdocs_results, context = await build_context(req, api_key=req.api_key)
            qdrant_json = {
                "qdrant_count": qdrant_results.get("count", 0),
                "qdrant_results": qdrant_results.get("results", [])[:8],
            }
            yield f"event: qdrant\ndata: {json.dumps(qdrant_json, ensure_ascii=False)}\n\n"

            yield "event: status\ndata: {\"msg\":\"Поиск в локальной БД...\"}\n\n"
            rvtdocs_json = {
                "rvtdocs_count": rvtdocs_results.get("count", 0),
                "rvtdocs_results": rvtdocs_results.get("results", [])[:5],
                "source": "revit_api.db (local)",
            }
            yield f"event: rvtdocs\ndata: {json.dumps(rvtdocs_json, ensure_ascii=False)}\n\n"

            yield "event: status\ndata: {\"msg\":\"Генерация ответа...\"}\n\n"

            system = _safe_format(
                get_cfg("prompts", "web_research", default=""),
                revit_version=req.revit_version,
            )
            async for chunk in llm_chat_stream(
                [{"role": "user", "content": f"## Question\n{req.query}\n\n## Search Results\n{context}"}],
                system=system,
                api_key=req.api_key,
            ):
                yield f"event: token\ndata: {json.dumps({'token': chunk}, ensure_ascii=False)}\n\n"

            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            _logger.error("research with key stream failed: %s", e, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Chat endpoints ────────────────────────────────────────────────────────

def _extract_search_request(text: str) -> Optional[str]:
    """Check if AI requested a new search via [SEARCH: ...] marker."""
    import re
    m = re.search(r'\[SEARCH:\s*(.+?)\s*\]', text)
    if m:
        return m.group(1).strip()
    return None


def _strip_search_marker(text: str) -> str:
    import re
    return re.sub(r'\s*\[SEARCH:\s*.+?\]\s*', '', text).strip()


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    """Chat endpoint: conversation with search context, AI can request new searches."""
    if llm_provider() != "ollama" and not os.environ.get("ROUTERAI_API_KEY"):
        raise HTTPException(400, "ROUTERAI_API_KEY not set (or set LLM_PROVIDER=ollama)")

    try:
        messages = [{"role": m.role, "content": m.content} for m in req.trimmed_messages]

        context_parts = []
        if req.search_context:
            context_parts.append(req.search_context)

        system = _safe_format(
            get_cfg("prompts", "chat", default=""),
            revit_version=req.revit_version,
        )

        reply = await llm_chat_full(messages, system=system)

        search_query = _extract_search_request(reply)
        search_results = None

        if search_query:
            _logger.info("Chat: AI requested new search: %s", search_query)
            search_req = SearchRequest(
                query=search_query,
                collections=req.collections,
                revit_version=req.revit_version,
            )
            qdrant_results, rvtdocs_results, context = await build_context(search_req)
            search_results = {
                "query": search_query,
                "context": context,
                "qdrant_results": qdrant_results.get("results", [])[:8],
                "rvtdocs_results": rvtdocs_results.get("results", [])[:5],
            }

            system_with_context = (
                system + "\n\nYou requested a new search. Here are the results:\n" + context
            )
            reply = await llm_chat_full(messages, system=system_with_context)
            # If the new reply also has a search marker, strip it for display
            reply = _strip_search_marker(reply)

        reply = _strip_search_marker(reply)

        return {
            "reply": reply,
            "new_search": search_query,
            "search_results": search_results,
        }
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("chat failed: %s", e, exc_info=True)
        raise HTTPException(500, str(e))


@app.post("/api/chat/stream")
async def api_chat_stream(req: ChatRequest):
    """SSE chat endpoint: conversation with search context, streaming response."""
    if llm_provider() != "ollama" and not os.environ.get("ROUTERAI_API_KEY"):
        raise HTTPException(400, "ROUTERAI_API_KEY not set (or set LLM_PROVIDER=ollama)")

    async def _event_stream():
        try:
            messages = [{"role": m.role, "content": m.content} for m in req.trimmed_messages]

            system = _safe_format(
                get_cfg("prompts", "chat", default=""),
                revit_version=req.revit_version,
            )

            if req.search_context:
                system = system + "\n\nPrevious search results:\n" + req.search_context

            yield "event: status\ndata: {\"msg\":\"Думаю...\"}\n\n"

            full_text = ""
            async for chunk in llm_chat_stream(messages, system=system):
                full_text += chunk
                yield f"event: token\ndata: {json.dumps({'token': chunk}, ensure_ascii=False)}\n\n"

            search_query = _extract_search_request(full_text)

            if search_query:
                yield f"event: search_request\ndata: {json.dumps({'query': search_query}, ensure_ascii=False)}\n\n"
                yield "event: status\ndata: {\"msg\":\"Выполняю дополнительный поиск...\"}\n\n"

                search_req = SearchRequest(
                    query=search_query,
                    collections=req.collections,
                    revit_version=req.revit_version,
                )
                _, _, context = await build_context(search_req)

                system_with_context = (
                    system + "\n\nYou requested a new search. Here are the results:\n" + context
                )
                final_reply = ""
                async for chunk in llm_chat_stream(messages, system=system_with_context):
                    cleaned = _strip_search_marker(chunk)
                    if cleaned:
                        final_reply += cleaned
                        yield f"event: token\ndata: {json.dumps({'token': cleaned}, ensure_ascii=False)}\n\n"
            else:
                final_reply = full_text

            yield "event: done\ndata: {}\n\n"
        except Exception as e:
            _logger.error("chat stream failed: %s", e, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
