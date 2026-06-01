"""Causal Armor integration — LOO causal attribution via Gemma 2 proxy on Cloud Run.

Uses the causal-armor library with VLLMProxyProvider pointing at a
Gemma 2 2B model served by vLLM on Cloud Run (L4 GPU).

Based on: "CausalArmor: Efficient IPI Guardrails via Causal Attribution"
(arXiv:2602.07918)
"""

import logging
import os

from causal_armor import (
    Message,
    MessageRole,
    ToolCall,
    build_structured_context,
    compute_attribution,
    detect_dominant_spans,
)
from causal_armor.providers.vllm import VLLMProxyProvider

logger = logging.getLogger(__name__)

VLLM_BASE_URL = os.environ.get(
    "CAUSAL_ARMOR_VLLM_URL",
    "http://35.253.140.196:8000",
)
VLLM_MODEL = os.environ.get("CAUSAL_ARMOR_MODEL", "google/gemma-2-2b-it")

_provider = None


def _get_provider() -> VLLMProxyProvider:
    global _provider
    if _provider is None:
        _provider = VLLMProxyProvider(
            base_url=VLLM_BASE_URL,
            model=VLLM_MODEL,
            timeout=30.0,
        )
    return _provider


async def analyze(
    user_message: str,
    agent_response: str,
    tool_results: list[dict],
    margin_tau: float = 0.0,
) -> dict:
    """Run LOO causal attribution on an agent response."""
    untrusted_tool_names: set[str] = set()
    messages: list[Message] = [
        Message(role=MessageRole.USER, content=user_message),
    ]

    for tr in tool_results:
        name = tr.get("name", "unknown")
        resp = tr.get("response", {})
        text = resp if isinstance(resp, str) else str(resp)
        messages.append(Message(
            role=MessageRole.TOOL,
            content=text[:2000],
            tool_name=name,
        ))
        untrusted_tool_names.add(name)

    messages.append(Message(role=MessageRole.ASSISTANT, content=agent_response[:1000]))

    if not untrusted_tool_names:
        return {
            "verdict": "NO_TOOL_DATA",
            "explanation": "No untrusted tool results in context.",
        }

    provider = _get_provider()

    try:
        ctx = build_structured_context(
            messages=messages,
            untrusted_tool_names=frozenset(untrusted_tool_names),
        )

        action = ToolCall(
            name="respond",
            arguments={},
            raw_text=agent_response[:800],
        )

        attribution = await compute_attribution(
            ctx=ctx,
            action=action,
            proxy=provider,
        )

        detection = detect_dominant_spans(attribution, margin_tau=margin_tau)

        span_influences = {
            k: round(v, 4) for k, v in attribution.span_attributions_normalized.items()
        }

        if detection.is_attack_detected:
            flagged = ", ".join(detection.flagged_spans)
            verdict = "DOMINATED"
            explanation = (
                f"Untrusted tool(s) [{flagged}] dominate the response "
                f"(span influence > user influence). "
                f"Possible indirect prompt injection."
            )
        else:
            verdict = "SAFE"
            explanation = "User request is the dominant cause of the response."

        return {
            "verdict": verdict,
            "is_attack": detection.is_attack_detected,
            "flagged_spans": list(detection.flagged_spans),
            "user_influence": round(attribution.delta_user_normalized, 4),
            "span_influences": span_influences,
            "base_logprob": round(attribution.base_logprob, 4),
            "margin_tau": margin_tau,
            "explanation": explanation,
        }

    except Exception as e:
        logger.error(f"Causal Armor analysis failed: {e}", exc_info=True)
        return {
            "verdict": "ERROR",
            "explanation": f"Analysis failed: {e}",
        }
