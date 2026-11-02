"""Natural conversation phrasing constrained to verified bundle state."""

from __future__ import annotations

import json
import logging
import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent.bundle_contracts import AgentTaskBundle
from agent.contracts import ConversationMessage, ConversationRole, TrustLabel
from agent.providers import ModelProvider, ProviderError

logger = logging.getLogger(__name__)


class ConversationReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=800)


class ModelConversationComposer:
    def __init__(self, provider: ModelProvider | None) -> None:
        self._provider = provider

    async def compose(
        self,
        *,
        bundle: AgentTaskBundle,
        locale: str,
        fallback: str,
        request_id: UUID,
    ) -> str:
        provider = self._provider
        if provider is None or not provider.available:
            return fallback
        state = {
            "bundle_status": bundle.status.value,
            "active_item_id": str(bundle.active_item_id) if bundle.active_item_id else None,
            "items": [
                {
                    "item_id": str(item.item_id),
                    "intent": item.intent.value,
                    "evidence": item.evidence,
                    "status": item.status.value,
                    "result": item.result,
                    "error_code": item.error_code,
                }
                for item in bundle.items
            ],
        }
        language = "English" if locale == "en-US" else "Simplified Chinese"
        messages = [
            ConversationMessage(
                role=ConversationRole.SYSTEM,
                trust=TrustLabel.SYSTEM_POLICY,
                content=(
                    f"Write a warm, clear banking-assistant reply in {language}, using two to "
                    "four short sentences. Acknowledge the request, state verified progress, "
                    "and explain the next action. Use only facts in bundle_state. Never claim "
                    "that a pending, deferred, failed, or approval-waiting action succeeded. "
                    "Do not reveal internal IDs. Return only the schema field."
                ),
            ),
            ConversationMessage(
                role=ConversationRole.USER,
                content=json.dumps({"bundle_state": state}, ensure_ascii=False),
            ),
        ]
        try:
            generated = await provider.generate_structured(
                messages=messages,
                output_model=ConversationReply,
                request_id=request_id,
                temperature=0.2,
                max_tokens=256,
            )
        except ProviderError as exc:
            logger.warning("conversation composition failed code=%s", exc.code)
            return fallback
        reply = generated.output.text.strip()
        if re.search(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
            reply,
            re.I,
        ):
            logger.warning("conversation composition exposed an internal identifier")
            return fallback
        allowed_numbers = set(re.findall(r"\d+(?:\.\d+)?", json.dumps(state)))
        used_numbers = set(re.findall(r"\d+(?:\.\d+)?", reply))
        if not used_numbers.issubset(allowed_numbers):
            logger.warning("conversation composition introduced an unverified number")
            return fallback
        return reply
