# 산책 기록 계약 (outbound)

이 레포가 **주는** 것. [dog-profile.md](dog-profile.md) 가 "남이 주고 우리가 소비"라면 이건 그 반대다 —
우리가 수집한 사실을 남(케어 밸런스 · 서술 · 보행체크 · 수의사 리포트)이 소비한다.
소비자가 이 레포 안에 있을 수도 바깥 팀원일 수도 있다. 어느 쪽이든 **이 계약만 본다.**

근거: [결정 — 병원은 산책의 모드, 산책이 척추](../decisions/2026-08-22-walk-as-spine.md) 7절,
[연구 — 산책 데이터 신뢰도 등급](../research/2026-08-19-walk-data-evidence.md).

## 원칙

1. **사실만.** `walk-data-evidence.md` 의 "넣음" 등급만 필드가 된다. 시간 · 거리 · 속도 · 정지. 전부 폰 GPS 로 ±2~5%.
2. **의미 없음.** 목표 대비 · 보상 · 점수 · 레벨 · 트리거 · 권유 · 서술 — 이 계약에 없다. 그건 소비자가 자기 쪽에서 얹는다.
3. **텍스트 없음.** 사용자에게 보여줄 문장 필드가 없다. 문자열은 식별자뿐이다.
4. **버전.** `record_version` 으로 변경을 감지한다. 필드가 늘면 버전이 오른다.

코드: `app/features/walk/models.py`. 필드 집합과 금지 이름은 `tests/test_walk_contract.py` 가 고정한다 —
필드 하나를 더하면 테스트가 깨지고, 깨뜨리는 것이 **보이는 결정**이 된다.

## 형태

```
WalkFix      수신 원본 한 점. 앱이 배치로 올린다
  at            tz 필수
  lat, lng
  accuracy_m    있으면. 필터 재료
  is_mock       재생·가짜 위치 표식. Android DEVICE/MOCK 구분의 서버 짝 — 개발 재생이
                진짜 산책 사실처럼 쌓이지 않게 한다. 사실 필드가 아니라 표식이다

WalkSession  세션 하나
  id, dog_id
  started_at, ended_at     ended_at 없으면 진행 중
  fix_count

WalkFacts    세션이 끝난 뒤 코드가 계산한 사실. 이게 바깥에 나가는 것
  record_version
  session_id, dog_id
  started_at, ended_at
  duration_s
  distance_m               원 GPS 누적. 정지 중 지터 포함 — 참고값
  moving_distance_m        속도 임계 이하 구간을 0 으로 — **"거리"는 이것이다**
  moving_s
  stop_count, stop_s       "정지"까지만. 냄새 맡기로 단정하지 않는다 (evidence C절)
  avg_speed_mps            moving 기준
  fix_count
```

## 수집 API (2026-08-24)

```
POST /walk/sessions                시작. id 는 클라이언트 생성(UUID) — 오프라인 시작 + 멱등 재전송
POST /walk/sessions/{id}/fixes     배치 업로드 → 수신 계수만 응답. 판정·서술 없음 (계약 원칙)
POST /walk/sessions/{id}/finish    종료 → WalkFacts 확정. 멱등 — 확정된 사실은 재계산하지 않는다
GET  /walk/sessions/{id}           세션 + 사실
```

**fix 는 세션이 살아 있는 동안만 서버에 있다.** finish 가 사실을 계산하면 같은
트랜잭션에서 지운다. 삭제는 영구 방침이 아니라 아래 저장 정책이 서기 전의 안전
기본값이다 — 정책이 서면 절삭·보관기간과 함께 보관으로 바꿀 수 있다.

계산 정책은 Android `WalkCalculationPolicy` v1 미러 (`app/features/walk/facts.py`):
이동 임계 0.5m/s · 정지 최소 10초 · accuracy 50m 컷 · 200m 튐 단절. 값을 바꾸면
앱 미리보기와 서버 확정치가 어긋난다 — 양쪽을 같이 바꾸고 버전을 올린다.

## 예정 — 저장 정책이 선 뒤

- 궤적 · 재방문 · 구역 — evidence 는 "넣음"이지만 **궤적을 저장해야** 나온다. 시작·종료 좌표는 집 주소다.
  절삭 · 지연 저장 · 보관 기간([backlog](../backlog.md))이 먼저다. 그전까지 계약에 넣지 않는다
- 평소 대비 % — 가장 믿을 만한 지표지만 baseline 이 있어야 한다. 2~4주 뒤. 그때 `WalkBaseline` 로 별도
- 이용 과정의 데이터(어디서 뭘 찾았나) — 같은 이유로 저장 정책 뒤

## 안 주는 것 (다시 안 물으려고)

| | 왜 |
|---|---|
| 칼로리 | 걷기 MAPE 35%. 숫자로 내면 거짓말 |
| 걸음 수 | 폰은 사람 걸음. 소형견 보폭 3~4배 |
| 냄새 맡기 | 검증된 행동 분류 8개에 없음. 목걸이가 있어도 |
| 계단 · 육교 | TMAP 이 안 준다 — 288경로 0 ([조사](../research/2026-08-22-tmap-option-survey.md)) |
| 목표 대비 · 보상 · 권유 | 사실이 아니라 판정. 소비자의 일 |
| 서술 · 에피소드 | 옵션. 소비자의 일 |
