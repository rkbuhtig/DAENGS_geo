"""한 Capsule의 사실·문맥·Pin을 영구 원본 없이 결정론적 산책 일기로 투영한다."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.spatial_diary.context import (
    CONTEXT_POLICY_VERSION,
    DIARY_CALENDAR_TIMEZONE,
    context_facets,
)
from app.features.spatial_diary.contract import (
    ReviewDisposition,
    SubjectRole,
    TemporalPrecision,
    TrailContextSnapshot,
    WalkJournalContextFacets,
    WalkJournalEntry,
    WalkJournalFacts,
    WalkJournalProjection,
    WalkJournalReceipt,
)
from app.features.spatial_diary.episode import (
    PinEntry,
    SpatialDiaryEpisodeIntegrityError,
    SpatialDiaryEpisodeNotFoundError,
    load_pin_entries,
)
from app.features.spatial_diary.snapshot import ensure_repeatable_read_snapshot

NARRATION_POLICY_VERSION = 1
MAX_JOURNAL_ENTRIES = 100

_DIARY_ZONE = ZoneInfo(DIARY_CALENDAR_TIMEZONE)
_ROLE_LABELS = {
    SubjectRole.DOG: "강아지",
    SubjectRole.OWNER: "견주",
    SubjectRole.JOINT: "강아지와 견주",
    SubjectRole.EXTERNAL: "주변 대상",
}


def _duration_text(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3_600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}시간")
    if minutes:
        parts.append(f"{minutes}분")
    if seconds or not parts:
        parts.append(f"{seconds}초")
    return " ".join(parts)


def _context_sentence(facets: dict[str, str]) -> str | None:
    precipitation = {
        "rain": "비 오는 날로 분류된",
        "dry": "비 없는 날로 분류된",
    }.get(facets["precipitation"])
    daylight = {"day": "낮", "night": "밤"}.get(facets["daylight"])
    if precipitation and daylight:
        return f"{precipitation} {daylight} 산책이었어요."
    if precipitation:
        return f"{precipitation} 산책이었어요."
    if daylight:
        return f"{daylight} 산책이었어요."
    return None


def _entry_narration(entry: PinEntry) -> str:
    pin = entry.pin
    attestation = entry.attestation
    if pin.temporal_precision is TemporalPrecision.UNKNOWN:
        prefix = "시간을 특정하지 않고"
    else:
        local_time = pin.event_at.astimezone(_DIARY_ZONE).strftime("%H시 %M분")
        suffix = "쯤" if pin.temporal_precision is TemporalPrecision.APPROXIMATE else ""
        prefix = f"{local_time}{suffix},"

    roles = sorted({_ROLE_LABELS[claim.subject_role] for claim in attestation.claims})
    subject = "·".join(roles) + "에 관한 " if roles else ""
    if attestation.review_disposition is ReviewDisposition.UNCERTAIN:
        return f"{prefix} 사용자가 확실하지 않지만 {subject}장면을 기억에 남겼어요."
    return f"{prefix} 사용자가 {subject}장면으로 확인해 기억에 남겼어요."


def _journal_title(started_at: datetime) -> str:
    local_day = started_at.astimezone(_DIARY_ZONE)
    return f"{local_day.year}년 {local_day.month}월 {local_day.day}일 산책 일기"


def _journal_summary(facts: WalkJournalFacts, facets: dict[str, str], pin_count: int) -> str:
    sentences = [
        (
            f"기록상 {_duration_text(facts.duration_s)} 동안 "
            f"{facts.moving_distance_m:,}m를 이동했어요."
        )
    ]
    context = _context_sentence(facets)
    if context is not None:
        sentences.append(context)
    if pin_count:
        sentences.append(f"기억으로 남긴 장면은 {pin_count}개예요.")
    else:
        sentences.append("기억으로 남긴 장면은 아직 없어요.")
    return " ".join(sentences)


async def query_walk_journal(
    db: AsyncSession,
    session_id: str,
    *,
    generated_at: datetime | None = None,
) -> WalkJournalProjection:
    """한 repeatable-read snapshot에서 재생성 가능한 산책 일기 한 편을 조립한다."""

    await ensure_repeatable_read_snapshot(db)
    material = (await db.execute(text("""
        SELECT manifest.capsule_version, manifest.dog_id,
               facts.session_id AS facts_session_id,
               facts.dog_id AS facts_dog_id,
               facts.started_at, facts.ended_at, facts.duration_s,
               facts.moving_distance_m, facts.moving_s,
               facts.stop_count, facts.stop_s,
               context.session_id AS context_session_id,
               context.context_version, context.status, context.walked_at,
               context.source_observed_at, context.captured_at, context.provider,
               context.precipitation_mm, context.temperature_c,
               context.humidity_pct, context.sun_elevation_deg,
               context.failure_reason
        FROM walk_capsule_manifest manifest
        LEFT JOIN walk_facts facts ON facts.session_id = manifest.session_id
        LEFT JOIN walk_trail_context context ON context.session_id = manifest.session_id
        WHERE manifest.session_id = :session_id
    """), {"session_id": session_id})).one_or_none()
    if material is None:
        raise SpatialDiaryEpisodeNotFoundError("sealed walk capsule not found")
    if material.facts_session_id is None or material.context_session_id is None:
        raise SpatialDiaryEpisodeIntegrityError("sealed capsule is missing journal material")
    if material.facts_dog_id != material.dog_id:
        raise SpatialDiaryEpisodeIntegrityError("capsule and walk facts disagree on dog")

    context = TrailContextSnapshot(
        session_id=material.context_session_id,
        context_version=material.context_version,
        status=material.status,
        walked_at=material.walked_at,
        source_observed_at=material.source_observed_at,
        captured_at=material.captured_at,
        provider=material.provider,
        precipitation_mm=material.precipitation_mm,
        temperature_c=material.temperature_c,
        humidity_pct=material.humidity_pct,
        sun_elevation_deg=material.sun_elevation_deg,
        failure_reason=material.failure_reason,
    )

    pin_entries = await load_pin_entries(
        db,
        [session_id],
        limit=MAX_JOURNAL_ENTRIES + 1,
    )
    if len(pin_entries) > MAX_JOURNAL_ENTRIES:
        raise SpatialDiaryEpisodeIntegrityError("walk journal entry limit exceeded")
    entries = tuple(
        WalkJournalEntry(
            pin=entry.pin,
            attestation=entry.attestation,
            narration=_entry_narration(entry),
        )
        for entry in pin_entries
    )
    journal_facts = WalkJournalFacts(
        started_at=material.started_at,
        ended_at=material.ended_at,
        duration_s=material.duration_s,
        moving_distance_m=material.moving_distance_m,
        moving_s=material.moving_s,
        stop_count=material.stop_count,
        stop_s=material.stop_s,
    )
    facets = context_facets(context)
    return WalkJournalProjection(
        session_id=session_id,
        dog_id=material.dog_id,
        facts=journal_facts,
        context=context,
        context_facets=WalkJournalContextFacets(
            precipitation=facets["precipitation"],
            daylight=facets["daylight"],
            policy_version=CONTEXT_POLICY_VERSION,
        ),
        title=_journal_title(material.started_at),
        summary=_journal_summary(journal_facts, facets, len(entries)),
        entries=entries,
        receipt=WalkJournalReceipt(
            narration_policy_version=NARRATION_POLICY_VERSION,
            context_policy_version=CONTEXT_POLICY_VERSION,
            capsule_version=material.capsule_version,
            generated_at=generated_at or datetime.now(UTC),
            pin_count=len(entries),
        ),
    )
