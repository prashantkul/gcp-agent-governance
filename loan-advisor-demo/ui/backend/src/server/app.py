"""FastAPI application factory — proxies AG-UI requests to Agent Engine."""

import os
import json
import uuid
import asyncio
import logging

import httpx
import google.auth
import google.auth.transport.requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from ag_ui.core import (
    EventType,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
)
from ag_ui.encoder import EventEncoder
from .config import ServerConfig, EndpointConfig

logger = logging.getLogger(__name__)

AGENT_ENGINE_ID = os.environ.get(
    "AGENT_ENGINE_ID",
    "projects/190206934161/locations/us-central1/reasoningEngines/7506782047977865216",
)
AGENT_ENGINE_BASE = f"https://us-central1-aiplatform.googleapis.com/v1/{AGENT_ENGINE_ID}"
GCP_PROJECT = "privacy-ml-lab1"
MODEL_ARMOR_TEMPLATE = os.environ.get(
    "MODEL_ARMOR_TEMPLATE",
    "projects/privacy-ml-lab1/locations/us-central1/templates/loan-advisor-armor",
)
MODEL_ARMOR_BASE = f"https://modelarmor.us-central1.rep.googleapis.com/v1/{MODEL_ARMOR_TEMPLATE}"

auth_consent_store: dict[str, dict] = {}
model_armor_config: dict[str, bool] = {"request": False, "response": False}
active_user: dict[str, str] = {"user_id": "prashant@pskulkarni.altostrat.com"}

DEMO_USERS = [
    {"id": "prashant@pskulkarni.altostrat.com", "name": "Prashant Kulkarni", "role": "Loan Officer"},
    {"id": "devon@pskulkarni.altostrat.com", "name": "Devon", "role": "Underwriter"},
    {"id": "vinesh@pskulkarni.altostrat.com", "name": "Vinesh", "role": "Risk Analyst"},
    {"id": "admin@pskulkarni.altostrat.com", "name": "Admin", "role": "Branch Manager"},
]


def _get_access_token() -> str:
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _auth_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-goog-user-project": GCP_PROJECT,
    }


async def _ensure_session(client: httpx.AsyncClient, headers: dict, user_id: str, session_id: str) -> str:
    """Create a new Agent Engine session. Always creates fresh to avoid corrupted state."""
    create_url = f"{AGENT_ENGINE_BASE}/sessions?sessionId={session_id}"
    try:
        resp = await client.post(create_url, headers=headers, json={"userId": user_id})
        if resp.status_code in [200, 201]:
            logger.info(f"Created session: {session_id}")
            return session_id
        elif resp.status_code == 409:
            return session_id
    except Exception as e:
        logger.error(f"Session creation failed: {e}")

    return session_id


async def _sanitize_user_prompt(text: str, token: str) -> dict | None:
    """Call Model Armor to scan user input. Returns full filter results."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{MODEL_ARMOR_BASE}:sanitizeUserPrompt",
            headers=_auth_headers(token),
            json={"userPromptData": {"text": text}},
        )
        if resp.status_code != 200:
            return None
        result = resp.json().get("sanitizationResult", {})
        if result.get("filterMatchState") == "MATCH_FOUND":
            return result.get("filterResults", {})
    return None


async def _sanitize_model_response(text: str, token: str) -> tuple[dict | None, str | None]:
    """Call Model Armor to scan agent output. Returns (filter_results, redacted_text)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{MODEL_ARMOR_BASE}:sanitizeModelResponse",
            headers=_auth_headers(token),
            json={"modelResponseData": {"text": text}},
        )
        if resp.status_code != 200:
            return None, None
        result = resp.json().get("sanitizationResult", {})
        if result.get("filterMatchState") == "MATCH_FOUND":
            filters = result.get("filterResults", {})
            redacted = filters.get("sdp", {}).get("sdpFilterResult", {}).get("deidentifyResult", {}).get("data", {}).get("text")
            return filters, redacted
    return None, None


