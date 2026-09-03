---
status: parked
implementation: none
last_verified: 2026-09-02
depends-on:
  - contracts/walk-record.md
  - explorations/walk/session-continuity-and-dwell.md
---
# 속도색 산책 동선 — 방향은 GO, 구현은 보류

산책 중 지도에 표시되는 동선을 단일 색 선이 아니라 이동 속도에 따라 다른 색으로 표현하는
방안을 검토했다. 목적은 속도를 평가하거나 경쟁시키는 것이 아니라, 사용자가 자기 산책의 흐름을
게임 화면처럼 직관적으로 느끼게 하는 것이다.

동선은 전체적으로 하나의 싸인펜 자국처럼 보여야 한다. 천천히 탐색한 구간, 편안하게 걸은 구간,
신나게 이동한 구간이 은은하게 구분되되 지도와 현재 위치를 읽는 데 방해가 되어서는 안 된다.

## 검토한 표현

1. 순간 속도를 연속 그라데이션으로 표시
2. 속도를 세 단계로 나누어 구간별 색상 표시
3. 속도에 따라 선 굵기 변경
4. 점 또는 잉크 밀도로 속도 표현
5. 최근 구간에만 속도색 적용

연속 그라데이션은 정보량은 많지만 GPS 속도 노이즈까지 드러나 경로가 지나치게 조각나 보일 수
있다. 선 굵기나 잉크 밀도 방식은 싸인펜 콘셉트에는 어울리지만 지도 오버레이 수와 렌더링 비용을
통제하기 어렵다.

첫 후보는 **보정된 세 단계 속도색**으로 둔다.

## 지금 내린 결정

### 표현

- 경로선 색상은 속도 세 단계를 나타낸다.
- 단계 이름은 `천천히 탐색`, `편안한 산책`, `신나는 이동`처럼 우열이 없는 말로 정한다.
- 연속 무지개색이나 빨강·금색처럼 위험·보상을 암시하는 색은 피한다.
- 세 색은 하나의 잉크 계열처럼 보이도록 밝기와 존재감을 비슷하게 맞춘다.
- 확정 전 현재 구간은 중립색 또는 흐린 색으로 표시하는 안을 dev 프로토타입에서 비교한다.

한 선에 의미를 모두 접지 않는다.

- 경로선 색상: 이동 속도
- 별도의 부드러운 번짐 영역: 한 산책 안의 체류
- 여러 산책의 반복 방문: Spatial Diary/Cellophane 레이어

색상·진하기·중첩을 한 선에 모두 넣으면 사용자가 어두운 이유를 구분할 수 없다. 이 분리는
[`session-continuity-and-dwell`](session-continuity-and-dwell.md)이 `walks`·`occupancy`·dwell을
하나의 진함으로 섞지 않는 방향과도 맞는다.

### 속도 판정 후보

```text
Location.speed
  ↓ speed accuracy 검사
EWMA 약 5초
  ↓
천천히 탐색 / 편안한 산책 / 신나는 이동
  ↓ hysteresis + 확정 조건
색상 파트
```

- 원시 순간 속도를 바로 사용하지 않고 EWMA로 평활화한다.
- 단계 진입과 이탈 문턱을 다르게 두는 hysteresis를 적용한다.
- 같은 단계가 일정 시간과 거리 이상 유지된 뒤 파트로 확정한다.
- 정확한 속도 문턱과 확정 시간·거리는 실제 산책 데이터 없이 고정하지 않는다.
- `5초 AND 10m` 같은 단일 규칙은 느린 구간에서 20~30초 지연을 만들 수 있다. 단계별로 서로
  다른 조건을 쓰거나, 최근 구간을 잠시 미확정 버퍼로 두고 나중에 색을 확정하는 안을 비교한다.

Android `Location.speed`는 GNSS Doppler 등을 사용할 때 좌표 차분보다 정확할 수 있지만, 값의
유효성과 별도의 speed accuracy를 함께 봐야 한다. 현재 연구용 Android 사본의 `LocationSample`에는
순간 speed가 있으나 Room `RecordedFix`와 서버 계약에는 speed와 speed accuracy가 모두 영속되지
않는다. 첫 검증은 이 계약을 넓히지 않는 로컬 UX다.

### 렌더링 후보

