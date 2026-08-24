"""baseline - 기존 migrations/*.sql 을 그대로 고정

`migrations/` 의 12개 파일을 순서대로 실행한 것과 같은 스키마를 만든다. 원본 SQL 을 한 글자도
바꾸지 않고 옮겼다 - 이 리비전은 **역사**이고, 다시 쓰면 이미 이 스키마로 돌아가는 DB 와 어긋난다.

`011` 이 두 개인 것도 그대로 뒀다. 서로 다른 두 브랜치가 같은 번호를 집어서 main 에서 만난
결과이고, 둘은 각각 anchor 테이블과 walk_fix 컬럼이라 순서가 상관없어 **우연히** 무사했다.
번호로 순서를 정하던 방식이 실패한 지점이라, 이 러너를 도입하는 이유의 실물이다.

**이미 이 스키마로 돌아가는 DB 는 이걸 실행하면 안 된다.** `alembic stamp 0001` 로 적용됨
표시만 한다. 008 의 백필 UPDATE 세 개가 멱등이 아니기 때문이다 - 다시 돌리면
`walk_facts.record_version` 이 3 에서 2 로 내려가고 `walk_session.state` 의 sealed/derived 가
뭉개진다.

downgrade 는 없다. 이 아래는 빈 데이터베이스다.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 원본 파일별로 나눠 둔다. 어느 문장이 어디서 왔는지 diff 에서 보이게.
SOURCES: tuple[tuple[str, str], ...] = (
    (
        "001_init.sql",
        """
-- DAENGS_geo 초기 스키마. docker-compose 첫 기동 시 자동 실행.
CREATE EXTENSION IF NOT EXISTS postgis;

-- 병원/약국 POI. 원천은 공공데이터(지방행정 인허가). 제공사 로컬검색 결과 저장 금지.
CREATE TABLE IF NOT EXISTS place (
    id            BIGSERIAL PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('hospital', 'pharmacy')),
    name          TEXT NOT NULL,
    address       TEXT,
    phone         TEXT,
    location      geography(Point, 4326) NOT NULL,
    is_night      BOOLEAN NOT NULL DEFAULT FALSE,   -- 야간 진료 표방 (영업시간과 별개 플래그)
    is_24h        BOOLEAN NOT NULL DEFAULT FALSE,
    hours         JSONB,                             -- app/geo/hours.py 형식. NULL = 미상
    source        TEXT NOT NULL,                     -- 'public:localdata' 등
    source_id     TEXT,                              -- 원천 식별자 (중복 적재 방지)
    active        BOOLEAN NOT NULL DEFAULT TRUE,     -- 폐업 = FALSE
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS place_location_gix ON place USING GIST (location);
CREATE INDEX IF NOT EXISTS place_kind_idx     ON place (kind) WHERE active;
""",
    ),
    (
        "002_tags_scale.sql",
        """
-- name-tagging + 인허가 규모 지표
ALTER TABLE place ADD COLUMN IF NOT EXISTS tags        TEXT[]  NOT NULL DEFAULT '{}';
ALTER TABLE place ADD COLUMN IF NOT EXISTS area_m2     NUMERIC;      -- 인허가 면적 (규모 표시용)
ALTER TABLE place ADD COLUMN IF NOT EXISTS staff_count INTEGER;      -- 인허가 종사자수
CREATE INDEX IF NOT EXISTS place_tags_gin ON place USING GIN (tags);
""",
    ),
    (
        "003_mois_ingest.sql",
        """
-- 행정안전부 동물병원/동물약국 OpenAPI 동기화 메타데이터.
ALTER TABLE place ADD COLUMN IF NOT EXISTS source_updated_at   TIMESTAMPTZ;
ALTER TABLE place ADD COLUMN IF NOT EXISTS license_status_code TEXT;
ALTER TABLE place ADD COLUMN IF NOT EXISTS license_status_name TEXT;
ALTER TABLE place ADD COLUMN IF NOT EXISTS coordinate_source   TEXT;
ALTER TABLE place ADD COLUMN IF NOT EXISTS raw_data            JSONB;

CREATE INDEX IF NOT EXISTS place_source_updated_idx
    ON place (source, source_updated_at);

