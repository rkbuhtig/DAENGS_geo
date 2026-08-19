# 03. 병원/약국 찾기

## 두 진입점, 하나의 검색

| | 챗봇 진입 | 메뉴 진입 |
|---|---|---|
| 입력 | 자연어 ("지금 열린 야간 병원") | 필터 UI (반경·영업중·야간·병원/약국) |
| 위치 | 대화 시점 현위치 1회 | 지도 드래그 시 재검색 (계속 바뀜) |
| 출력 | 상위 몇 개 텍스트 + 지도 카드 | 지도 마커 전체 + 리스트 |
| LLM | 질의 파싱만 | **안 씀** |

**뒤는 같은 함수 하나.** 검색 로직을 두 벌 만들지 않는다.

```
search(lat, lng, radius_m, type[hospital|pharmacy], open_now, night, limit)
parse(text, ctx) → search 파라미터   (LLM, 실패 시 기본값 폴백)
```

## LLM의 역할과 금지

- 한다: 자연어 → 파라미터. `"지금 문 연 야간 병원"` → `{open_now: true, night: true, radius: default}`
- 한다: `results`를 받아 **요약 문장** 작성
- **안 한다: 병원 정보 생성.** 이름·거리·전화·주소는 `results`에서 그대로. 없는 병원을 만들어내면 사고.

## 챗봇 응답 스키마

세 필드는 **같은 `results` 하나에서 파생**된다. 텍스트·카드·지도가 어긋날 수 없게.

```jsonc
{
  "answer": "가장 가까운 야간 진료 병원은 OO동물병원(650m)입니다. ...",
  "results": [
    { "id", "name", "type", "lat", "lng", "distance_m",
      "open_now", "night", "phone", "address", "hours_today" }
  ],
  "map": {
    "preview_url": "정적 지도 이미지 (마커 포함)",
    "deeplink":    "daengs://map?lat=..&lng=..&type=hospital&filter=open,night&ids=a,b,c",
    "web_url":     "https://.../map?lat=..&lng=..&type=hospital&filter=open,night&ids=a,b,c"
  }
}
```

- `deeplink`/`web_url`은 **검색 조건 + 강조할 id**를 실는다. 결과 자체가 아님. 지도 화면이 열리면서 같은 `search`를 다시 쳐서 마커를 그린다 → 드래그·재검색으로 자연스럽게 이어짐
- 앱/웹 어디서 챗봇이 뜨든 프론트가 골라 쓴다

## 흐름

```
search() ─→ results 확정
         ├→ answer : results를 템플릿/LLM에 넣어 요약만 (수치·이름 재생성 금지)
         └→ map    : results 좌표로 서버가 조립
```

## 지도 위치 (클라이언트, 참고)

- 메뉴 진입: 지도가 주인공 → Android는 카카오/네이버 SDK **네이티브**
- 챗봇 진입: 대화가 주인공 → 정적 이미지 카드 + "지도에서 보기" = 메뉴 화면으로 **딥링크**(필터 채워진 채)
- 웹: JS SDK로 별도. 백엔드 API는 동일

## 저장소

- PostgreSQL + **PostGIS** (팀 pgvector와 같은 인스턴스, 확장만 추가)
- 벡터 검색 안 씀. 거리 + 필터.

## 진짜 난이도: 영업시간

공공데이터(지방행정 인허가 · 동물병원 업종)에는 좌표·상호·영업상태는 있어도 **영업시간이 없다.**
요구사항의 핵심이 "지금 열었나 / 야간에 갈 수 있나"이므로 여기가 작업량 대부분.
→ 데이터 확보 경로 미결. `06-open-questions.md` 참조.

## 데이터 파이프라인 (팀 Airflow에 편승)

수집 → 전처리 → 지오코딩 → PostGIS 적재. 임베딩 단계만 건너뛰는 분기.
