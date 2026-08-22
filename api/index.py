"""Maintenance Copilot — FastAPI entrypoint.

Runs both locally (uvicorn api.index:app) and as a Vercel serverless function
(vercel.json rewrites /api/* to this file; Vercel auto-detects the ASGI `app`).
"""

import json
import os
import sys

# Make `api/lib` importable both locally and inside Vercel's function bundle.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()  # local dev convenience; on Vercel, env vars come from the dashboard

from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from lib.agent import (
	EMERGENCY_PROMPT,
	LLM_MODULES,
	MODEL,
	PUBLIC_MODULES,
	SYSTEM_PROMPT,
	run_case,
)
from lib.llm_client import is_llmod_configured, llmod_public_status
from lib.repositories import CaseRepository
from lib.state import CaseState
from lib.supabase_client import check_supabase_connection

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


class ExecuteRequest(BaseModel):
	prompt: str = Field(..., min_length=1, max_length=4000)

	@field_validator("prompt")
	@classmethod
	def prompt_must_not_be_blank(cls, value: str) -> str:
		value = value.strip()
		if not value:
			raise ValueError("Prompt must contain non-whitespace text.")
		return value


class ExecutionPrompt(BaseModel):
	model_config = ConfigDict(extra="forbid")

	system_prompt: str
	user_prompt: str


class ExecutionStep(BaseModel):
	model_config = ConfigDict(extra="forbid")

	module: str
	prompt: ExecutionPrompt
	response: Dict[str, Any]

	@field_validator("module")
	@classmethod
	def module_matches_architecture(cls, value: str) -> str:
		if value not in LLM_MODULES:
			raise ValueError(
				"LLM step module must match the architecture: "
				+ ", ".join(LLM_MODULES)
			)
		return value


class ExecuteResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	status: Literal["ok", "error"]
	error: Optional[str]
	response: Optional[str]
	steps: List[ExecutionStep]