CREATE TABLE IF NOT EXISTS ingest_state (
    source      TEXT PRIMARY KEY,
    watermark   TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
""",
    ),
    (
        "004_kcisa_facility.sql",
        """
-- KCISA 반려동물 동반 문화시설 기반층. 스냅샷 통째 교체가 설계 단위다 —
-- 행 단위 증분 없음(원천에 안정 ID가 없다). place(MOIS 인허가)는 의료 오버레이로 남는다.
CREATE TABLE IF NOT EXISTS facility (
    id           BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL,             -- 정규화 슬러그: cafe/travel/hospital/pharmacy/...
    category3    TEXT NOT NULL,             -- 원천 표기 그대로
    sido         TEXT,
    sigungu      TEXT,
    address      TEXT,
    phone        TEXT,
    homepage     TEXT,
    hours_text   TEXT,                      -- 원문 보존. place.hours(JSONB) 구조화는 별도 단계
    closed_days  TEXT,
    parking      BOOLEAN,
    indoor       BOOLEAN,
    outdoor      BOOLEAN,
    pet          JSONB,                     -- 동반가능·전용·크기·제한·추가요금
    location     geography(Point,4326) NOT NULL,
    last_written DATE,                      -- 원천 최종작성일
    snapshot     TEXT NOT NULL              -- 예: '2025-03-24'. 교체 단위이자 화면 표기용
);
CREATE INDEX IF NOT EXISTS facility_gix       ON facility USING gist (location);
CREATE INDEX IF NOT EXISTS facility_kind_idx  ON facility (kind);

-- 기반층 ↔ 인허가 오버레이. 매칭 방법과 거리를 남긴다 — "왜 이 둘이 같은 가게인가"에 답하는 자리.
CREATE TABLE IF NOT EXISTS facility_place_link (
    facility_id BIGINT NOT NULL REFERENCES facility (id) ON DELETE CASCADE,
    place_id    BIGINT NOT NULL REFERENCES place (id) ON DELETE CASCADE,
    method      TEXT NOT NULL,
    distance_m  REAL,
    matched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (facility_id, place_id)
);
CREATE INDEX IF NOT EXISTS facility_place_link_place_idx ON facility_place_link (place_id);
""",
    ),
    (
        "005_facility_link_multi_source.sql",
        """
-- 기반층 다원천화. facility는 원천별로 통째 교체하고(source 단위),
-- 링크는 특정 테이블 FK가 아니라 (source, source_ref) 쌍으로 어떤 원천이든 받는다.
ALTER TABLE facility ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'kcisa';
ALTER TABLE facility ADD COLUMN IF NOT EXISTS raw    JSONB;
CREATE INDEX IF NOT EXISTS facility_source_idx ON facility (source);

CREATE TABLE IF NOT EXISTS facility_link (
    facility_id BIGINT NOT NULL REFERENCES facility (id) ON DELETE CASCADE,
    source      TEXT NOT NULL,     -- 'mois:place'(의료 인허가) | 'facility'(원천 간 동일 시설) | 이후 원천
    source_ref  TEXT NOT NULL,     -- place.id / facility.id / 원천 고유키 — 문자열로 통일
    method      TEXT NOT NULL,
    distance_m  REAL,
    confidence  REAL,
    matched_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (facility_id, source, source_ref)
);
CREATE INDEX IF NOT EXISTS facility_link_ref_idx ON facility_link (source, source_ref);

-- 기존 전용 링크 이전 후 폐기
INSERT INTO facility_link (facility_id, source, source_ref, method, distance_m, matched_at)
SELECT facility_id, 'mois:place', place_id::text, method, distance_m, matched_at
FROM facility_place_link
ON CONFLICT DO NOTHING;
DROP TABLE IF EXISTS facility_place_link;
""",
    ),
    (
        "006_facility_source_ref.sql",
        """
-- 안정 식별자. facility.id(BIGSERIAL)는 스냅샷 교체마다 바뀌므로 외부가 잡으면 안 된다.
-- 원천 고유키를 1급으로 올리고, 적재는 (source, source_ref) UPSERT로 바꾼다 →
-- id가 교체 사이에 유지되고, 즐겨찾기·추천 이력이 나중에 붙어도 깨지지 않는다.
ALTER TABLE facility ADD COLUMN IF NOT EXISTS source_ref TEXT;
ALTER TABLE facility ADD COLUMN IF NOT EXISTS synced_at  TIMESTAMPTZ;

-- 이번 마이그레이션 시점의 기존 행은 ref가 없다. 적재를 다시 돌리면 UPSERT가 ref를 채우고,
-- 못 채운 행(원천에서 사라진 것)은 prune이 지운다. 그때까지만 NULL을 허용한다.
CREATE UNIQUE INDEX IF NOT EXISTS facility_source_ref_uidx
    ON facility (source, source_ref) WHERE source_ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS facility_synced_idx ON facility (source, synced_at);
""",
    ),
    (
        "007_walk_sessions.sql",
        """
-- 산책 수집 코어. 계약은 docs/contracts/walk-record.md — 사실만, 판정·서술 없음.
--
-- walk_fix 는 **세션 진행 중에만** 존재한다. finish 가 사실을 계산하고 나면 그 자리에서
-- 지운다. 궤적 영구 보관은 프라이버시 정책(절삭·보관 기간)이 서기 전까지 하지 않는다 —
-- 시작·종료 좌표는 집 주소다. 삭제는 영구 방침이 아니라 정책 결정 전의 안전 기본값이다.

CREATE TABLE IF NOT EXISTS walk_session (
    id             TEXT PRIMARY KEY,          -- 클라이언트 생성(UUID). 오프라인 시작 + 멱등 재전송
    dog_id         TEXT NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL,
    ended_at       TIMESTAMPTZ,               -- NULL = 진행 중
    fix_count      INTEGER NOT NULL DEFAULT 0,  -- 수신 원본 수 (거부 포함)
    mock_fix_count INTEGER NOT NULL DEFAULT 0,  -- 재생·가짜 위치 수. 사실이 아니라 운영 표식
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS walk_session_dog_idx ON walk_session (dog_id, started_at);

CREATE TABLE IF NOT EXISTS walk_fix (
    session_id TEXT NOT NULL REFERENCES walk_session (id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,              -- 수신 순서. 측정 시각(at)과 둘 다 보존한다
    at         TIMESTAMPTZ NOT NULL,
    lat        DOUBLE PRECISION NOT NULL,
    lng        DOUBLE PRECISION NOT NULL,
    accuracy_m REAL,
    is_mock    BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (session_id, seq)
);

CREATE TABLE IF NOT EXISTS walk_facts (
    session_id        TEXT PRIMARY KEY REFERENCES walk_session (id) ON DELETE CASCADE,
    record_version    INTEGER NOT NULL,
    dog_id            TEXT NOT NULL,
    started_at        TIMESTAMPTZ NOT NULL,
    ended_at          TIMESTAMPTZ NOT NULL,
    duration_s        INTEGER NOT NULL,
    distance_m        INTEGER NOT NULL,
    moving_distance_m INTEGER NOT NULL,
    moving_s          INTEGER NOT NULL,
    stop_count        INTEGER NOT NULL,
    stop_s            INTEGER NOT NULL,
    avg_speed_mps     DOUBLE PRECISION,     -- REAL 은 왕복에서 값이 변한다 (1.398 → 1.3980000019)
    fix_count         INTEGER NOT NULL,
    quality           JSONB NOT NULL,         -- 수신/수용/거부 사유별 계수. 계약 밖 운영 데이터
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
""",
    ),
    (
        "008_walk_collection_hardening.sql",
        """
-- PR36 후속 하드닝.
-- 1) client_seq는 모바일 재전송의 안정 키, seq는 서버 수신 순서다.
-- 2) finish는 OPEN → SEALED → DERIVED → PURGED 뒤에만 원좌표를 지운다.
-- 3) mock/device 출처와 계산 버전을 결과에 남겨 baseline 오염을 막는다.
-- 4) 원좌표 삭제 전에 공간 좌표가 있는 정지 occurrence를 파생한다.

