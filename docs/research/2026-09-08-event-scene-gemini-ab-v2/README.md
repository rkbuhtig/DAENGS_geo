# 실제 모델의 사건별 / 묶음 구성 비교

본문 작성 전 구성만 비교한다. 아래 문구는 모델 원문이며 구조 통과가 의미 승인은 아니다.
거부된 출력은 진단용이다. 반환 시각과 구성은 정상 장면이나 지도 표시 데이터로 사용하지 않는다.

요청 시도 6 · 구조 통과 3 · 확인된 토큰 78646 · 사용량 미상 0

| 실행 | 상태 | 원문 제안 수 | 승인된 장면 수 |
| --- | --- | ---: | ---: |
| [movement-individual](movement-individual/planned_request.json) | accepted | 7 | 7 |
| [movement-grouped](movement-grouped/planned_request.json) | accepted | 3 | 3 |
| [actions-grouped](actions-grouped/planned_request.json) | rejected_or_failed | 3 | — |
| [actions-individual](actions-individual/planned_request.json) | rejected_or_failed | 7 | — |
| [gap-individual](gap-individual/planned_request.json) | accepted | 2 | 2 |
| [gap-grouped](gap-grouped/planned_request.json) | rejected_or_failed | 3 | — |

## movement-individual

구조 상태: accepted

### 모델의 전체 이해

보호자와 반려견 두부가 도심의 상가 밀집 지역과 늘벗근린공원, 양재천 인근을 경유하며 산책을 진행했다.

대표 제목 초안: 도심 상가와 자연을 잇는 산책

### scene_01 · 상가 밀집 구간으로의 진입

시스템이 복원한 대표 사건 시각: 2026-09-07T09:08:00+09:00 → 2026-09-07T09:12:00+09:00

### scene_02 · 늘벗근린공원 인근으로의 이동

시스템이 복원한 대표 사건 시각: 2026-09-07T09:13:00+09:00 → 2026-09-07T09:16:00+09:00

### scene_03 · 양재천 인근 구간 진입

시스템이 복원한 대표 사건 시각: 2026-09-07T09:17:00+09:00 → 2026-09-07T09:20:00+09:00

### scene_04 · 다시 상가 밀집 구간으로 복귀

시스템이 복원한 대표 사건 시각: 2026-09-07T09:21:00+09:00 → 2026-09-07T09:24:00+09:00

### scene_05 · 상가 밀집 지역에서 한적한 구간으로의 이동

시스템이 복원한 대표 사건 시각: 2026-09-07T09:25:00+09:00 → 2026-09-07T09:27:00+09:00

### scene_06 · 양재천과의 거리 변화

시스템이 복원한 대표 사건 시각: 2026-09-07T09:28:00+09:00 → 2026-09-07T09:33:00+09:00

### scene_07 · 산책 후반부의 환경 변화

시스템이 복원한 대표 사건 시각: 2026-09-07T09:34:00+09:00 → 2026-09-07T09:36:00+09:00

### 모델의 선택·맥락·생략 이유

- e00 (connection, None): 원본의 카드 비대상 연결 구간
- e01 (connection, None): 원본의 카드 비대상 연결 구간
- e02 (connection, None): 원본의 카드 비대상 연결 구간
- e03 (selected, scene_01): 산책의 시작점에서 주변 환경이 상가 밀집 지역으로 변화하는 지점이다.
- e04 (selected, scene_02): 상가 지역에서 공원 인근으로 환경이 전환되는 과정을 보여준다.
- e05 (selected, scene_03): 공원 인근에서 하천 인근으로 산책 공간의 성격이 변화했다.
- e06 (selected, scene_04): 하천 인근에서 다시 상가 지역으로 이동하며 경로의 다양성을 보여준다.
- e07 (selected, scene_05): 상가 밀집도 변화에 따른 공간적 특징의 차이를 보여준다.
- e08 (selected, scene_06): 하천과의 거리가 가까워졌다가 멀어지는 동선상의 변화를 기록한다.
- e09 (selected, scene_07): 하천 인근에서 상가가 적은 구간으로 이동하며 산책을 마무리하는 과정이다.
- e10 (connection, None): 원본의 카드 비대상 연결 구간

## movement-grouped

구조 상태: accepted

### 모델의 전체 이해

