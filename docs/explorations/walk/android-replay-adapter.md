---
status: exploring
implementation: working-skeleton
---
# Walk trace Android replay adapter

> 후속 소비자 기록 (2026-09-04): APP의 `feat/walk-territory-lab`에 단일 chain JSON을 읽는
> debug 재생·접근 UX 실험이 구현됐다. [설계와 인수인계](../../research/2026-09-04-walk-territory-lab-handoff.md)에
> 지원 범위와 미완료 검증을 구분해 기록했다. 아래 어댑터의 범위와 Geo/APP 코드 소유권은 그대로다.

`walk-trace-scenario-v1`의 **observed capture**를 Android 쪽에서 반복 사용할 수 있는 형태로
바꾼다. 새 GPS 생성기나 제품 수집 경로가 아니라 Geo Lab과 Android 검증 사이의 얇은 어댑터다.

```text
walk-trace-scenario-v1
        ↓ 기존 truth → sensor/fault 실행
walk-trace-v1 observed capture
        ├─ android-replay.json  앱 내부 TraceLocationSource용 무손실 입력
        ├─ android-route.gpx    Android Studio Location용 좌표·시각 어댑터
        └─ adb emu geo fix      AVD Fused Location 관통용 실시간 좌표 주입
```

## 실행

원좌표 artifact가 생기므로 출력은 레포 밖의 빈 폴더를 준다. 기존 폴더를 덮지 않는다.

```powershell
uv run python -m scripts.sim.walk.android_replay `
  --spec scripts/sim/walk/examples/sniff-and-go.json `
  --out C:/dev/walk-replay/sniff-and-go
```

생성된 GPX는 Android Studio Emulator의 `Extended controls → Location → Routes`에서 불러온다.
실행 중인 AVD에 capture 간격을 지켜 직접 좌표를 보내려면 `--play`를 명시한다.

```powershell
uv run python -m scripts.sim.walk.android_replay `
  --spec scripts/sim/walk/examples/sniff-and-go.json `
  --out C:/dev/walk-replay/sniff-and-go-adb `
  --play --speed 10 --serial emulator-5554 --prime-wait 5
```

`--prime-wait 5`는 첫 좌표를 먼저 넣어 Fused의 과거 cached 위치를 밀어낸 뒤 5초 동안 산책
시작 버튼을 누를 시간을 준다. 그 뒤 첫 표본부터 다시 보내며 capture 시간축을 시작한다.

ADB 재생기는 재생 시작 monotonic clock에 각 capture offset/배속을 더한 절대
deadline까지만 기다린 뒤 `longitude`, `latitude` 순서로 `adb emu geo fix`를 호출한다.
그래야 이전 ADB 명령 실행 시간이 다음 표본 간격에 누적되지 않는다. 앱 시작·종료 버튼이나
서버 업로드는 제어하지 않는다. 그것은 이 좌표 source를 실제
`WalkTrackingService → Room → upload`에 통과시키는 APP 통합 하네스의 책임이다.

## `walk-location-replay-v1`

한 sample은 다음 capture 증거만 가진다.

- `captured_offset_ms`, `delay_from_previous_ms`: 원 시나리오 시작 기준 상대 시간
- `elapsed_realtime_offset_nanos`: Android consumer가 재생 시작 monotonic clock에 더할 offset
- 위도·경도, horizontal accuracy, mock 표식
- 원 `sample_id`, `client_seq`, `chain_index`: 결과 대조와 control event 조립용 provenance

소비자는 과거 `source_started_at`을 현재 기기 시각으로 그대로 넣지 않는다. 재생을 시작한 현재
wall clock과 monotonic clock을 각각 기준으로 offset을 더한다. 그래야 오래된 위치로 거부되지
않으면서 wall/monotonic 시간의 역할을 섞지 않는다.

누락 truth sample은 location sample을 만들지 않는다. 대신 다음 observed sample의
`delay_from_previous_ms`가 길어지므로 dropout이 시간축에 남는다. chain index가 바뀌는 지점은
`control_events[type=chain_break]`로 따로 낸다. 위치 source가 session lifecycle을 몰래 조종하지
않고 APP 하네스가 해당 시점에 pause/resume을 실행하게 하기 위해서다.

계약은 sample ID 고유성, capture offset 단조 증가, offset과 delay/monotonic 값의 일치,
chain transition과 control event의 정확한 대응, receipt 분모를 검증한다. 모든 위치는
`is_mock=true`다.

## transport별 손실 경계

| transport | 보존 | 표현하지 못하는 것 |
|---|---|---|
| replay JSON | 좌표·상대 시각·accuracy·mock·chain control | delivery는 의도적으로 제외 |
| GPX | 좌표·절대 시각, missing/chain별 `trkseg`; 나머지는 DAENGS extension | Android Studio가 extension accuracy/mock을 적용한다는 보장 없음 |
| ADB `geo fix` | 좌표·상대 도착 간격, dropout·position offset | accuracy, mock field, pause/resume, delivery |

GPX와 ADB가 표현하지 못하는 값을 표현했다고 간주하지 않는다. JSON receipt의
`adb_unrepresentable_fields`에 손실을 남긴다. chain control이 있으면 ADB 재생은 기본 실패한다.
좌표만 볼 목적이라면 `--allow-unapplied-controls`로 그 손실을 명시적으로 받아들일 수 있다.

delivery 지연·batch·역순·중복은 GPS가 캡처된 **뒤**의 문제다. 따라서 이 어댑터가 좌표 발생
순서를 바꾸지 않으며, 기존 `delivery.json`과 PR3 평가 영수증이 별도로 검증한다.

## 레포 경계

이번 구현은 다음을 하지 않는다.

- Geo Android 화면의 하드코딩 replay를 제품 산책 서비스 source로 교체
- DAENGS_APP의 debug file picker·Room·업로드 연결
- DAENGS_dev finalize 호출이나 conformance report 생성
- GPX를 실험 원본 계약으로 승격
- mock 산책을 운영 데이터로 업로드

다음 APP 단계는 `android-replay.json`을 debug 전용 `TraceLocationSource`가 읽고 실제 산책
서비스 주입점에서 선택하도록 만든다. Geo의 scenario/trace와 평가기는 그 APP 구현 없이도
독립 실행돼야 하고, APP fixture도 최종적으로 Geo checkout 없이 단독 회귀할 수 있어야 한다.
