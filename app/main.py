"""Doc2Agent — turn any API's documentation into a working AI agent."""
import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import demo_data, store  # noqa: E402
from .agent import AgentSession, run_agent, run_agent_events  # noqa: E402
from .demo_api import demo_app  # noqa: E402
from .guardrails import APPROVALS  # noqa: E402
from .ingest import ingest  # noqa: E402
from .mcp_export import generate_mcp_server  # noqa: E402
from .models import (  # noqa: E402
    ApprovalDecision, ChatRequest, ChatResponse, IngestRequest, IngestResponse,
)
from .safety import UnsafeURLError, trust_own_netloc  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    demo_data.seed()
    task = asyncio.create_task(demo_data.simulator_loop())
    yield
    task.cancel()


app = FastAPI(title="Doc2Agent", version="2.0.0", lifespan=lifespan)

SESSIONS: dict[str, AgentSession] = {}  # warm cache over SQLite
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _get_session(session_id: str) -> AgentSession:
    session = SESSIONS.get(session_id)
    if session is None:
        payload = store.load_session(session_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Session not found — ingest docs first.")
        session = AgentSession.from_dict(payload)
        SESSIONS[session_id] = session
    return session


def _save_session(session_id: str, session: AgentSession) -> None:
    SESSIONS[session_id] = session
    store.save_session(session_id, session.to_dict())


def _agent_error_detail(exc: Exception) -> str:
    if "rate_limit_exceeded" in str(exc):
        return (
            "The demo's free daily LLM quota is exhausted (Groq free tier). "
            "It resets within a few hours — please come back and try again."
        )
    return f"Agent error: {exc}"


@app.post("/api/ingest", response_model=IngestResponse)
def api_ingest(req: IngestRequest, request: Request) -> IngestResponse:
    # Self-referential demo: if the user points Doc2Agent at this very app's
    # bundled /demo API, exempt our own host from the SSRF guard.
    parsed = urlparse(req.url)
    if parsed.netloc == request.headers.get("host", "") and parsed.path.startswith("/demo"):
        trust_own_netloc(parsed.netloc)

    try:
        source, base_url, endpoints = ingest(req.url)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not ingest docs: {exc}")

    session_id = uuid.uuid4().hex
    session = AgentSession(
        base_url=base_url,
        endpoints=endpoints,
        api_key=req.api_key,
        auth_header=req.auth_header,
        auth_scheme=req.auth_scheme,
    )
    _save_session(session_id, session)
    return IngestResponse(
        session_id=session_id, base_url=base_url, source=source, endpoints=endpoints
    )


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(req: ChatRequest) -> ChatResponse:
    session = _get_session(req.session_id)
    session.auto_approve = req.auto_approve
    try:
        reply, traces = run_agent(session, req.message)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_agent_error_detail(exc))
    _save_session(req.session_id, session)
    return ChatResponse(reply=reply, trace=traces)


@app.post("/api/chat/stream")
def api_chat_stream(req: ChatRequest) -> StreamingResponse:
    session = _get_session(req.session_id)
    session.auto_approve = req.auto_approve

    def event_stream():
        try:
            for event in run_agent_events(session, req.message, interactive=True):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': _agent_error_detail(exc)})}\n\n"
        finally:
            _save_session(req.session_id, session)
            yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/approvals/{approval_id}")
def api_resolve_approval(approval_id: str, decision: ApprovalDecision) -> dict:
    if not APPROVALS.resolve(approval_id, decision.approve):
        raise HTTPException(status_code=404, detail="Approval not found or already resolved.")
    return {"ok": True, "approved": decision.approve}


@app.get("/api/sessions/{session_id}/mcp")
def api_export_mcp(session_id: str) -> PlainTextResponse:
    session = _get_session(session_id)
    host = urlparse(session.base_url).hostname or "api"
    code = generate_mcp_server(session.base_url, session.endpoints, title=host)
    filename = f"{host.replace('.', '_')}_mcp.py"
    return PlainTextResponse(
        code,
        media_type="text/x-python",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/monitor/feed")
def monitor_feed() -> dict:
    by_status: dict[str, int] = {}
    for s in demo_data.shipments.values():
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
    recent = sorted(
        demo_data.shipments.values(), key=lambda s: s["updated_at"], reverse=True
    )[:14]
    return {
        "stats": {
            "total": len(demo_data.shipments),
            "in_transit": by_status.get("in_transit", 0) + by_status.get("out_for_delivery", 0),
            "delivered": by_status.get("delivered", 0),
            "delayed": by_status.get("delayed", 0),
            "idle_couriers": sum(1 for c in demo_data.couriers.values() if c["status"] == "idle"),
            "agent_calls": sum(1 for r in demo_data.request_log if r["caller"] == "agent"),
        },
        "requests": list(demo_data.request_log)[:40],
        "events": list(demo_data.events)[:30],
        "shipments": [{k: v for k, v in s.items() if k != "events"} for s in recent],
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/monitor")
def monitor() -> FileResponse:
    return FileResponse(STATIC_DIR / "monitor.html")


app.mount("/demo", demo_app)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
