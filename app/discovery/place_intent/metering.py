"""Intent proposer 제공사와 무관한 사용량 집행 wrapper."""

from app.discovery.place_intent.contract import IntentProposer, LLMIntentOutput
from app.usage.gate import UsageGate
from app.usage.models import LanguageParseIntent


class MeteredIntentProposer:
    """실제 모델 호출 직전에 기존 language.parse 사용량 정책을 집행한다."""

    def __init__(self, inner: IntentProposer, gate: UsageGate):
        self._inner = inner
        self._gate = gate

    async def propose(self, utterance: str) -> LLMIntentOutput:
        intent = LanguageParseIntent(input_chars=len(utterance))
        permit = await self._gate.check(intent)
        await self._gate.consume(intent, permit)
        return await self._inner.propose(utterance)
