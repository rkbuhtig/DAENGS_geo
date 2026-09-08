"""Frozen writing A/B and bounded HTTP behavior, without live model calls."""

import json

import httpx
import pytest

from scripts.spikes.diary_storyboard.how_stamp_demo import run as demo
from scripts.spikes.diary_storyboard.how_writing_experiment import execute, prepare
from scripts.spikes.diary_storyboard.storage import read, save


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp("writing-source") / "prepared"
    demo(path, writing_comparison=True)
    return path


def transport(monkeypatch, sent, *, duplicate=False, http_status=200, tokens=100):
    def respond(request):
        body = json.loads(request.content)
        sent.append(body)
        payload = json.loads(body["contents"][0]["parts"][0]["text"])
        cards = [{"stamp_id": s["id"], "title": "합성", "text": "검사용 문장"}
                 for s in payload["stamps"]]
        if duplicate:
            cards[-1]["stamp_id"] = cards[0]["stamp_id"]
        return httpx.Response(http_status, json={
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{
                "text": json.dumps({"title": "합성", "cards": cards})}]}}],
            "modelVersion": "fake", "usageMetadata": {"totalTokenCount": tokens,
                                                       "promptTokenCount": tokens - 10,
                                                       "candidatesTokenCount": 10},
        })
    client = httpx.Client
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-secret")
    monkeypatch.setattr(httpx, "Client", lambda **kw: client(
        transport=httpx.MockTransport(respond), **kw))


def test_same_stamps_prompt_schema_and_exact_input_encoder_with_no_resend(
    tmp_path, source, monkeypatch
):
    sent = []
    transport(monkeypatch, sent)
    prepare(tmp_path, source)
    assert not sent
    result = execute(tmp_path)
    assert result["attempts"] == result["accepted"] == len(sent) == 6
    assert result["known_usage_totals"]["totalTokenCount"] == 600
    assert execute(tmp_path) == result and len(sent) == 6
    for case in ("all_records", "no_record", "gap"):
        comparison = read(source / case / "writing_comparison.json")
        requests, outputs = [], []
        for arm in ("baseline", "compact"):
            root = tmp_path / case / arm
            request = read(root / "calls/000001/request.json")
            assert request == read(root / "planned_request.json")
            text = request["contents"][0]["parts"][0]["text"]
            assert text == json.dumps(comparison[f"{arm}_input"], ensure_ascii=False,
                                      separators=(",", ":"), allow_nan=False)
            requests.append(request)
            outputs.append(read(root / "accepted.json"))
        assert requests[0]["generationConfig"] == requests[1]["generationConfig"]
        assert requests[0]["systemInstruction"] == requests[1]["systemInstruction"]
        assert requests[0]["contents"] != requests[1]["contents"]
        assert outputs[0] == outputs[1]  # same source anchors and exact refs
    assert "test-only-secret" not in "".join(p.read_text(encoding="utf-8")
                                               for p in tmp_path.rglob("*.json"))


@pytest.mark.parametrize("filename", ["writing_comparison.json", "baseline/planned_request.json"])
def test_changed_frozen_input_fails_before_network(tmp_path, source, monkeypatch, filename):
    sent = []
    transport(monkeypatch, sent)
    prepare(tmp_path, source)
    path = tmp_path / "all_records" / filename
    data = read(path)
    data["unexpected_change"] = True
    save(path, data)
    with pytest.raises(ValueError, match="changed"):
        execute(tmp_path)
    assert not sent


def test_interrupted_attempt_stops_all_calls_and_is_never_retried(tmp_path, source, monkeypatch):
    sent = []
    transport(monkeypatch, sent)
    prepare(tmp_path, source)
    (tmp_path / "all_records/baseline/calls/000001").mkdir(parents=True)
    result = execute(tmp_path)
    assert result["attempts"] == result["unknown_usage_attempts"] == 1
    assert not sent and execute(tmp_path) == result


def test_duplicate_record_rejected_without_repair_or_retry(tmp_path, source, monkeypatch):
    sent = []
    transport(monkeypatch, sent, duplicate=True)
    prepare(tmp_path, source)
    result = execute(tmp_path)
    assert result["attempts"] == len(sent) == 6 and result["accepted"] == 0
    assert all(r["structural_status"] == "rejected" for r in result["rows"])
    assert execute(tmp_path) == result and len(sent) == 6


@pytest.mark.parametrize("http_status,tokens,unknown", [(429, 100, 1), (200, 40000, 0)])
def test_unknown_usage_or_observed_token_threshold_stops_further_calls(
    tmp_path, source, monkeypatch, http_status, tokens, unknown
):
    sent = []
    transport(monkeypatch, sent, http_status=http_status, tokens=tokens)
    prepare(tmp_path, source)
    result = execute(tmp_path)
    assert result["attempts"] == len(sent) == 1
    assert result["unknown_usage_attempts"] == unknown
    assert execute(tmp_path) == result and len(sent) == 1


def test_modified_accepted_text_cannot_masquerade_as_saved_response(tmp_path, source, monkeypatch):
    sent = []
    transport(monkeypatch, sent)
    prepare(tmp_path, source)
    execute(tmp_path)
    path = tmp_path / "all_records/baseline/accepted.json"
    data = read(path)
    data["cards"][0]["text"] = "나중에 바꾼 문장"
    save(path, data)
    with pytest.raises(ValueError, match="accepted output changed"):
        execute(tmp_path)
    assert len(sent) == 6
