# 테스트 재점검 — 지도와 진행

구조 재편(결정 #67)이 끝났다. 그 다섯 PR 은 전부 **"테스트 본문 수정 0"** 을 완료 조건으로
삼았으므로, 테스트는 새 구조를 한 번도 따라오지 못한 채 import 경로만 갱신됐다. 이 문서는
그 격차를 재고 pass 별로 좁힌 기록이다.

한 번에 다 돌리면 꼼꼼해지지 않는다. 나눠서, 각 pass 마다 세 가지를 묻는다.

    이 테스트가 무엇을 지키나
    어디 있어야 하나
    **무엇을 못 보나**          ← 이번 구조 시리즈에서 네 번 물린 질문이다

## 규모 (2026-08-27)

397 개 / 49 파일. 디렉토리별로는 `walk` 129 · `discovery` 102 · `facility` 60 ·
`place` 31 · `providers` 32 · `api` 14 · `usage` 9 · 최상위 20.

## 자리 불일치 — 디렉토리 이름이 옛 구조의 화석이다

| 디렉토리 | 실제 검증 대상 | 처분 |
|---|---|---|
| `search/` → `discovery/` | import 1위가 `app.discovery`(38건). `search` 라는 패키지는 없다 | **Pass 1 완료** |
| `walk/` | walk 7파일 + **territory 6** + scene 1 — 코드는 셋으로 갈랐는데 테스트는 한 방 | Pass 2 |
| `facility/` | `geo`(hours·pet_axes·icons) + `ingest` + `place` 혼재. `facility` 는 #65 가 내부 용어로 격하한 어휘 | Pass 3 |
| `place/` `providers/` `usage/` `api/` | 대상과 대체로 일치 | Pass 4 |

목표는 `app/` 패키지를 그대로 비추는 트리다. 그래야 "이 테스트 어디 두지"에 구조가 답한다 —
결정 #67 이 코드에 대해 세운 것과 같은 기준이다.

## 커버리지 공백

직접 import 가 없는 모듈 24개를 세었으나, TestClient·함수 호출 경유를 추적하니 대부분
간접 검증이었다. **산책 업로드는 공백이 아니다** — `test_walk_store`(멱등) ·
`test_walk_bundle`(변환) · Android `WalkSessionExporterTest` 셋이 분담하고 그 분담을
docstring 이 적어놨다.

진짜로 아무도 안 보는 것:

| 대상 | 무엇이 안 지켜지나 | 배정 |
|---|---|---|
| `GET /places` (legacy) | 응답 계약 | Pass 4 |
| `/anchor/search` | `truncated` 경계 | Pass 3 |
| `providers.naver` · `kakao` | 파싱·인증 헤더. fake 경유만 있다 (tmap 은 truthfulness 가 커버) | Pass 4 |
| `providers.registry.build` | 키 유무별 제공사 선택 | Pass 4 |
| `journey.handoff` | 딥링크 생성 | Pass 4 |
| `usage.http` | `UsageDenied` → HTTP 매핑. **gate 는 촘촘한데 오류 매핑층이 0 이다** | Pass 4 |
| `core.clock` | `FixedClock` 결정론 계약 | Pass 4 |

## Pass 진행

- [x] **Pass 0** — 지도 (이 문서)
- [x] **Pass 1** — `search/` → `discovery/`. 아래 참고
- [ ] **Pass 2** — `walk/` 를 walk·scene·territory 로 가른다
- [ ] **Pass 3** — `facility/` 해체 + `place/` 정합, `/anchor` 공백
- [ ] **Pass 4** — providers·usage·api 정합 + 남은 공백 전부

### Pass 1 결과

`tests/search/` → `tests/discovery/`. 함께 옮긴 것:

    test_personas.py        → tests/profile/     검증 대상이 profile.source · journey.advice
    test_facility_ranking.py → tests/facility/    검증 대상이 api.facility · ingest

**테스트 품질 자체는 깨끗했다.** 비공개 심볼을 찌르는 곳 0, `Companion = str` 시절 가정
잔재 0, `inspect.signature` 세 곳은 전부 의도적 경계 고정이다(계획을 나눈 목적이 "엔진이
남의 축을 못 본다"이므로 시그니처가 곧 계약).

`refine.labels` 만 직접 테스트가 없었는데, `diff` 와 `features/hospital/actions` 가
문장 전체를 비교하므로 간접으로는 덮여 있다. 다만 두 소비자가 대표값 하나씩만 쓰기 때문에
**m/km 경계는 아무도 안 본다** — `test_labels.py` 로 그 경계만 고정했다.

`tests/search` 문자열 참조 3건(`.github/workflows/ci.yml` 주석 포함)도 갱신했다. pytest 가
못 보는 자리라 grep 으로만 잡힌다 — 구조 PR 에서 두 번 물린 것과 같은 종류다.
