"""Gemini REST transport plus exact-request replay. Keys never enter saved requests."""

import json
import os
import time
from pathlib import Path

import httpx

from .prompts import COMMON, STAGES
from .storage import digest, read, save


def key_from_environment(env_file: Path | None) -> str:
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    if env_file:
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.lower().startswith("gemini:"):
                return stripped.split(":", 1)[1].strip().strip("\"'")
            name, separator, value = stripped.partition("=")
            if separator and name.strip() in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
                return value.strip().strip("\"'")
    raise ValueError("Gemini key missing; use GEMINI_API_KEY or --env-file")


class Provider:
    def __init__(
        self, run: Path, model: str, env_file: Path | None = None, replay_from: Path | None = None
    ):
        self.run, self.model = run, model
        self.env_file, self.replay_from = env_file, replay_from
        self.last_attempt = None

    def instruction(self, stage):
        return COMMON + "\n" + STAGES[stage]

    def call(self, stage, payload, contract):
        request = {
            "systemInstruction": {"parts": [{"text": self.instruction(stage)}]},
            "contents": [
                {"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": contract.model_json_schema(),
            },
        }
        root = self.run / "calls"
        root.mkdir(exist_ok=True)
        attempt = root / f"{len(list(root.iterdir())) + 1:06d}"
        attempt.mkdir()
        self.last_attempt = attempt
        save(attempt / "request.json", request)
        fingerprint = digest(request)
        receipt = {
            "stage": stage,
            "requested_model": self.model,
            "request_sha256": fingerprint,
            "transport": "replay" if self.replay_from else "gemini",
        }
        began = time.perf_counter()
        secret = ""
        try:
            if self.replay_from:
                answer = self._replay(fingerprint)
            else:
                secret = key_from_environment(self.env_file)
                with httpx.Client(timeout=90) as client:
                    response = client.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/"
                        f"{self.model}:generateContent",
                        headers={"x-goog-api-key": secret},
                        json=request,
                    )
                receipt["http_status"] = response.status_code
                if not response.is_success:
                    raise ValueError(f"Gemini HTTP {response.status_code}")
                raw = response.json()
                save(attempt / "raw.json", raw)
                candidate = raw.get("candidates", [{}])[0]
                receipt.update(
                    model=raw.get("modelVersion"),
                    usage=raw.get("usageMetadata"),
                    finish_reason=candidate.get("finishReason"),
                )
                if candidate.get("finishReason") != "STOP":
                    raise ValueError("Gemini response did not finish with STOP")
                answer = json.loads(
                    "".join(
                        p.get("text", "")
                        for p in candidate["content"]["parts"]
                        if not p.get("thought")
                    )
                )
            save(attempt / "response.json", answer)
            result = contract.model_validate(answer)
            receipt["status"] = "parsed"
            return result
        except (httpx.HTTPError, ValueError, KeyError, OSError, IndexError) as exc:
            message = str(exc)
            if secret:
                message = message.replace(secret, "[REDACTED]")
            receipt.update(status="failed", error=message[:1500])
            raise ValueError(message[:1500]) from None
        finally:
            receipt["latency_s"] = round(time.perf_counter() - began, 3)
            save(attempt / "receipt.json", receipt)
            print(f"{stage}: {receipt.get('status')} ({receipt['latency_s']}s)", flush=True)

    def _replay(self, fingerprint):
        for path in sorted((self.replay_from / "calls").glob("*/receipt.json"), reverse=True):
            receipt = read(path)
            if (
                receipt.get("request_sha256") == fingerprint
                and receipt.get("requested_model") == self.model
                and receipt.get("status") == "parsed"
                and receipt.get("validation") != "rejected"
            ):
                return read(path.parent / "response.json")
        raise ValueError("No recorded response for this exact request and model")

    def record_validation(self, error=None):
        if self.last_attempt is None:
            return
        path = self.last_attempt / "receipt.json"
        receipt = read(path)
        receipt["validation"] = "rejected" if error else "accepted"
        if error:
            receipt["validation_error"] = str(error)
        save(path, receipt)
        self.last_attempt = None