보호자와 반려견 두부가 도심 상가 밀집 지역에서 시작하여 늘벗근린공원과 양재천 주변을 순환하며 산책한 기록이다.

대표 제목 초안: 상가와 자연을 잇는 도심 산책

### scene_01 · 상가 밀집 지역에서 공원 인근으로의 환경 변화

시스템이 복원한 대표 사건 시각: 2026-09-07T09:08:00+09:00 → 2026-09-07T09:12:00+09:00

중심: e03

포함: e03, e04

맥락:

상업 시설이 많은 곳에서 공원이라는 녹지 공간으로 이동하는 흐름을 묶어 공간적 대비를 보여줌

### scene_02 · 양재천과 상가 지역의 교차

시스템이 복원한 대표 사건 시각: 2026-09-07T09:17:00+09:00 → 2026-09-07T09:20:00+09:00

중심: e05

포함: e05, e06

맥락: e04

하천 인근과 상가 지역을 오가는 산책의 리듬을 강조함

### scene_03 · 양재천 주변을 포함한 산책의 마무리

시스템이 복원한 대표 사건 시각: 2026-09-07T09:25:00+09:00 → 2026-09-07T09:27:00+09:00

중심: e07

포함: e07, e08, e09

맥락: e06

하천과의 거리가 변하는 구간을 포함하여 산책의 후반부 경로를 일관성 있게 정리함

### 모델의 선택·맥락·생략 이유

- e00 (connection, None): 원본의 카드 비대상 연결 구간
- e01 (connection, None): 원본의 카드 비대상 연결 구간
- e02 (connection, None): 원본의 카드 비대상 연결 구간
- e03 (selected, scene_01): 상업 시설이 많은 곳에서 공원이라는 녹지 공간으로 이동하는 흐름을 묶어 공간적 대비를 보여줌
- e04 (selected, scene_01): 상업 시설이 많은 곳에서 공원이라는 녹지 공간으로 이동하는 흐름을 묶어 공간적 대비를 보여줌
- e05 (selected, scene_02): 하천 인근과 상가 지역을 오가는 산책의 리듬을 강조함
- e06 (selected, scene_02): 하천 인근과 상가 지역을 오가는 산책의 리듬을 강조함
- e07 (selected, scene_03): 하천과의 거리가 변하는 구간을 포함하여 산책의 후반부 경로를 일관성 있게 정리함
- e08 (selected, scene_03): 하천과의 거리가 변하는 구간을 포함하여 산책의 후반부 경로를 일관성 있게 정리함
- e09 (selected, scene_03): 하천과의 거리가 변하는 구간을 포함하여 산책의 후반부 경로를 일관성 있게 정리함
- e10 (connection, None): 원본의 카드 비대상 연결 구간

## actions-grouped

구조 상태: rejected_or_failed

omissions must cover exactly unused eligible events

정상 내부 구성이 생성되지 않았다. 원문은 results.json과 해당 calls에 보존했다.

### 모델의 미승인 제안 원문

