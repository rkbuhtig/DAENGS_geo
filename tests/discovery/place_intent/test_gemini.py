import json

import httpx
import pytest

from app.discovery.place_intent.contract import (
    IntentProposerInvalidOutputError,
    ProposalDisposition,
    ProposalReason,
    SearchModeId,
)
from app.discovery.place_intent.gemini import (
    GeminiIntentProposer,
    GeminiIntentProposerResponseError,
)


def _completed(output: dict) -> dict:
    return {
        "status": "completed",
        "steps": [
            {
                "type": "model_output",
                "content": [{"type": "text", "text": json.dumps(output)}],
            }
        ],
    }


@pytest.mark.asyncio
async def test_gemini_interactions_request_is_stateless_and_structured() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/interactions"
        assert "key" not in request.url.params
        assert request.headers["x-goog-api-key"] == "test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "gemini-3.1-flash-lite"
        assert payload["input"] == "어디 갈까"
        assert payload["store"] is False
        assert "반려견 동반 장소 검색" in payload["system_instruction"]
        assert "buy와 dog_toy는 둘 다 hypothetical" in payload["system_instruction"]
        output_format = payload["response_format"]
        assert output_format["type"] == "text"
        assert output_format["mime_type"] == "application/json"
        schema = output_format["schema"]
        interpretation = schema["properties"]["interpretations"]["items"]
        proposal = interpretation["properties"]["proposals"]["items"]
        assert interpretation["properties"]["search_mode"]["enum"] == [
            "directed_search",
            "open_discovery",
        ]
        assert interpretation["properties"]["proposals"]["minItems"] == 0
        assert schema["properties"]["reason"]["enum"][0] == "none"
        assert "reason" in schema["required"]
        assert "intent_type" in proposal["properties"]
        assert set(proposal["properties"]["intent_type"]["enum"]) == {
            "kind",
            "purpose",
            "boolean_capability",
            "semantic",
            "activity",
            "object",
        }
        assert proposal["properties"]["activity_id"]["enum"] == ["play", "buy"]
        assert proposal["properties"]["object_id"]["enum"] == ["dog_toy"]
        assert "intent" not in proposal["properties"]
        serialized_schema = json.dumps(output_format["schema"])
        assert "$ref" not in serialized_schema
        assert "$defs" not in serialized_schema
        assert "pattern" not in serialized_schema
        assert "maxItems" not in serialized_schema
        return httpx.Response(
            200,
            json=_completed(
                {
                    "disposition": "abstained",
                    "interpretations": [],
                    "reason": "insufficient_target",
                }
            ),
        )

    proposer = GeminiIntentProposer(
        "test-key",
        "gemini-3.1-flash-lite",
        transport=httpx.MockTransport(handle),
    )

    output = await proposer.propose("어디 갈까")

    assert output.disposition is ProposalDisposition.ABSTAINED


@pytest.mark.asyncio
async def test_gemini_flat_adapter_output_becomes_typed_intent() -> None:
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_completed(
                {
                    "disposition": "proposed",
                    "reason": "none",
                    "interpretations": [
                        {
                            "search_mode": "directed_search",
                            "proposals": [
                                {
                                    "role": "required_target",
                                    "intent_type": "purpose",
                                    "purpose_id": "dining",
                                    "quote": "밥 먹을 곳",
                                    "start": 0,
                                }
                            ]
                        }
                    ],
                }
            ),
        )

    proposer = GeminiIntentProposer(
        "test-key",
        "model",
        transport=httpx.MockTransport(handle),
    )

    output = await proposer.propose("밥 먹을 곳")

    proposal = output.interpretations[0].proposals[0]
    assert output.interpretations[0].search_directive.mode is SearchModeId.DIRECTED_SEARCH
    assert proposal.intent.intent_type == "purpose"
    assert proposal.intent.purpose_id.value == "dining"
    assert proposal.evidence.start is None and proposal.evidence.end is None