def _classify_armor_findings(findings: dict) -> tuple[bool, str]:
    """Classify findings into block vs warn. Returns (should_block, message)."""
    block_reasons = []
    warn_reasons = []

    # Prompt injection / jailbreak → BLOCK
    pi = findings.get("pi_and_jailbreak", {}).get("piAndJailbreakFilterResult", {})
    if pi.get("matchState") == "MATCH_FOUND":
        block_reasons.append("Prompt injection / jailbreak attempt detected")

    # SDP / PII → BLOCK (check both inspectResult and deidentifyResult)
    sdp = findings.get("sdp", {}).get("sdpFilterResult", {})
    inspect = sdp.get("inspectResult", {})
    deidentify = sdp.get("deidentifyResult", {})
    sdp_match = inspect.get("matchState") == "MATCH_FOUND" or deidentify.get("matchState") == "MATCH_FOUND"
    if sdp_match:
        pii_types = deidentify.get("infoTypes", [])
        if not pii_types:
            for finding in inspect.get("findings", []):
                pii_types.append(finding.get("infoType", {}).get("name", "PII"))
        label = ", ".join(pii_types) if pii_types else "PII"
        block_reasons.append(f"Sensitive data detected ({label})")

    # RAI filters → WARN only (too many false positives at low confidence)
    rai = findings.get("rai", {}).get("raiFilterResult", {})
    if rai.get("matchState") == "MATCH_FOUND":
        for category, detail in rai.get("raiFilterTypeResults", {}).items():
            if detail.get("matchState") == "MATCH_FOUND":
                warn_reasons.append(category.replace("_", " "))

    should_block = len(block_reasons) > 0
    if should_block:
        return True, "; ".join(block_reasons)
    elif warn_reasons:
        return False, f"RAI advisory: {', '.join(warn_reasons)}"
    return False, ""


