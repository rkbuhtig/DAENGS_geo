---
status: adopted
decision: 86
adopted_at: 2026-09-07
---
# 공용 구현은 검토 도구·실험·테스트를 import하지 않는다

[결정 #67](2026-08-26-package-architecture.md)의 app 내부 계층·계약·DAG 규칙은 유지한다.
여기에 저장소 실행 경계를 추가한다. 0차 기준 `0cb7377`에서 `app/main.py`가 개발 모드에
`scripts.sim.walk.lab`을 연결하고 있었다. 기존 검사는 `from app.*`를 중심으로 보므로
이 역참조는 검사 범위 밖이었다.

## 소유권과 방향

| 위치 | 책임 |
|---|---|
| `app/` | 여러 실행 경로에서 함께 쓰는 구현·계약·기준 API |
| `tools/` | 사람이 열어 조작하는 검토 서버·화면과 그 전용 어댑터 |
| `scripts/sim/` | 재사용 가능한 합성 입력 생성기 |
| `scripts/verify/` | 여러 작업에서 재사용하는 관통 검증 |
| `scripts/spikes/<갈래>/` | 특정 기획·가설의 실험과 재현 장치 |
| `tests/` | 소유 기능별 검증. 루트에는 저장소 경계 검사 |

`tools`와 `scripts`는 `app`을 소비할 수 있고 도구·실험은 공용 `scripts/sim`을 재사용할
수 있다. **`app`은 저장소 최상위 `tools`, `scripts`, `tests`를 import하지 않는다.**
`app` 내부 계층은 기존 #67이 계속 검사한다. 이 새 규칙이 tools/scripts 사이의 모든
의존성이나 동적 실행을 허용·보장한다는 뜻은 아니다.

`app`에 있다는 사실은 운영 제품 채택을 뜻하지 않는다. Geo는 R&D 원본이며 실제 운영
소유권·승격 여부는 [승격 원장](../promotion-ledger.toml)과 DEV/APP의 채택 기록을 따른다.
이 결정 때문에 승격 기준 커밋을 바꾸지 않는다.

## 이행 중 예외는 한 모듈 연결만

| 출발 | 도착 | 남겨 둔 이유 | 제거 시점 |
|---|---|---|---|
| `app.main` | `scripts.sim.walk.lab` | 현재 dev_console의 GPS 검토 라우터. 검사 도입과 실행 입구 이동을 분리한다 | 3차 공용 API/검토 서버 입구 분리 |

`tests/test_repository_imports.py`의 `KNOWN_EDGES`는 이 모듈 쌍과 정확히 일치해야 한다.
새 출발 모듈·형제 도착 모듈은 예외가 아니다. 연결이 사라졌는데 예외가 남아 있어도
실패하고, 선언된 출발·도착 파일이 없어져도 실패한다. 기존 app 내부 검사의
`KNOWN_VIOLATIONS`와는 별도 목록이다.

## 검사 범위와 한계

app의 모든 Python 파일을 AST로 읽는다. `__init__.py`, 최상위 모듈, namespace package,
함수 내부·조건부 import도 포함하며 파일을 실제로 import하지 않는다.

- `import`, `from ... import ...`, 상대 import를 해석한다. `from scripts.sim.walk import lab`
  처럼 모듈을 가져오는 경우와 `from scripts.sim.walk.lab import router`처럼 심볼을 가져오는
  경우의 모듈 끝점을 구별한다.
- `importlib.import_module`과 직접 가져온 별칭, `__import__`의 문자열 리터럴 호출도 확인한다.
  인식한 동적 호출의 모듈명/상대 package가 계산식이면 조용히 건너뛰지 않고 실패한다.
- 임의의 `exec`, 함수 재할당·반사 호출까지 해석하는 보안 경계는 아니다. 새 로딩 기법이
  필요하면 이 검사와 소유권을 함께 검토한다.
- 저장소 경로가 비거나 잘못돼 아무것도 검사하지 않는 경우를 막는다. 임시 소스 트리에
  금지 import·예외 누락·파일 삭제를 넣어 같은 검사 함수가 실제로 실패하는지 검증한다.

## 테스트 이동의 보존 기준

일기 실험 테스트 세 파일은 `tests/spikes/diary_storyboard/`로 옮긴다. 두 파일은 내용 그대로,
스켈레톤 파일은 깊이가 바뀐 fixture 경로만 갱신한다. `tests/conftest.py` 하나를 계속 사용한다.

0차 기본 수집 1,481개 중 이동 대상은 17개다. 이번 PR에서는 이전 nodeid의 파일 경로를
새 경로로 대응시켜 **기존 모든 item이 유지되고 새 검사만 추가되는지** 확인한다. 이 숫자를
영구적인 테스트 개수 제한으로 넣지는 않는다. 미래의 기능 추가·삭제는 그 변경 근거로
검토하며, 파일 이동 PR에서는 nodeid 대응과 fixture 실행을 함께 확인한다.

날짜가 붙은 과거 연구 기록의 옛 실행 명령은 당시 사실로 남긴다. 현재 실행 명령은
[실험 README](../../scripts/spikes/diary_storyboard/README.md)와
[테스트 안내](../../tests/README.md)에서 찾는다.

이번에는 구조 검사와 테스트 분류만 바꾼다. 검토 서버·에셋 이전, 공용 게임의 독립,
문서 주제별 재배치와 seed 경로 변경은 후속 단계다.