@pytest.mark.asyncio
async def test_gemini_flat_adapter_accepts_groundable_mode_only_open_discovery() -> None:
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_completed(
                {
                    "disposition": "proposed",
                    "reason": "none",
                    "interpretations": [
                        {
                            "search_mode": "open_discovery",
                            "search_mode_quote": "네가 추천해봐",
                            "proposals": [],
                        }
                    ],
                }
            ),
        )

    proposer = GeminiIntentProposer("test-key", "model", transport=httpx.MockTransport(handle))

    output = await proposer.propose("오늘 심심한데 네가 추천해봐")

    interpretation = output.interpretations[0]
    assert interpretation.search_directive.mode is SearchModeId.OPEN_DISCOVERY
    assert interpretation.search_directive.evidence.quote == "네가 추천해봐"
    assert interpretation.proposals == ()


@pytest.mark.asyncio
async def test_gemini_abstention_discards_schema_forced_incomplete_proposals() -> None:
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_completed(
                {
                    "disposition": "abstained",
                    "interpretations": [
                        {
                            "search_mode": "directed_search",
                            "proposals": [
                                {
                                    "role": "hypothetical",
                                    "intent_type": "semantic",
                                    "quote": "강아지가 좋아하는거 있는곳",
                                }
                            ]
                        }
                    ],
                    "reason": "insufficient_target",
                }
            ),
        )

    proposer = GeminiIntentProposer(
        "test-key",
        "model",
        transport=httpx.MockTransport(handle),
    )

    output = await proposer.propose("강아지가 좋아하는거 있는곳")

    assert output.disposition is ProposalDisposition.ABSTAINED
    assert output.reason is ProposalReason.INSUFFICIENT_TARGET
    assert output.interpretations == ()


@pytest.mark.asyncio
async def test_gemini_preserves_unspecified_abstention_without_guessing_a_reason() -> None:
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_completed(
                {
                    "disposition": "abstained",
                    "interpretations": [],
                    "reason": "none",
                }
            ),
        )

    proposer = GeminiIntentProposer("test-key", "model", transport=httpx.MockTransport(handle))

    output = await proposer.propose("안녕")

    assert output.disposition is ProposalDisposition.ABSTAINED
    assert output.reason is ProposalReason.UNSPECIFIED
    assert output.interpretations == ()


@pytest.mark.asyncio
async def test_gemini_rejects_incomplete_or_invalid_interactions() -> None:
    async def incomplete(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "incomplete", "steps": []})

    proposer = GeminiIntentProposer(
        "test-key",
        "model",
        transport=httpx.MockTransport(incomplete),
    )
    with pytest.raises(GeminiIntentProposerResponseError, match="did not complete"):
        await proposer.propose("카페")

    async def invalid(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "steps": [
                    {
                        "type": "model_output",
                        "content": [{"type": "text", "text": "not-json"}],
                    }
                ],
            },
        )

    proposer = GeminiIntentProposer(
        "test-key",
        "model",
        transport=httpx.MockTransport(invalid),
    )
    with pytest.raises(
        IntentProposerInvalidOutputError,
        match="invalid intent payload",
    ) as captured:
        await proposer.propose("카페")
    assert captured.value.raw_output == "not-json"


@pytest.mark.asyncio
async def test_gemini_rejects_non_json_success_response_as_provider_failure() -> None:
    async def invalid_body(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    proposer = GeminiIntentProposer(
        "test-key",
        "model",
        transport=httpx.MockTransport(invalid_body),
    )

    with pytest.raises(GeminiIntentProposerResponseError, match="not valid JSON"):
        await proposer.propose("카페")


@pytest.mark.asyncio
async def test_gemini_does_not_salvage_invalid_proposed_output() -> None:
    async def invalid(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_completed(
                {
                    "disposition": "proposed",
                    "reason": "none",
                    "interpretations": [
                        {
                            "proposals": [
                                {
                                    "role": "required_target",
                                    "intent_type": "semantic",
                                    "quote": "조용한 곳",
                                }
                            ]
                        }
                    ],
                }
            ),
        )

    proposer = GeminiIntentProposer(
        "test-key",
        "model",
        transport=httpx.MockTransport(invalid),
    )

    with pytest.raises(IntentProposerInvalidOutputError, match="invalid intent payload"):
        await proposer.propose("조용한 곳")
