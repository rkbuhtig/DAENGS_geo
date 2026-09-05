# 장면 생성 규칙의 실데이터 이식

`app/features/storyboard/scenes.py`와 `selection.py`는 시뮬레이터 의존성이 없는
장면 builder/선택 함수다. GPS lab은 관측 nodes·기록·시간 범위를 만들어 이 함수를 부르고,
합성 결과에는 synthetic=true를 지정한다. 기존 다섯 fixture의 장면 ID는 유지한다.

DAENGS_dev의 `backend/src/daengs_walk`에 두 파일을 동일하게 이식했다. 운영 adapter는
기존 canonical GPS 계산의 segments/gaps와 서버 기록을 입력한다. 실데이터 builder의
기본값은 synthetic=false이고 start/end/entry:<id>는 app의 로컬 장면 ID에 대응한다.
시간·경로 범위, 선택 이유, 사실/출처, revision을 담는 v1 JSON 필드 계약은 그대로다.

HTTP 인증·DB 세대 관리·Place 환경 조회는 dev의 서비스 책임이며 geo lab 서버를 운영
중계 서버로 쓰지 않는다. 구현 및 운영 적용은 DAENGS_dev `docs/walk-storyboard-live.md`,
app 검토는 DAENGS_app `docs/walk-storyboard-live.md`를 참고한다.
