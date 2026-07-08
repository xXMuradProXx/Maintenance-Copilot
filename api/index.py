"""Maintenance Copilot — FastAPI entrypoint.

Runs both locally (uvicorn api.index:app) and as a Vercel serverless function
(vercel.json rewrites /api/* to this file; Vercel auto-detects the ASGI `app`).
"""

import os
import sys

# Make `api/_lib` importable both locally and inside Vercel's function bundle.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()  # local dev convenience; on Vercel, env vars come from the dashboard

from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError

from _lib.agent import run_case
from _lib.state import CaseState

app = FastAPI(
	title="Maintenance Copilot API",
	description="Supervisor agent that triages tenant maintenance messages into "
	            "work orders: classify, prioritize, retrieve guidance (RAG), "
	            "schedule or escalate.",
	version="1.0.0",
)

app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],  # demo-friendly; restrict to your domain in production
	allow_methods=["*"],
	allow_headers=["*"],
)

_ALLOWED_CHANNELS = {"whatsapp", "sms", "email", "portal"}


class ChatRequest(BaseModel):
	message: str = Field(..., min_length=1, max_length=4000)
	channel: str = "portal"
	history: List[Dict[str, Any]] = Field(default_factory=list)
	case_state: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
	reply: str
	case_state: Dict[str, Any]


def _handle_chat(req: ChatRequest) -> ChatResponse:
	if not os.getenv("OPENAI_API_KEY"):
		raise HTTPException(
			status_code=500,
			detail="OPENAI_API_KEY is not set. Add it to .env (local) or to the "
			       "Vercel project's Environment Variables.",
		)

	# Rebuild the shared case state from the client; start fresh if it's malformed.
	try:
		case = CaseState(**req.case_state) if req.case_state else CaseState()
	except (ValidationError, TypeError):
		case = CaseState()

	channel = (req.channel or "portal").lower()
	case.channel = channel if channel in _ALLOWED_CHANNELS else "portal"

	try:
		reply, case = run_case(req.message.strip(), req.history, case)
	except HTTPException:
		raise
	except Exception as exc:  # noqa: BLE001 — surface a clean error to the UI
		raise HTTPException(status_code=502, detail=f"Agent error: {exc}") from exc

	return ChatResponse(reply=reply, case_state=case.model_dump())


# Both paths are registered so the app works behind the Vercel rewrite
# (/api/chat) and when routes are invoked without the prefix.
@app.post("/api/chat", response_model=ChatResponse)
@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
	return _handle_chat(req)


@app.get("/api/health")
@app.get("/health")
def health() -> Dict[str, Any]:
	return {
		"status": "ok",
		"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
		"openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
		"pinecone_key_present": bool(os.getenv("PINECONE_API_KEY")),
		"pinecone_index": os.getenv("PINECONE_INDEX", "maintenance-copilot"),
	}


# Local-dev convenience: serve the frontend from the same server.
# On Vercel, /public/index.html is served by the static layer before any rewrite.
_INDEX_HTML = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "index.html"
)


@app.get("/")
def root():
	if os.path.exists(_INDEX_HTML):
		return FileResponse(_INDEX_HTML)
	return JSONResponse({"service": "Maintenance Copilot API", "docs": "/docs"})