def create_app(config: ServerConfig = None) -> FastAPI:
    if config is None:
        config = ServerConfig()

    app = FastAPI(
        title="Loan Advisor AG-UI Backend",
        description="Proxies AG-UI to Agent Engine",
        version="2.0.0",
    )

    cors_origins = config.cors_origins.split(",") if config.cors_origins != "*" else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    sessions: dict[str, str] = {}

    @app.get("/model-armor/config")
    async def get_armor_config():
        return model_armor_config

    @app.post("/model-armor/config")
    async def set_armor_config(request: Request):
        body = await request.json()
        if "request" in body:
            model_armor_config["request"] = bool(body["request"])
        if "response" in body:
            model_armor_config["response"] = bool(body["response"])
        return model_armor_config

    @app.get("/users")
    async def list_users():
        return {"users": DEMO_USERS, "active": active_user["user_id"]}

    @app.post("/users/active")
    async def set_active_user(request: Request):
        body = await request.json()
        if "user_id" in body:
            active_user["user_id"] = body["user_id"]
            sessions.clear()
        return {"active": active_user["user_id"]}

    @app.post(EndpointConfig.AGENT_PATH)
    async def agent_endpoint(request: Request):
        """AG-UI endpoint — proxies to Agent Engine streamQuery."""
        body = await request.json()
        accept = request.headers.get("accept", "text/event-stream")
        encoder = EventEncoder(accept=accept)

        thread_id = body.get("threadId", str(uuid.uuid4()))
        user_id = active_user["user_id"]
        run_id = body.get("runId", str(uuid.uuid4()))

        user_message = ""
        messages = body.get("messages", [])
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    user_message = content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            user_message = part["text"]
                            break
                        elif isinstance(part, str):
                            user_message = part
                            break
                break

        resume = body.get("resume", [])
        is_auth_resume = len(resume) > 0

        if not user_message and not is_auth_resume:
            user_message = "Hello"

        logger.info(f"User [{user_id}] thread [{thread_id}]: {user_message[:80]} (resume={is_auth_resume})")

        token = _get_access_token()
        headers = _auth_headers(token)

        # Model Armor: scan user prompt if enabled
        armor_warning = ""
        if model_armor_config["request"] and user_message and not is_auth_resume:
            try:
                findings = await _sanitize_user_prompt(user_message, token)
                if findings:
                    should_block, description = _classify_armor_findings(findings)
                    if should_block:
                        async def blocked_stream():
                            yield encoder.encode(RunStartedEvent(type=EventType.RUN_STARTED, thread_id=thread_id, run_id=run_id))
                            msg_id = str(uuid.uuid4())
                            yield encoder.encode(TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=msg_id, role="assistant"))
                            yield encoder.encode(TextMessageContentEvent(
                                type=EventType.TEXT_MESSAGE_CONTENT, message_id=msg_id,
                                delta=f"🛡️ **Model Armor — Request Blocked**\n\n{description}\n\nYour message was flagged by Model Armor security policies and was not forwarded to the agent.",
                            ))
                            yield encoder.encode(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=msg_id))
                            yield encoder.encode(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id))
                        return StreamingResponse(blocked_stream(), media_type=encoder.get_content_type())
                    elif description:
                        armor_warning = description
            except Exception as e:
                logger.warning(f"Model Armor request scan failed: {e}")

        async def stream_events():
            yield encoder.encode(RunStartedEvent(type=EventType.RUN_STARTED, thread_id=thread_id, run_id=run_id))

            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    session_id = sessions.get(thread_id)
                    if not session_id:
                        session_id = await _ensure_session(client, headers, user_id, thread_id)
                        sessions[thread_id] = session_id

                    if is_auth_resume:
                        stored = auth_consent_store.get("latest", {})
                        fc_id = stored.get("function_call_id", "")
                        auth_config = stored.get("auth_config", {})
                        message_content = {
                            "role": "user",
                            "parts": [{
                                "functionResponse": {
                                    "id": fc_id,
                                    "name": "adk_request_credential",
                                    "response": auth_config,
                                }
                            }],
                        }
                    else:
                        message_content = {
                            "role": "user",
                            "parts": [{"text": user_message}],
                        }

                    payload = {
                        "input": {
                            "session_id": session_id,
                            "user_id": user_id,
                            "message": message_content,
                        }
                    }

                    full_text = ""
                    msg_id = str(uuid.uuid4())

                    async with client.stream(
                        "POST",
                        f"{AGENT_ENGINE_BASE}:streamQuery",
                        headers=headers,
                        json=payload,
                    ) as resp:
                        if resp.status_code != 200:
                            err = await resp.aread()
                            yield encoder.encode(RunErrorEvent(
                                type=EventType.RUN_ERROR,
                                message=f"Agent Engine error {resp.status_code}: {err.decode()[:200]}",
                            ))
                        else:
                            async for line in resp.aiter_lines():
                                if not line or not line.strip():
                                    continue

                                try:
                                    event = json.loads(line)
                                except json.JSONDecodeError:
                                    logger.debug(f"Non-JSON line: {line[:100]}")
                                    continue

                                if not isinstance(event, dict):
                                    continue

                                logger.info(f"Event from AE: author={event.get('author')}, keys={list(event.get('content',{}).get('parts',[{}])[0].keys()) if event.get('content',{}).get('parts') else 'no-parts'}")

                                author = event.get("author", "")
                                if author == "user":
                                    continue

                                content = event.get("content", {})
                                parts = content.get("parts", [])
                                actions = event.get("actions", {})

                                for part in parts:
                                    fc = part.get("functionCall") or part.get("function_call")
                                    if fc:
                                        fc_id_val = fc.get("id", str(uuid.uuid4()))
                                        fc_name = fc.get("name", "")

                                        if fc_name == "adk_request_credential":
                                            # Capture the function call ID for resume, but don't show to user
                                            auth_consent_store["_adk_fc_id"] = fc_id_val
                                            auth_consent_store["_adk_fc_args"] = fc.get("args", {})
                                            continue

                                        yield encoder.encode(ToolCallStartEvent(type=EventType.TOOL_CALL_START, tool_call_id=fc_id_val, tool_call_name=fc_name, parent_message_id=None))
                                        if fc.get("args"):
                                            yield encoder.encode(ToolCallArgsEvent(type=EventType.TOOL_CALL_ARGS, tool_call_id=fc_id_val, delta=json.dumps(fc["args"])))
                                        yield encoder.encode(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=fc_id_val))
                                        continue

                                    fr = part.get("functionResponse") or part.get("function_response")
                                    if fr:
                                        continue

                                    text = part.get("text")
                                    if text:
                                        full_text += text

                                # Check actions.requested_auth_configs (ADK 1.x pattern)
                                requested_auth = actions.get("requested_auth_configs", {})
                                if requested_auth:
                                    for tool_id, auth_cfg in requested_auth.items():
                                        exchanged = auth_cfg.get("exchanged_auth_credential", {})
                                        oauth2 = exchanged.get("oauth2", {})
                                        auth_uri = oauth2.get("auth_uri") or oauth2.get("auth_response_uri")
                                        nonce = oauth2.get("nonce")
                                        logger.info(f"Auth via requested_auth_configs: tool={tool_id}, nonce={nonce}")

                                        if nonce:
                                            auth_consent_store["latest"] = {
                                                "consent_nonce": nonce,
                                                "user_id": user_id,
                                                "function_call_id": tool_id,
                                                "auth_config": auth_cfg,
                                                "thread_id": thread_id,
                                                "session_id": session_id,
                                            }

                                        if auth_uri:
                                            auth_msg_id = str(uuid.uuid4())
                                            yield encoder.encode(TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=auth_msg_id, role="assistant"))
                                            yield encoder.encode(TextMessageContentEvent(
                                                type=EventType.TEXT_MESSAGE_CONTENT,
                                                message_id=auth_msg_id,
                                                delta=f"🔐 **Authentication required** to access your data.\n\n[Click here to authorize access]({auth_uri})\n\nA new window will open for Google sign-in. The conversation will resume automatically after you authorize.",
                                            ))
                                            yield encoder.encode(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=auth_msg_id))

                                error_msg = event.get("error_message")
                                if error_msg:
                                    err_msg_id = str(uuid.uuid4())
                                    yield encoder.encode(TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=err_msg_id, role="assistant"))
                                    yield encoder.encode(TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=err_msg_id, delta=f"⚠️ {error_msg}"))
                                    yield encoder.encode(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=err_msg_id))

                    if full_text:
                        resp_armor_note = ""
                        if model_armor_config["response"]:
                            try:
                                resp_findings, redacted_text = await _sanitize_model_response(full_text, token)
                                if resp_findings:
                                    should_block, description = _classify_armor_findings(resp_findings)
                                    if should_block and redacted_text:
                                        full_text = f"🛡️ **Model Armor — PII Redacted**\n\n{description}\n\n---\n\n{redacted_text}"
                                    elif should_block:
                                        yield encoder.encode(TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=msg_id, role="assistant"))
                                        yield encoder.encode(TextMessageContentEvent(
                                            type=EventType.TEXT_MESSAGE_CONTENT, message_id=msg_id,
                                            delta=f"🛡️ **Model Armor — Response Blocked**\n\n{description}\n\nThe agent's response was flagged and redacted.",
                                        ))
                                        yield encoder.encode(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=msg_id))
                                        full_text = ""
                                    elif description:
                                        resp_armor_note = description
                            except Exception as e:
                                logger.warning(f"Model Armor response scan failed: {e}")

                        if full_text:
                            display_text = full_text
                            if armor_warning:
                                display_text += f"\n\n---\n⚠️ *Model Armor advisory (request): {armor_warning}*"
                            if resp_armor_note:
                                display_text += f"\n\n---\n⚠️ *Model Armor advisory (response): {resp_armor_note}*"
                            yield encoder.encode(TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=msg_id, role="assistant"))
                            yield encoder.encode(TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=msg_id, delta=display_text))
                            yield encoder.encode(TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=msg_id))

            except httpx.HTTPStatusError as e:
                logger.error(f"Agent Engine error: {e.response.text[:300]}")
                yield encoder.encode(RunErrorEvent(type=EventType.RUN_ERROR, message=f"Agent Engine error: {e.response.status_code}"))
            except Exception as e:
                logger.error(f"Error: {e}", exc_info=True)
                yield encoder.encode(RunErrorEvent(type=EventType.RUN_ERROR, message=str(e)))

            yield encoder.encode(RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=run_id))

        return StreamingResponse(stream_events(), media_type=encoder.get_content_type())

    @app.get("/auth-nonce")
    async def auth_nonce_endpoint():
        """Returns auth nonce and user_id for the frontend to set as cookies."""
        stored = auth_consent_store.get("latest", {})
        from fastapi.responses import JSONResponse
        resp = JSONResponse({
            "consent_nonce": stored.get("consent_nonce", ""),
            "user_id": stored.get("user_id", config.user_id),
        })
        resp.set_cookie("consent_nonce", stored.get("consent_nonce", ""), path="/")
        resp.set_cookie("user_id", stored.get("user_id", config.user_id), path="/")
        return resp

    @app.get("/commit")
    async def commit(request: Request):
        logger.info(f"Commit params: {dict(request.query_params)}")

        connector = request.query_params.get("auth_provider_name") or request.query_params.get("connector_name")
        user_id_validation_state = request.query_params.get("user_id_validation_state")

        # Read from cookies first (set by frontend), fall back to in-memory store
        cookie_nonce = request.cookies.get("consent_nonce")
        cookie_user_id = request.cookies.get("user_id")
        stored = auth_consent_store.get("latest", {})

        payload = {
            "userId": cookie_user_id or stored.get("user_id", config.user_id),
            "userIdValidationState": user_id_validation_state,
            "consentNonce": cookie_nonce or stored.get("consent_nonce"),
        }

        if not connector:
            return HTMLResponse("<p>Error: Missing connector name</p>", status_code=400)

        finalize_url = f"https://iamconnectorcredentials.googleapis.com/v1alpha/{connector}/credentials:finalize"
        print(f"[COMMIT] nonce source: {'COOKIE' if cookie_nonce else 'MEMORY'}")
        print(f"[COMMIT] userId source: {'COOKIE' if cookie_user_id else 'MEMORY'}")
        print(f"[COMMIT] Payload: userId={payload['userId']}, nonce={payload.get('consentNonce','NONE')[:30] if payload.get('consentNonce') else 'NONE'}...")
        print(f"[COMMIT] userIdValidationState present: {bool(user_id_validation_state)}")
        try:
            finalize_token = _get_access_token()
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    finalize_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {finalize_token}"},
                )
                print(f"[COMMIT] Finalize status: {resp.status_code}")
                print(f"[COMMIT] Finalize body: {resp.text[:500]}")
                resp.raise_for_status()
                resp_data = resp.json()
                logger.info(f"Finalize response: {resp_data}")

                operation_name = resp_data.get("name")
                done = resp_data.get("done", False)

                if operation_name and not done:
                    logger.info(f"Polling LRO: {operation_name}")
                    poll_url = f"https://iamconnectorcredentials.googleapis.com/v1alpha/{operation_name}"
                    for attempt in range(30):
                        await asyncio.sleep(1.0)
                        poll_resp = await client.get(poll_url)
                        poll_resp.raise_for_status()
                        poll_data = poll_resp.json()
                        logger.info(f"Poll attempt {attempt + 1}: done={poll_data.get('done')}")
                        if poll_data.get("done", False):
                            if "error" in poll_data:
                                raise RuntimeError(f"LRO failed: {poll_data['error'].get('message', 'Unknown')}")
                            logger.info("LRO completed successfully")
                            break
                    else:
                        raise TimeoutError("LRO timed out")

                logger.info("Credential finalized successfully")
        except Exception as e:
            err_text = e.response.text if hasattr(e, "response") and e.response else str(e)
            logger.error(f"Finalize failed: {err_text}")
            return HTMLResponse(f"<p>Error: {err_text}</p>", status_code=500)

        # Store auth details for client-side resume
        auth_consent_store["resume_result"] = {
            "status": "complete",
            "auth_complete": True,
            "function_call_id": auth_consent_store.get("_adk_fc_id", ""),
            "auth_config": stored.get("auth_config", {}),
            "session_id": stored.get("session_id", ""),
        }

        return HTMLResponse("""
            <html><body>
            <p>Authentication successful! Returning to chat...</p>
            <script>
                if (window.opener) {
                    window.opener.postMessage({type: 'AUTH_COMPLETE'}, '*');
                }
                setTimeout(() => window.close(), 1500);
            </script>
            </body></html>
        """)

    @app.get("/resume-result")
    async def resume_result():
        result = auth_consent_store.get("resume_result", {"status": "pending"})
        return result

    @app.get(EndpointConfig.ROOT_PATH)
    async def root():
        return {"message": "Loan Advisor AG-UI Backend (Agent Engine proxy)", "agent_engine": AGENT_ENGINE_ID}

    @app.get(EndpointConfig.HEALTH_PATH)
    async def health_check():
        return {"status": "healthy", "agent_engine": AGENT_ENGINE_ID}

    logger.info(f"AG-UI Backend proxying to Agent Engine: {AGENT_ENGINE_ID}")

    return app
