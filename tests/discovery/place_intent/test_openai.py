import json

import httpx
import pytest

from app.discovery.place_intent.contract import (
    IntentProposerInvalidOutputError,
    ProposalDisposition,
)
from app.discovery.place_intent.openai import (
    IntentProposerResponseError,
    MeteredIntentProposer,
    OpenAIIntentProposer,
)
from app.discovery.place_intent.prompt import strict_output_schema
from app.usage.gate import UsageGate, usage_request_scope
from app.usage.ledger import InMemoryLedger
from app.usage.models import UsageDenied
from app.usage.policy import DenyAllPolicy

_ABSTAINED = {
    "disposition": "abstained",
    "interpretations": [],
    "reason": "insufficient_target",
}


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": json.dumps(payload)},
                    ],
                }
            ],
        },
    )


async def test_openai_adapter_uses_responses_strict_schema_without_storing() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _response(_ABSTAINED)

    proposer = OpenAIIntentProposer(
        "test-key",
        "test-model",
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handle),
    )
    result = await proposer.propose("어디 갈까")

    assert result.disposition is ProposalDisposition.ABSTAINED
    assert len(seen) == 1
    request = seen[0]
    assert request.url == "https://example.test/v1/responses"
    assert request.headers["authorization"] == "Bearer test-key"
    payload = json.loads(request.content)
    assert payload["store"] is False
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert payload["input"] == "어디 갈까"


def test_strict_schema_requires_every_declared_object_property() -> None:
    schema = strict_output_schema()
    assert schema["type"] == "object" and "anyOf" not in schema
    serialized = json.dumps(schema)
    assert all(
        f'"{keyword}"' not in serialized
        for keyword in ("default", "title", "discriminator", "oneOf", "const")
    )

    def assert_strict(value: object) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                assert value.get("additionalProperties") is False
                assert set(value["required"]) == set(properties)
            for child in value.values():
                assert_strict(child)
        elif isinstance(value, list):
            for child in value:
                assert_strict(child)

    assert_strict(schema)


async def test_openai_adapter_rejects_refusal_or_invalid_payload() -> None:
    def refusal(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "refusal", "refusal": "no"}],
                    }
                ],
            },
        )

    proposer = OpenAIIntentProposer("key", "model", transport=httpx.MockTransport(refusal))
    with pytest.raises(IntentProposerResponseError, match="refused"):
        await proposer.propose("카페")

    def invalid(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output_text": "not-json",
            },
        )

    proposer = OpenAIIntentProposer("key", "model", transport=httpx.MockTransport(invalid))
    with pytest.raises(
        IntentProposerInvalidOutputError,
        match="invalid intent payload",
    ) as captured:
        await proposer.propose("카페")
    assert captured.value.raw_output == "not-json"


async def test_openai_rejects_non_json_success_response_as_provider_failure() -> None:
    def invalid_body(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    proposer = OpenAIIntentProposer(
        "key",
        "model",
        transport=httpx.MockTransport(invalid_body),
    )

    with pytest.raises(IntentProposerResponseError, match="not valid JSON"):
        await proposer.propose("카페")


async def test_usage_denial_happens_before_network_call() -> None:
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(_ABSTAINED)

    inner = OpenAIIntentProposer("key", "model", transport=httpx.MockTransport(handle))
    proposer = MeteredIntentProposer(
        inner,
        UsageGate(DenyAllPolicy(), InMemoryLedger()),
    )
    async with usage_request_scope():
        with pytest.raises(UsageDenied, match="not configured"):
            await proposer.propose("카페")
    assert calls == 0