ALTER TABLE walk_session
    ADD COLUMN IF NOT EXISTS state TEXT NOT NULL DEFAULT 'open',
    ADD COLUMN IF NOT EXISTS evidence_origin TEXT NOT NULL DEFAULT 'unknown';

UPDATE walk_session
SET state = CASE WHEN ended_at IS NULL THEN 'open' ELSE 'purged' END,
    evidence_origin = CASE
        WHEN fix_count = 0 THEN 'unknown'
        WHEN mock_fix_count = 0 THEN 'device'
        WHEN mock_fix_count = fix_count THEN 'mock'
        ELSE 'mixed'
    END;

DO $$ BEGIN
    ALTER TABLE walk_session ADD CONSTRAINT walk_session_state_check
        CHECK (state IN ('open', 'sealed', 'derived', 'purged'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE walk_session ADD CONSTRAINT walk_session_origin_check
        CHECK (evidence_origin IN ('device', 'mock', 'mixed', 'unknown'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE walk_fix ADD COLUMN IF NOT EXISTS client_seq INTEGER;
UPDATE walk_fix SET client_seq = seq WHERE client_seq IS NULL;
ALTER TABLE walk_fix ALTER COLUMN client_seq SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS walk_fix_client_seq_uidx
    ON walk_fix (session_id, client_seq);

ALTER TABLE walk_facts
    ADD COLUMN IF NOT EXISTS calculation_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS evidence_origin TEXT NOT NULL DEFAULT 'unknown';

UPDATE walk_facts f
SET record_version = 2,
    evidence_origin = s.evidence_origin
FROM walk_session s
WHERE s.id = f.session_id;

DO $$ BEGIN
    ALTER TABLE walk_facts ADD CONSTRAINT walk_facts_origin_check
        CHECK (evidence_origin IN ('device', 'mock', 'mixed', 'unknown'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS walk_motion_event (
    session_id       TEXT NOT NULL REFERENCES walk_session (id) ON DELETE CASCADE,
    event_index      INTEGER NOT NULL,
    type             TEXT NOT NULL CHECK (type IN ('stop')),
    started_at       TIMESTAMPTZ NOT NULL,
    ended_at         TIMESTAMPTZ NOT NULL,
    duration_s       INTEGER NOT NULL,
    location         GEOGRAPHY(Point, 4326) NOT NULL,
    route_offset_m   DOUBLE PRECISION NOT NULL,
    accuracy_p50_m   REAL,
    fix_count        INTEGER NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, event_index)
);
CREATE INDEX IF NOT EXISTS walk_motion_event_location_gix
    ON walk_motion_event USING GIST (location);
""",
    ),
    (
        "009_walk_encounter.sql",
        """
-- 동선 주변 시설 관측 — 기하값까지만. 판정("지나쳤다/봤다")은 소비자(app/scene)의 일.
-- 밴드 3개를 전부 저장하는 이유: 원좌표는 finish 에서 지워지므로, 판정 반지름을
-- 실측 후 정하려면 후보 반지름들의 답이 미리 계산돼 있어야 한다 (재계산 불가 보상).
-- 폐업·인허가 상태는 필터가 아니라 데이터다(place_active) — 관측층은 큐레이션하지 않는다.
CREATE TABLE IF NOT EXISTS walk_encounter (
    session_id       TEXT NOT NULL REFERENCES walk_session (id) ON DELETE CASCADE,
    event_index      INTEGER NOT NULL,
    facility_source  TEXT NOT NULL,
    facility_ref     TEXT NOT NULL,            -- 안정 키 (source, source_ref). facility.id 아님
    kind             TEXT NOT NULL,
    lat              DOUBLE PRECISION NOT NULL,  -- 시설 대표점 (공개 장소)
    lng              DOUBLE PRECISION NOT NULL,
    place_active     BOOLEAN,                  -- 의료 오버레이 상태. 비의료·미링크는 NULL
    as_of            DATE,
    min_lateral_m    DOUBLE PRECISION NOT NULL,
    offset_m         DOUBLE PRECISION NOT NULL,
    dwell_s_10m      INTEGER NOT NULL,
    dwell_s_30m      INTEGER NOT NULL,
    dwell_s_50m      INTEGER NOT NULL,
    pass_count       INTEGER NOT NULL,
    stop_overlap_10m BOOLEAN NOT NULL,
    stop_overlap_30m BOOLEAN NOT NULL,
    stop_overlap_50m BOOLEAN NOT NULL,
    stop_s_10m       INTEGER NOT NULL DEFAULT 0,
    accuracy_p50_m   REAL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, event_index)
);
CREATE INDEX IF NOT EXISTS walk_encounter_facility_idx
    ON walk_encounter (facility_source, facility_ref);
""",
    ),
    (
        "010_walk_encounter_occurrence.sql",
        """
-- 시설별 세션 합계(v1)를 연속 진입 occurrence(v2)로 바꾼다.
-- 기존 v1 행은 원좌표가 이미 삭제돼 분할할 수 없으므로 occurrence_version=1로 남긴다.
ALTER TABLE walk_encounter
    ADD COLUMN IF NOT EXISTS occurrence_version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS occurrence_index INTEGER,
    ADD COLUMN IF NOT EXISTS entered_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS exited_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS entry_observed BOOLEAN,
    ADD COLUMN IF NOT EXISTS exit_observed BOOLEAN,
    ADD COLUMN IF NOT EXISTS entered_offset_m DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS exited_offset_m DOUBLE PRECISION;

DO $$ BEGIN
    ALTER TABLE walk_encounter ADD CONSTRAINT walk_encounter_occurrence_version_check
        CHECK (occurrence_version >= 1);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE walk_encounter ADD CONSTRAINT walk_encounter_occurrence_v2_check
        CHECK (
            occurrence_version < 2 OR (
                occurrence_index IS NOT NULL AND occurrence_index >= 0
                AND entered_at IS NOT NULL AND exited_at IS NOT NULL
                AND entered_at <= exited_at
                AND entry_observed IS NOT NULL AND exit_observed IS NOT NULL
                AND entered_offset_m IS NOT NULL AND entered_offset_m >= 0
                AND exited_offset_m IS NOT NULL AND exited_offset_m >= entered_offset_m
                AND pass_count = 1
            )
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS walk_encounter_occurrence_uidx
    ON walk_encounter (session_id, facility_source, facility_ref, occurrence_index)
    WHERE occurrence_version >= 2;
""",
    ),
    (
        "011_anchor.sql",
        """
-- 점령 앵커 — 산책 게임의 고정 지점. 원천은 공공데이터(보안등 등) 좌표다.
--
-- **왜 원본을 다 담지 않는가**: 보안등 원본은 도심 최근접 이웃 중앙값이 12m 라
-- 판정 원이 통째로 겹친다. 육각 격자로 셀당 1개만 남긴 결과를 적재한다 —
-- 선별은 결정론이라 같은 원천 스냅샷이면 같은 앵커가 나온다 (scripts/load_anchors.py).
--
-- 이름을 두지 않는 이유: 앵커의 정체성은 장소명이 아니라 **점령한 주인**에서 온다.
-- 원천 48만 중 100m 안에 이름 붙일 시설이 있는 건 3.5% 뿐이라, 이름을 요구하면
-- 나머지 96.5% 를 버려야 한다. 익명 앵커가 정상이다.
CREATE TABLE IF NOT EXISTS anchor (
    id         BIGSERIAL PRIMARY KEY,
    cell       TEXT NOT NULL,                       -- 'anchor-hex:115:q:r' 선별 격자 셀
    source     TEXT NOT NULL,                       -- 'lamp' (전국보안등정보표준데이터)
    kind       TEXT NOT NULL,                       -- 한전주 | 전용주 | 통신주 | 건축물 | unknown
    location   geography(Point, 4326) NOT NULL,
    instt      TEXT,                                -- 제공기관 (커버리지 구멍 추적용)
    as_of      DATE,                                -- 원천 데이터기준일자
    UNIQUE (source, cell)
);
CREATE INDEX IF NOT EXISTS anchor_gix      ON anchor USING gist (location);
CREATE INDEX IF NOT EXISTS anchor_kind_idx ON anchor (kind);
""",
    ),
    (
        "011_walk_fix_chain.sql",
        """
-- pause/resume 경계를 원좌표와 함께 보존한다. 같은 세션의 두 chain 사이에는
-- 시간·거리가 가까워도 segment가 없다. 기존 클라이언트는 단일 chain(0)으로 읽는다.
ALTER TABLE walk_fix
    ADD COLUMN IF NOT EXISTS chain_index INTEGER NOT NULL DEFAULT 0;

DO $$ BEGIN
    ALTER TABLE walk_fix
        ADD CONSTRAINT walk_fix_chain_index_nonnegative CHECK (chain_index >= 0);
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
""",
    ),
)


def upgrade() -> None:
    # 드라이버 커서에 직접 넣는다. SQLAlchemy 경로(op.execute / exec_driver_sql)는 빈
    # 파라미터를 함께 넘기고, 그러면 psycopg 가 SQL 안의 `%` 를 자리표시자로 읽어
    # 011_anchor 주석의 `3.5%` 에서 죽는다. 원본을 한 글자도 안 바꾸려면 이 경로여야 한다.
    # 파일 하나에 든 여러 문장을 한 번에 보내는 것도 이 경로에서만 된다.
    raw = op.get_bind().connection.driver_connection
    for name, sql in SOURCES:
        try:
            with raw.cursor() as cursor:
                cursor.execute(sql)
        except Exception as exc:
            raise RuntimeError(f"baseline 실패: {name}") from exc


def downgrade() -> None:
    raise NotImplementedError("baseline 아래는 빈 데이터베이스다")