```json
{
  "understanding": {
    "summary": "보호자와 반려견 두부가 상가 밀집 지역에서 출발하여 늘벗근린공원과 양재천 인근을 경유하며 산책을 진행했다. 산책 중 두부는 특정 지점에서 냄새를 맡고 보호자와 함께 사진을 촬영하는 등 활발한 탐색 활동을 보였다.",
    "observed_flow": [
      {
        "text": "상가 밀집 지역에서 이동을 시작하여 두부가 냄새를 맡는 행동을 확인했다.",
        "candidate_ids": [
          "e03",
          "e04"
        ]
      },
      {
        "text": "늘벗근린공원 인근으로 이동하여 보호자와 두부가 함께 사진을 촬영했다.",
        "candidate_ids": [
          "e06",
          "e07"
        ]
      },
      {
        "text": "양재천 인근을 거쳐 다시 상가 지역과 한적한 구간을 오가며 산책을 마무리했다.",
        "candidate_ids": [
          "e09",
          "e10",
          "e11",
          "e12",
          "e13"
        ]
      }
    ],
    "interpretations": [
      {
        "text": "두부는 산책 경로상의 다양한 환경 변화에 반응하며 냄새를 맡는 등 적극적으로 주변을 탐색하고 있다.",
        "candidate_ids": [
          "e04",
          "e06",
          "e11"
        ]
      },
      {
        "text": "보호자는 두부와의 산책 중 특정 장소에서 사진을 남기며 기록을 이어가고 있다.",
        "candidate_ids": [
          "e07"
        ]
      }
    ],
    "open_questions": [
      "두부가 냄새를 맡는 행동이 특정 환경적 요인과 연관이 있는지 확인이 필요하다.",
      "산책 경로 중 상가 밀집 지역과 자연 구간의 비율이 두부의 활동성에 미치는 영향은 무엇인가?"
    ]
  },
  "title_draft": {
    "text": "두부와 함께한 상가와 자연을 잇는 산책",
    "candidate_ids": [
      "e04",
      "e07"
    ]
  },
  "scenes": [
    {
      "primary_candidate_id": "e04",
      "included_candidate_ids": [
        "e03",
        "e04"
      ],
      "context_candidate_ids": [
        "e00",
        "e01",
        "e02"
      ],
      "focus": "상가 밀집 지역에서의 탐색",
      "reason": "산책 초반 상가 지역으로 진입하며 두부가 냄새를 맡는 행동을 중심으로 환경 변화를 함께 기록한다."
    },
    {
      "primary_candidate_id": "e07",
      "included_candidate_ids": [
        "e06",
        "e07"
      ],
      "context_candidate_ids": [
        "e05"
      ],
      "focus": "늘벗근린공원 인근에서의 사진 촬영",
      "reason": "공원 인근으로 이동하여 보호자와 두부가 함께한 순간을 기록하고 환경적 특징 변화를 연결한다."
    },
    {
      "primary_candidate_id": "e09",
      "included_candidate_ids": [
        "e09",
        "e10",
        "e11",
        "e12",
        "e13"
      ],
      "context_candidate_ids": [
        "e08",
        "e14"
      ],
      "focus": "양재천과 주변 지역을 아우르는 산책의 흐름",
      "reason": "산책 후반부 양재천을 중심으로 주변 환경이 상가와 한적한 곳으로 교차되는 변화를 하나의 흐름으로 묶어 전달한다."
    }
  ],
  "omissions": [
    {
      "candidate_id": "e00",
      "code": "redundant",
      "reason": "산책 시작 전의 단순 연결 구간으로 별도의 장면 구성이 불필요함."
    },
    {
      "candidate_id": "e01",
      "code": "redundant",
      "reason": "산책 시작 전의 단순 연결 구간으로 별도의 장면 구성이 불필요함."
    },
    {
      "candidate_id": "e02",
      "code": "redundant",
      "reason": "산책 시작 전의 단순 연결 구간으로 별도의 장면 구성이 불필요함."
    },
    {
      "candidate_id": "e05",
      "code": "redundant",
      "reason": "장면 간 이동을 위한 단순 연결 구간임."
    },
    {
      "candidate_id": "e08",
      "code": "redundant",
      "reason": "장면 간 이동을 위한 단순 연결 구간임."
    },
    {
      "candidate_id": "e14",
      "code": "redundant",
      "reason": "산책 종료 후의 단순 연결 구간임."
    }
  ]
}
```

## actions-individual

구조 상태: rejected_or_failed

title must refer to selected scene events

정상 내부 구성이 생성되지 않았다. 원문은 results.json과 해당 calls에 보존했다.

### 모델의 미승인 제안 원문

