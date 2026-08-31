# Cellophane 실기기 로컬 replay

PR4의 목적은 제품 저장을 시작하는 것이 아니라, PR1~3의 동일 경로를 실제 Android export에
대어 canonical PaintSpec을 고를 측정 근거를 만드는 것이다.

```text
WalkSessionExporter format 1
→ compute_facts()
→ paint_sheet()
→ Cellophane GeoJSON
→ 기존 /cellophane viewer
```

## 실행

원좌표는 레포 밖의 개발 artifact다. `walk_bundle pull`의 `--out`과 replay `--out` 모두 레포
밖을 사용하고 관찰이 끝나면 삭제한다.

```powershell
uv run python -m scripts.verify.walk_bundle pull --out C:\dev\walks --delete

uv run python -m scripts.spikes.territory_paint.cellophane_replay `
  --input C:\dev\walks\device\walk-....json `
  --out C:\dev\walks\cellophane\walk-...
```

출력은 위치가 없는 `report.json` 하나와 위치가 포함된 GeoJSON 네 개다.

```text
cellophane-r8-step.geojson
cellophane-r8-smooth.geojson
cellophane-r15-step.geojson
cellophane-r15-smooth.geojson
```

`DAENGS_DEV_CONSOLE=true`로 서버를 띄우고 `/cellophane`의 `JSON 열기`에서 각 파일을 비교한다.
외부 basemap 요청은 없다.

## 읽는 값

- `cell_count`, `payload_bytes`: 저장·전송량
- `paint_ms`, `serialize_ms`: 로컬 비교용 실행 시간. 벤치마크 보장은 아니다.
- `support_area_m2`: 셀 중심 위도에서 계산한 칠해진 육각형 면적 합
- `local_occupancy_p50_s`, `local_occupancy_max_s`: canonical segment 중점을 최대 200개 골라
  반경 `local_read_m` 안의 셀 질량을 적분한 값
- `top10_mass_share`: 가장 큰 열 셀이 전체 질량에서 차지하는 비율
- `gap_brush_overlap_count`: gap을 잇는 segment는 없지만 양 끝 붓 support가 겹쳐 화면에서
  이어져 보일 수 있는 gap 수
- `mass_error_s`: 언제나 0에 가까워야 하는 계산 불변식

격자 비교에서 가장 진한 셀 하나를 정답으로 읽지 않는다. 격자가 달라지면 같은 질량이 다른
개수의 셀로 나뉘므로 국소 적분과 집중도를 함께 본다.

## privacy와 결과 환원

CLI는 입력·출력을 레포 안에 두는 것을 거부하고 기존 출력 폴더도 덮지 않는다. `report.json`은
fix, 좌표, q/r, cell id를 포함하지 않지만 GeoJSON 네 개는 정확한 경로를 포함한다. 모두 관찰
후 삭제 대상이다.

실기기에서 발견한 실패는 원본을 커밋하지 않는다.

```text
실제 현상 관찰 → 최소 합성 fixture → 회귀 테스트 → 실기기 artifact 삭제
```

PR5로 넘어가는 조건은 실제 산책에서 네 후보를 비교해 canonical radius/profile을 선택할
근거가 생기는 것이다. 그 전에는 DB migration이나 Android overlay를 만들지 않는다.

## Android Studio AVD 관통 결과 (2026-08-31)

Pixel 8 AVD에서 `walk_emulator_drive`의 58점 경로를 실제 Fused Location → foreground
service → Room → `WalkSessionExporter`로 통과시켰다. Fused Location이 시작·resume 때 점을
추가로 내어 export는 62 fix였고, 62개 모두 수용되어 60 segment와 명시적 chain 2개가 됐다.
네 후보 모두 `source_segment_s=295.181`을 보존했다.

| 후보 | 셀 | payload | paint | support | local p50 | top10 |
|---|---:|---:|---:|---:|---:|---:|
| r8-step | 170 | 88,173 B | 5.40 ms | 17,793 m² | 34.57 s | 20.73% |
| r8-smooth | 170 | 90,165 B | 5.71 ms | 17,793 m² | 34.86 s | 19.89% |
| r15-step | 37 | 20,846 B | 2.78 ms | 13,614 m² | 35.11 s | 44.96% |
| r15-smooth | 37 | 21,423 B | 2.85 ms | 13,614 m² | 35.23 s | 44.61% |

이 측정은 **실기기 GPS 지터 근거가 아니다.** 다만 Android 수집 경계를 실제로 통과해 PR4
adapter와 viewer가 wire format 그대로 작동함을 확인한다. 여기서 AVD `adb emu geo fix`가
`LocationCompat.isMock=false`로 들어오는 문제도 발견했다. Android는 이제 플랫폼 표식뿐 아니라
에뮬레이터 build identity도 mock 근거로 사용하고, 검증 스크립트는 새 export가 전부 mock인지
끝에서 확인한다. 수정 APK를 다시 설치한 짧은 foreground-service 산책에서 export fix 3/3이
`is_mock=true`로 확인됐다. 가상 산책이 서버의 device evidence로 섞이는 것을 막는 회귀다.