class StudentInfo(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str
	email: str


class TeamInfoResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	group_batch_order_number: str
	team_name: str
	students: List[StudentInfo]


class PromptTemplateInfo(BaseModel):
	model_config = ConfigDict(extra="forbid")

	template: str
	example: Optional[str] = None


class PromptExample(BaseModel):
	model_config = ConfigDict(extra="forbid")

	prompt: str
	full_response: str
	steps: List[ExecutionStep]


class AgentInfoResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	description: str
	purpose: str
	prompt_template: PromptTemplateInfo
	prompt_examples: List[PromptExample]
	model: str
	modules: List[str]


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
	if request.url.path.rstrip("/").endswith("/execute"):
		message = "; ".join(
			str(item.get("msg", "Invalid request")) for item in exc.errors()
		)
		return JSONResponse(
			status_code=422,
			content={
				"status": "error", "error": message,
				"response": None, "steps": [],
			},
		)
	return JSONResponse(status_code=422, content={"detail": exc.errors()})


def _handle_chat(req: ChatRequest) -> ChatResponse:
	if not is_llmod_configured():
		raise HTTPException(
			status_code=500,
			detail="LLMod is not configured. Set LLMOD_BASE_URL and LLMOD_API_KEY.",
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


def _persist_completed_execution(
	repository: CaseRepository,
	database_case_id: str,
	case: CaseState,
	reply: str,
) -> None:
	"""Write the final case, response, and ordered LLM calls to Supabase."""
	repository.update_case(
		database_case_id,
		{
			**case.snapshot(),
			"citations": case.citations,
			"current_response": reply,
			"metadata": {
				"source_endpoint": "/api/execute",
				"decision_trace": case.trace,
				"llm_step_count": len(case.llm_steps),
				"taxonomy_urgency": case.taxonomy_urgency,
				"policy_flags": case.policy_flags,
			},
		},
	)
	repository.append_message(database_case_id, "assistant", reply)
	for step in case.llm_steps:
		model_response = step.get("response") or {}
		repository.append_event(
			database_case_id,
			step["module"],
			"llm_call",
			prompt=step.get("prompt"),
			response=model_response,
			model=model_response.get("model"),
			token_usage=model_response.get("token_usage"),
		)


def _execute_agent(req: ExecuteRequest) -> ExecuteResponse:
	case = CaseState(channel="portal")
	if not is_llmod_configured():
		return ExecuteResponse(
			status="error",
			error="LLMod is not configured. Set LLMOD_BASE_URL and LLMOD_API_KEY.",
			response=None,
			steps=[],
		)

	try:
		repository = CaseRepository()
		database_case = repository.create_case(
			{"channel": "portal", "metadata": {"source_endpoint": "/api/execute"}}
		)
		case.case_id = database_case["public_id"]
		repository.append_message(database_case["id"], "user", req.prompt.strip())
		reply, case = run_case(req.prompt.strip(), [], case)
		_persist_completed_execution(repository, database_case["id"], case, reply)
		return ExecuteResponse(
			status="ok", error=None, response=reply, steps=case.llm_steps
		)
	except Exception as exc:  # noqa: BLE001 - contract requires a structured error
		return ExecuteResponse(
			status="error",
			error=f"Execution failed: {type(exc).__name__}: {exc}",
			response=None,
			steps=case.llm_steps,
		)


@app.post("/api/execute", response_model=ExecuteResponse)
@app.post("/execute", response_model=ExecuteResponse)
def execute(req: ExecuteRequest) -> ExecuteResponse:
	"""Assignment entrypoint: one prompt in, final response plus all LLM calls out."""
	return _execute_agent(req)


@app.get("/api/team_info", response_model=TeamInfoResponse)
@app.get("/team_info", response_model=TeamInfoResponse)
def team_info() -> TeamInfoResponse:
	return TeamInfoResponse.model_validate({
		"group_batch_order_number": "1_4",
		"team_name": "Murad Aviv",
		"students": [
			{"name": "Aviv Fedida", "email": "aviv.fedida@campus.technion.ac.il"},
			{"name": "Murad Rahimli", "email": "muradrahimli@campus.technion.ac.il"},
		],
	})


@app.get("/api/agent_info", response_model=AgentInfoResponse)
@app.get("/agent_info", response_model=AgentInfoResponse)
def agent_info() -> AgentInfoResponse:
	emergency_message = "I smell gas in my kitchen in apartment 4B."
	example_citations = (
		"- [ABCs of Housing, page 10] I. Gas Leaks\n\n"
		"as leak s can create fires Proper t y owners are required 2. Af ter leaving "
		"the building, Gand explosions. It\u2019s to post signage and provide from a safe "
		"distance away impor tant that you and your information to tenants from the "
		"building, call 9 11 family know how to recognize regarding \n"
		"- [NYC Housing Maintenance Code (Title 27, Chapter 2), page 6] the expected "
		"start and end dates of the service interruption. The notice shall be updated "
		"as needed. Such notice shall be posted in English, Spanish and such other "
		"languages as the department may provide by rule.\n\n"
		"2. Repairs made pursuant to section 27-2125 of this code shall be exempt from the prov\n"
	)
	emergency_system = EMERGENCY_PROMPT.format(
		reason="Possible gas leak reported",
		guidance=(
			"Please leave the apartment now. Do not touch light switches, appliances, "
			"or anything that can spark, and do not light flames. Once outside, call "
			"911 and your gas utility's 24-hour emergency line."
		),
		unit="4B",
		citations=example_citations,
	)
	example_context = (
		"Today is an example date. Message channel: portal.\n"
		"SAFETY PRE-FILTER: none\n"
		"DETERMINISTIC TENANT GUIDANCE (JSON; use these steps/questions and do not "
		"invent additional DIY work): {\"key\": \"generic\", \"summary\": \"maintenance "
		"issue\", \"trade\": null, \"safe_steps\": [], \"questions\": [{\"field\": "
		"\"problem details\", \"question\": \"What exactly is happening, and where in "
		"the apartment is it happening?\"}]}\n"
		"CURRENT SHARED CASE STATE (JSON): {\"status\":\"new\",\"channel\":\"portal\"}"
	)
	example_system = SYSTEM_PROMPT + "\n\n" + example_context
	vague_message = "Something is wrong in my bathroom."
	vague_first_prompt = json.dumps(
		[{"role": "user", "content": vague_message}], ensure_ascii=False
	)
	vague_second_prompt = json.dumps(
		[
			{"role": "user", "content": vague_message},
			{
				"role": "assistant", "content": "",
				"tool_calls": [{
					"id": "example_call_1", "type": "function",
					"function": {
						"name": "ask_tenant",
						"arguments": "{\"missing_fields\":[\"problem details\",\"unit\"]}",
					},
				}],
			},
			{
				"role": "tool", "tool_call_id": "example_call_1",
				"content": "{\"ok\":true,\"status\":\"needs_info\"}",
			},
		],
		ensure_ascii=False,
	)

	mold_message = "There is black mold spreading across the bathroom ceiling in apartment 5C."
	mold_reply = (
		"Thanks \u2014 I understand there\u2019s black mold spreading across the bathroom "
		"ceiling in apartment 5C. That can be a serious moisture issue, and the building "
		"is responsible for addressing it. For mold work, the city guidance I found points "
		"to \u201cNYC Housing Maintenance Code (Title 27, Chapter 2), \u00a7 27-2017.1 "
		"Owners\u2019 responsibility to remediate\u201d and \u201c\u00a7 27-2153 Alternative "
		"enforcement program.\u201d\n\nWhat I still need is: is there any active leak, water "
		"staining, or other moisture source causing it? Once you tell me that, I can route "
		"this correctly for next steps."
	)
	mold_first_prompt = json.dumps(
		[{"role": "user", "content": mold_message}], ensure_ascii=False
	)

	return AgentInfoResponse.model_validate({
		"description": (
			"Maintenance Copilot is a supervisor-style AI agent for tenant "
			"maintenance requests. It uses a safety pre-filter, an HPD complaint "
			"taxonomy, official-source retrieval, simulated scheduling tools, shared case "
			"state, and a guarded multi-step tool loop. It does not replace "
			"emergency services or make unsupported legal claims."
		),
		"purpose": (
			"Turn an unstructured tenant report into a grounded work order and "
			"one safe next state: ask for information, offer a simulated vendor "
			"window, record an explicitly selected demo window, mark for review, or resolve."
		),
		"prompt_template": {
			"template": (
				"Apartment/unit: <unit number>\n"
				"Location: <room or building area>\n"
				"Problem: <what is happening>\n"
				"Started: <when it began>\n"
				"Immediate danger: <gas, smoke, sparks, flooding, injury risk, or none>"
			),
			"example": (
				"Apartment/unit: 4B\n"
				"Location: kitchen sink\n"
				"Problem: clogged and draining very slowly\n"
				"Started: yesterday evening\n"
				"Immediate danger: none"
			),
		},
		"prompt_examples": [
			{
				"prompt": emergency_message,
				"full_response": (
					"Please leave the apartment now without touching light switches, "
					"appliances, or anything that could spark, and do not light a flame. "
					"Once you are outside, call 911 and your gas utility's 24-hour "
					"emergency line. This case is marked for urgent manager review, but "
					"this demo does not send notifications, so contact building management directly."
				),
				"steps": [{
					"module": "EmergencyResponseAgent",
					"prompt": {
						"system_prompt": emergency_system,
						"user_prompt": json.dumps(
							[{"role": "user", "content": emergency_message}],
							ensure_ascii=False,
						),
					},
					"response": {
						"model": MODEL,
						"content": "Please leave the apartment now without touching light switches, appliances, or anything that could spark, and do not light a flame. Once you are outside, call 911 and your gas utility's 24-hour emergency line. This case is marked for urgent manager review, but this demo does not send notifications, so contact building management directly.",
						"tool_calls": [],
					},
				}],
			},
			{
				"prompt": "Something is wrong in my bathroom.",
				"full_response": (
					"I can help open the right work order. What exactly is happening in "
					"the bathroom, and what is your apartment number?"
				),
				"steps": [
					{
						"module": "SupervisorAgent",
						"prompt": {
							"system_prompt": example_system,
							"user_prompt": vague_first_prompt,
						},
						"response": {"model": MODEL, "content": "", "tool_calls": [{"name": "ask_tenant", "arguments": "{\"missing_fields\":[\"problem details\",\"unit\"]}"}]},
					},
					{
						"module": "SupervisorAgent",
						"prompt": {
							"system_prompt": example_system,
							"user_prompt": vague_second_prompt,
						},
						"response": {"model": MODEL, "content": "I can help open the right work order. What exactly is happening in the bathroom, and what is your apartment number?", "tool_calls": []},
					},
				],
			},
			{
				"prompt": mold_message,
				"full_response": mold_reply,
				"steps": [
					{
						"module": "SupervisorAgent",
						"prompt": {
							"system_prompt": example_system,
							"user_prompt": mold_first_prompt,
						},
						"response": {
							"model": MODEL,
							"content": "",
							"tool_calls": [
								{
									"id": "example_mold_call_1",
									"name": "classify_issue",
									"arguments": "{\"query\": \"black mold spreading across the bathroom ceiling in apartment 5C\"}",
								},
								{
									"id": "example_mold_call_2",
									"name": "retrieve_guidance",
									"arguments": "{\"query\": \"mold bathroom ceiling housing code source guidance remediation obligation\"}",
								},
								{
									"id": "example_mold_call_3",
									"name": "get_tenant_guidance",
									"arguments": "{}",
								},
							],
						},
					},
					{
						"module": "SupervisorAgent",
						"prompt": {
							"system_prompt": example_system,
							"user_prompt": mold_first_prompt,
						},
						"response": {
							"model": MODEL,
							"content": "",
							"tool_calls": [{
								"id": "example_mold_call_4",
								"name": "record_work_order",
								"arguments": "{\"summary\":\"Black mold is spreading across the bathroom ceiling in apartment 5C.\",\"issue_category\":\"GENERAL\",\"problem_code\":\"MOLD & MILDEW\",\"urgency\":\"URGENT\",\"taxonomy_urgency\":\"EMERGENCY\",\"vendor_trade\":\"remediation\",\"unit\":\"5C\",\"missing_info\":[\"Whether the mold is associated with an active leak, water staining, or other moisture source.\"]}",
							}],
						},
					},
					{
						"module": "SupervisorAgent",
						"prompt": {
							"system_prompt": example_system,
							"user_prompt": mold_first_prompt,
						},
						"response": {
							"model": MODEL,
							"content": "",
							"tool_calls": [{
								"id": "example_mold_call_5",
								"name": "ask_tenant",
								"arguments": "{\"missing_fields\":[\"Whether the mold is associated with an active leak, water staining, or other moisture source.\"]}",
							}],
						},
					},
					{
						"module": "SupervisorAgent",
						"prompt": {
							"system_prompt": example_system,
							"user_prompt": mold_first_prompt,
						},
						"response": {
							"model": MODEL,
							"content": mold_reply,
							"tool_calls": [],
						},
					},
				],
			},
		],
		"model": MODEL,
		"modules": list(PUBLIC_MODULES),
	})


@app.get("/api/health")
@app.get("/health")
def health(probe: bool = False) -> Dict[str, Any]:
	database_status = check_supabase_connection()
	payload = {
		"status": "ok",
		"model": os.getenv("LLMOD_MODEL", "MB5R2CF-azure/gpt-5.4-mini"),
		"llmod": llmod_public_status(),
		"pinecone_key_present": bool(os.getenv("PINECONE_API_KEY")),
		"pinecone_index": os.getenv("PINECONE_INDEX", "maintenance-copilot"),
		"pinecone_namespace": os.getenv("PINECONE_NAMESPACE", "official-housing-v1"),
		"embed_model": os.getenv("EMBED_MODEL", "MB5R2CF-azure/text-embedding-3-small"),
		"supabase": database_status,
	}
	if probe:
		from lib import rag
		result = rag.retrieve("heat season temperature requirements", top_k=1)
		payload["rag_probe"] = {
			"ok": result.get("ok"),
			"error": result.get("error"),
			"top_title": (result.get("results") or [{}])[0].get("title"),
		}
	return payload


# Local-dev convenience: serve the frontend from the same server.
# On Vercel, /public/index.html is served by the static layer before any rewrite.
_INDEX_HTML = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public", "index.html"
)
_ARCHITECTURE_PNG = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
	"public", "model-architecture.png",
)


@app.get("/api/model_architecture")
@app.get("/model_architecture")
def model_architecture():
	if not os.path.exists(_ARCHITECTURE_PNG):
		return JSONResponse(
			status_code=500,
			content={"error": "Model architecture image is unavailable."},
		)
	return FileResponse(_ARCHITECTURE_PNG, media_type="image/png")


@app.get("/")
def root():
	if os.path.exists(_INDEX_HTML):
		return FileResponse(_INDEX_HTML)
	return JSONResponse({"service": "Maintenance Copilot API", "docs": "/docs"})