```json
{
  "understanding": {
    "summary": "보호자와 반려견 두부가 상가 밀집 지역에서 시작해 늘벗근린공원 인근을 거쳐 양재천 주변을 산책하며 다양한 환경 변화를 경험한 기록입니다.",
    "observed_flow": [
      {
        "text": "상가 밀집 구간으로 진입하며 두부가 냄새를 맡는 행동을 보임",
        "candidate_ids": [
          "e03",
          "e04"
        ]
      },
      {
        "text": "늘벗근린공원 인근으로 이동하여 함께 사진을 촬영함",
        "candidate_ids": [
          "e06",
          "e07"
        ]
      },
      {
        "text": "양재천 인근과 상가 구간을 오가며 산책을 이어감",
        "candidate_ids": [
          "e09",
          "e10",
          "e11",
          "e12",
          "e13"
        ]
      }
    ],
    "interpretations": [
      {
        "text": "상가와 공원, 하천 등 다양한 환경을 경유하며 두부의 탐색 활동이 활발히 이루어짐",
        "candidate_ids": [
          "e04",
          "e07"
        ]
      }
    ],
    "open_questions": [
      "두부가 가장 흥미를 보인 특정 지점의 환경적 특징은 무엇인가?",
      "산책 중 사진 촬영이 이루어진 장소의 구체적인 분위기는 어떠했는가?"
    ]
  },
  "title_draft": {
    "text": "두부와 함께한 상가와 하천을 잇는 산책",
    "candidate_ids": [
      "e03",
      "e04",
      "e06",
      "e07",
      "e09",
      "e10",
      "e11",
      "e12",
      "e13"
    ]
  },
  "scenes": [
    {
      "candidate_id": "e03",
      "focus": "상가 밀집 구간으로의 진입",
      "reason": "산책 경로의 환경적 변화가 시작되는 지점임"
    },
    {
      "candidate_id": "e04",
      "focus": "두부의 탐색 행동",
      "reason": "사용자가 직접 남긴 반려견의 행동 기록임"
    },
    {
      "candidate_id": "e06",
      "focus": "늘벗근린공원 인근으로의 이동",
      "reason": "주변 환경이 상가에서 공원 인근으로 전환됨"
    },
    {
      "candidate_id": "e07",
      "focus": "기념 사진 촬영",
      "reason": "사용자가 직접 남긴 산책의 주요 활동임"
    },
    {
      "candidate_id": "e09",
      "focus": "양재천 인근으로의 진입",
      "reason": "주변 환경이 하천 인근으로 전환됨"
    },
    {
      "candidate_id": "e10",
      "focus": "상가 구간으로의 재진입",
      "reason": "환경적 특징이 다시 상가 밀집 지역으로 바뀜"
    },
    {
      "candidate_id": "e11",
      "focus": "상가 밀집도가 낮은 구간으로의 이동",
      "reason": "산책로의 환경적 특징 변화를 보여줌"
    }
  ],
  "omissions": [
    {
      "candidate_id": "e12",
      "code": "redundant",
      "reason": "양재천 인근의 환경 변화가 앞선 장면들과 유사하여 생략함"
    },
    {
      "candidate_id": "e13",
      "code": "redundant",
      "reason": "산책 후반부의 환경 변화가 앞선 기록들과 중복됨"
    }
  ]
}
```

## gap-individual

구조 상태: accepted

### 모델의 전체 이해

보호자와 반려견 두부가 상가 밀집 지역과 공원 인근을 포함한 다양한 환경을 산책하며 냄새 맡기 및 사진 촬영 등의 활동을 수행함.

대표 제목 초안: 두부와 함께한 상가와 공원 산책

### scene_01 · 상가 밀집 지역에서의 냄새 맡기

시스템이 복원한 대표 사건 시각: 2026-09-07T09:10:00+09:00 → 2026-09-07T09:10:00+09:00

### scene_02 · 늘벗근린공원 인근에서의 사진 촬영

시스템이 복원한 대표 사건 시각: 2026-09-07T09:15:00+09:00 → 2026-09-07T09:15:00+09:00

### 모델의 선택·맥락·생략 이유

- e00 (connection, None): 원본의 카드 비대상 연결 구간
- e01 (connection, None): 원본의 카드 비대상 연결 구간
- e02 (connection, None): 원본의 카드 비대상 연결 구간
- e03 (redundant, None): e04 장면의 배경 정보로 충분히 유추 가능함.
- e04 (selected, scene_01): 사용자의 직접적인 행동 기록이 포함된 핵심 장면임.
- e05 (connection, None): 원본의 카드 비대상 연결 구간
- e06 (redundant, None): e07 장면의 배경 정보로 충분히 유추 가능함.
- e07 (selected, scene_02): 산책 중 보호자와 반려견의 상호작용을 보여주는 중요한 기록임.
- e08 (connection, None): 원본의 카드 비대상 연결 구간
- e09 (connection, None): 원본의 카드 비대상 연결 구간
- e10 (low_signal, None): 단순 이동 경로의 변화로 별도의 장면 구성이 불필요함.
- e11 (low_signal, None): 단순 이동 경로의 변화로 별도의 장면 구성이 불필요함.
- e12 (connection, None): 원본의 카드 비대상 연결 구간
- e13 (low_signal, None): 단순 이동 경로의 변화로 별도의 장면 구성이 불필요함.
- e14 (low_signal, None): 단순 이동 경로의 변화로 별도의 장면 구성이 불필요함.
- e15 (low_signal, None): 단순 이동 경로의 변화로 별도의 장면 구성이 불필요함.
- e16 (connection, None): 원본의 카드 비대상 연결 구간
- e17 (low_signal, None): 산책 종료 시점의 단순 이동으로 장면 구성의 우선순위가 낮음.

