# 반려견 프로필 계약 + 가상 페르소나

프로필 원천은 **타 담당**. 이 레포는 소비자다. 아래 인터페이스만 계약으로 잡고, 저쪽 저장 방식은 관여하지 않는다.

## 인터페이스 (수신 형태 가정)

```
필수 ─────────────────────────────
dog_id, name
breed              혼합이면 [{breed, ratio}]
birth_date         → age는 서버가 계산
sex, neutered
weight_kg
size_class         small / medium / large   (품종 미상 대비)
profile_version    변경 감지용. 바뀌면 파생값 재계산

선택 (있으면 판정 정밀도 상승) ─────
brachycephalic     bool  ← 없으면 breed로 유추
health_flags       []    예: joint, heart, obesity, senior
activity_level     low / mid / high  (보호자 자기보고)
temperament        []    예: curious, timid, food_driven, reactive_to_dogs
walk_baseline      { avg_min, avg_km, usual_time }  ← 없으면 첫 2주 학습
```

## 가상 페르소나 3마리

판정 로직이 갈리는 **극단**으로 잡았다. 이 셋이 다 말이 되면 중간은 자동으로 된다.

### 1. 콩이 — 보더콜리 믹스 · 2세 · 18kg · 수컷 중성화
- activity high, temperament [curious, reactive_to_dogs], health_flags 없음
- 상한선 넉넉. 목표는 거리·신구역 탐험 위주
- 톤: 앞서 나가는 쪽 — "저기 안 가본 골목인데?"
- 리스크: 다른 개 반응성 → 산책 밀집 시간대 회피 제안

### 2. 두부 — 퍼그 · 5세 · 9kg(과체중) · 암컷 중성화
- brachycephalic true, health_flags [obesity], activity mid
- **여름 판정 기준점.** 26℃↑ 목표 축소, 28℃↑ "지금 나가지 마"
- 보상은 거리가 아니라 **꾸준함**(연속 일수, 시간대 준수)에 몰빵
- 톤: 느긋 + 앓는 소리 — 귀여움이 아니라 **실제 경고 채널**

### 3. 할매 — 말티즈 · 13세 · 3.2kg · 암컷
- health_flags [senior, joint], activity low, temperament [timid]
- **초과 페널티 기준점.** 권장량 넘기면 보상 감소 + 집 가자고 함
- 잦은 정지 = 정상. 정지 임계값이 다르다
- 짧은 산책 여러 번 > 한 번 긴 산책

## 페르소나에서 도출된 규칙

1. **하루 목표는 프로필 함수다.** 입력: 나이·체중·brachy·flags·기온 → 출력: 권장 시간/거리 범위. 고정값 없음
2. **정지 판정 임계값은 개마다 다르다.** 콩이 3분 정지 = 뭔가 있음, 할매 3분 정지 = 그냥 쉼
3. **톤은 temperament에서, 경고 강도는 health_flags에서.** 분리해야 귀여운 말투가 위험 경고를 묻지 않는다