NAVER Maps는 여러 색의 경로에 여러 `PathOverlay`를 두는 것보다
[`MultipartPathOverlay`](https://navermaps.github.io/android-map-sdk/reference/com/naver/maps/map/overlay/MultipartPathOverlay.html)를
사용하는 편이 효율적이라고 설명한다. 이를 첫 구현 후보로 둔다.

다만 오버레이 객체 하나를 재사용하는 것만으로 충분하지 않다. 1.5초마다 최대 5,000개 좌표와
색상 파트 전체를 새 리스트로 만들면 O(n) 재할당은 남는다. 구현한다면 다음 방어선을 함께 둔다.

- 오버레이 객체 유지
- 지도 화면 갱신 최대 1Hz
- 현재 활성 파트만 자주 변경하고 과거 파트는 일정 시점에 고정
- 오래된 표시 경로는 필요하면 Douglas–Peucker 방식으로 단순화
- 표시용 파트 수 256~512개를 최초 방어선으로 검토하고 프로파일링으로 확정
- 30분·60분·120분 fixture와 저사양 Android에서 프레임 드롭·GC 측정

현재 연구용 Android 사본은 trail이 바뀔 때마다 `PolylineOverlay`를 제거하고 전체 좌표로 다시
만든다. 속도색 구현 전에 이 전체 재생성 경로부터 분리해야 한다.

## 시스템 경계

첫 버전의 후보 범위는 운영 Android 원본인 `SAJOYO/DAENGS_APP`의 산책 중 로컬 UX다.

- 산책 중 위치를 서버로 스트리밍하지 않는다.
- 속도색 계산과 지도 표시는 기기 안에서 끝난다.
- 백엔드·네트워크·DB 부하는 추가하지 않는다.
- 이 저장소에서는 dev 시각화와 fixture로 감각·성능 근거를 먼저 만든 뒤 채택할 것만 승격한다.
- 운영 백엔드 원본인 `SAJOYO/DAENGS_dev` 계약은 첫 검증에서 바꾸지 않는다.

다른 기기 복원, 공유 일기, 위치별 속도색 리플레이가 실제 요구로 확인될 때만 백엔드를 다시 본다.
그때도 raw 좌표를 장기 보관하기보다 다음과 같은 압축 파생물을 우선 검토한다.

```text
SpeedBandPath
- encoded polyline
- 구간별 speed_band
- 알고리즘 버전
- confidence / unknown 구간
```

현재 서버는 원좌표 purge 뒤 속도 분위수와 좌표 없는 속도 곡선만 남기므로, 어느 위치가 어떤
색이었는지는 사후 재구성할 수 없다. 그것은 첫 버전에서 의도적으로 요구하지 않는다.

### 2026-09-03 후속 실험

[`walk-diary-route`](walk-diary-route.md) Lab은 단일 세션 선의 공간 보호·단순화와 함께
edge별 세 단계 색이 얼마나 남는지 보기 위해 **세션 내부 상대 분위수**를 임시로 표시한다.
이는 이 문서의 제품 속도 문턱·EWMA·hysteresis를 채택한 구현이 아니다. 저장 후보의 형태와
지도 가독성을 보는 실험일 뿐이며, 실제 속도 의미와 Android 렌더링 보류 조건은 그대로다.

## 지금 구현하지 않는 이유

아이디어 방향은 **GO**지만 현재 바로 개발하지 않는다.

1. 우선순위는 실제 산책 도중의 기본 가로형 UI·UX와 상호작용 구조를 확정하는 것이다.
2. 속도 단계 문턱은 실제 산책 데이터와 기기별 GPS 노이즈를 봐야 정할 수 있다.
3. 색 전환과 별도 체류 번짐이 함께 보일 때의 감각을 dev 프로토타입에서 먼저 확인해야 한다.
4. 현재 지도 렌더러의 전체 오버레이·좌표 재생성부터 고쳐야 장시간 비용을 제대로 잴 수 있다.
5. 공유·리플레이 수요가 없는 단계에서 영속 계약을 넓힐 이유가 없다.

## 다시 여는 조건

- 기본 산책 화면 UI가 확정됨
- dev 프로토타입에서 세 단계 색과 체류 레이어가 서로 다른 의미로 읽힘
- 실제 산책 샘플로 EWMA·hysteresis·확정 조건을 조정할 수 있음
- 장시간 fixture와 저사양 기기 프로파일링 계획이 준비됨
- 기능 플래그 뒤에서 사용자 반응을 검증할 수 있음

이 조건이 갖춰지면 `DAENGS_APP` 로컬 feature로 먼저 검증한다. 공유·복원·리플레이 요구가
확인되기 전까지 `DAENGS_dev` 저장 계약은 열지 않는다.

## 외부 근거

- [NAVER Maps `MultipartPathOverlay`](https://navermaps.github.io/android-map-sdk/reference/com/naver/maps/map/overlay/MultipartPathOverlay.html)
- [Android `Location` 속도 및 속도 정확도](https://developer.android.com/reference/android/location/Location)