## gap-grouped

구조 상태: rejected_or_failed

composition cannot join GPS chains

정상 내부 구성이 생성되지 않았다. 원문은 results.json과 해당 calls에 보존했다.

### 모델의 미승인 제안 원문

```json
{
  "understanding": {
    "summary": "보호자와 반려견 두부가 상가 밀집 지역과 공원 인근을 포함한 다양한 도시 환경을 산책하며 이동했다. 산책 중 두부는 특정 지점에서 냄새를 맡고, 보호자와 함께 사진을 남기는 등 상호작용을 보였다.",
    "observed_flow": [
      {
        "text": "상가 밀집 지역으로 진입하여 두부가 냄새를 맡는 행동을 보였다.",
        "candidate_ids": [
          "e03",
          "e04"
        ]
      },
      {
        "text": "늘벗근린공원 인근으로 이동하여 보호자와 두부가 함께 사진을 촬영했다.",
        "candidate_ids": [
          "e06",
          "e07"
        ]
      },
      {
        "text": "양재천과 독골근린공원 주변을 거쳐 다시 상가 밀집 지역으로 돌아오는 경로를 따라 산책을 이어갔다.",
        "candidate_ids": [
          "e10",
          "e11",
          "e13",
          "e14",
          "e15",
          "e17"
        ]
      }
    ],
    "interpretations": [
      {
        "text": "두부는 산책 중 익숙하거나 흥미로운 냄새를 탐색하며 주변 환경을 적극적으로 확인했다.",
        "candidate_ids": [
          "e04"
        ]
      },
      {
        "text": "보호자는 산책 중 특정 장소에서 반려견과의 추억을 기록하기 위해 사진을 남겼다.",
        "candidate_ids": [
          "e07"
        ]
      }
    ],
    "open_questions": [
      "두부가 냄새를 맡은 지점의 구체적인 환경적 특징은 무엇인가?",
      "산책 후반부에 다시 상가 밀집 지역으로 돌아온 이유는 무엇인가?"
    ]
  },
  "title_draft": {
    "text": "두부와 함께한 도시 산책: 상가와 공원을 잇는 기록",
    "candidate_ids": [
      "e04",
      "e07"
    ]
  },
  "scenes": [
    {
      "primary_candidate_id": "e04",
      "included_candidate_ids": [
        "e03",
        "e04"
      ],
      "context_candidate_ids": [
        "e00",
        "e01",
        "e02"
      ],
      "focus": "상가 밀집 지역에서의 탐색",
      "reason": "산책 초반부의 공간 변화와 두부의 냄새 맡기 행동을 연결하여 기록하기 위함."
    },
    {
      "primary_candidate_id": "e07",
      "included_candidate_ids": [
        "e06",
        "e07"
      ],
      "context_candidate_ids": [
        "e05"
      ],
      "focus": "늘벗근린공원에서의 사진 촬영",
      "reason": "공원 인근으로의 공간 이동과 보호자의 사진 촬영 행동을 함께 묶어 산책의 주요 장면으로 구성."
    },
    {
      "primary_candidate_id": "e10",
      "included_candidate_ids": [
        "e10",
        "e11",
        "e13",
        "e14",
        "e15",
        "e17"
      ],
      "context_candidate_ids": [
        "e08",
        "e09",
        "e12",
        "e16"
      ],
      "focus": "양재천과 공원을 아우르는 후반부 산책",
      "reason": "다양한 공간 변화가 연속적으로 일어나는 후반부 경로를 하나의 흐름으로 묶어 산책의 전체적인 이동을 보여줌."
    }
  ],
  "omissions": []
}
```
