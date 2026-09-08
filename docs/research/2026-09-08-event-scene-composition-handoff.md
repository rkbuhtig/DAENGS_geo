# 미커밋 후보 골격을 이어받은 사건→장면 구성

2026-09-08. 기준은 Geo `c2f8922`와 `geo-llm-architecture` 워크트리에 이미 있던 미커밋 작업이다. 별도 브랜치의 구현을 새로 가져오거나 기존 작업을 초기화하지 않았다.

## 이어받은 상태

`candidates.py`, `selection_adapter.py`, `selection_demo.py`, `selection_prompts.py`, `test_diary_selection.py`와 기존 contracts/provider/runner/storage/verify_run 수정이 있었다. 저장된 3차 입력을 Evidence로 옮기고, 후보별 선택/생략·순간 핀·빈 장면·재개를 기존 골격에 연결한 상태였다. 이어받은 관련 테스트 27개가 통과했다.

단, 후보 한 개와 장면 한 개를 일대일로 묶고 장면이 다른 후보의 근거를 참조하면 거부했다. 이 부분이 새 설계의 변경 지점이었다. 편집 전 소스 복사본을 저장소 밖 `outputs/event-scene-handoff-before/`에 보존했다.

## 이번에 연결한 것

- 기존 `individual`을 보존하고 `grouped`를 추가했다. Candidate는 원본 사건 단위이고 SceneComposition은 대표/포함/맥락 사건 참조를 갖는 편집 단위다.
- 필수 행동은 포함 기록으로 남긴다. 한 카드에 여러 행동을 담아도 시점과 근거가 각각 유지된다. 포함 사건은 한 장면만 소유하고 맥락은 여러 장면에서 공유할 수 있다.
- 개요 시각은 대표 사건의 범위다. 사건들의 시간 범위를 합쳐 사진/냄새의 지속시간으로 쓰지 않는다. 위치는 기존 보존 입력의 한계에 따라 unresolved다.
- 다른 chain·GPS 공백을 가로지르는 구성, 중복 소유, 필수 행동의 맥락 전용 처리, 구성 밖 근거, 잘못된 예산 생략을 검사한다.
- 기존 순회·재검토·체크포인트·재생·사용자 편집을 사용한다. 작성 전에 구성표를 읽을 수 있고, 작성 요청·읽기 결과·검토본에 사건별 시각/출처/근거를 포함한다.
- 구성은 실행 중 고정한다. 작성/재검토가 원본 사건이나 구성 소유 관계를 바꾸지 않는다. 실제 의미 검증·동적 구성 변경·지도 어댑터·운영 API/DB는 후속이다.

프롬프트와 스키마가 바뀐 예전 미커밋 선택 run은 새 디렉터리로 시작해야 한다. 옛 출력이나 사용자 편집본을 변환해 덮어쓰지 않았다.

## 검증과 출력

```powershell
python -m pytest tests/spikes/diary_storyboard/test_diary_composition.py tests/spikes/diary_storyboard/test_diary_selection.py tests/spikes/diary_storyboard/test_diary_storyboard_skeleton.py tests/spikes/diary_storyboard/test_diary_claim_experiment.py -q
python -m ruff check scripts/spikes/diary_storyboard tests/spikes/diary_storyboard/test_diary_composition.py tests/spikes/diary_storyboard/test_diary_selection.py
```

대상 45개 통과(기존 27 + 신규 18), Ruff 통과. 가짜 provider와 임시 파일을 사용하며 실제 API/DB 호출은 없다. 두 행동을 한 카드에 담고도 10분·15분이 유지되는 사례, 빈 묶음, 공유 맥락, 잘못된 구성의 체크포인트 거부, 실패 재개, 정확한 요청 재생, 편집/숨김 보존을 포함한다. 구조 검사는 본문의 주장 사실성을 보증하지 않는다.

오프라인 시연은 이동만/행동 있음/GPS 단절의 세 조건에 각각 individual/grouped를 실행했다. 같은 사용 사건 7개를 7카드/3카드로 표현했다. 각 조건에서 원본 후보는 11/15/18개이며 비교 대상 밖 후보도 목록에 남는다. 가짜 모델의 시간순 최대 3사건 묶음은 **연결 검산용 fixture**다. 실제 LLM의 선택이나 품질 개선, 최적 장면 수가 아니다. 일부 전환을 맥락으로 공유하며 두 행동 기록은 보존했다.

저장소 밖 `outputs/event-scene-comparison-20260908/README.md`에 비교 입구를 만들었다. 6개 run의 고정 입력·구성·요청/응답·상태·verification을 남겼다. individual은 fixture 9호출, grouped는 5호출이며 실제 모델 호출은 0회다. 모두 검토 대기에서 끝났다. 재현 명령은 [실험 README](../../scripts/spikes/diary_storyboard/README.md)에 있다.

## 다음에 검증할 것

이제 같은 사건 입력으로 LLM이 사건별/묶음 구성안을 직접 제안하도록 비교할 수 있는 골격이 생겼다. 본문을 쓰기 전 선택·포함·맥락·생략을 비교한 뒤, 구성을 고정해 문장 작성을 비교한다. 대표 배경의 공존 관계 확장과 주장별 의미 대조는 아직 구현하지 않았다. 운영 이식이나 새 PR 생성은 이번 작업에서 하지 않았다.
