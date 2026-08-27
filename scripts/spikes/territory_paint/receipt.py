"""브리핑 + 배경 타일을 영수증 템플릿에 구워 실행 가능한 HTML 하나를 만든다.

    uv run python -m scripts.spikes.territory_paint.experience_scene \\
        --personas personas.json --cache-sheets sheets.pkl --out brief.json
    uv run python -m scripts.spikes.territory_paint.basemap \\
        --scenes brief.json --out basemap.json
    uv run python -m scripts.spikes.territory_paint.receipt \\
        --brief brief.json --basemap basemap.json --out receipt.html

## 무엇을 그리나

[evidence-layer](../../../docs/explorations/walk/evidence-layer.md) 원칙 1 의 **사람 쪽
renderer** 다. AI 는 같은 JSON 을 읽고 문장을 만들고, 이 화면은 같은 JSON 을 읽고 근거를
편다 — 사실은 하나고 그리는 방법만 둘이다.

위에서 아래로 넷.

    ① 문장        오늘 도착할 말 (푸시 초안)
    ② 근거        왜 그렇게 말했나 — 분자/분모·비교 기준·표본
    ③ 안 고른 것  왜 저 말은 안 했나 — 후보 순위와 탈락 사유
    ④ 지도        조건 칩으로 바꿔 보는 칠한 자리

**지도가 맨 마지막인 게 이 프레임이다.** 예전에는 지도가 주인공이고 문장이 곁다리였다.

## 규칙 하나

**화면의 모든 숫자는 JSON 에서 온다.** 페이지에서 다시 계산하지 않는다. 그래야 "화면에서
재밌으면 제품에서도 같은 숫자다" 가 성립하고, 판정(E4)이 실제 제품의 판정이 된다.

## 왜 레포에 있나

`layer_viewer` 와 같은 이유다 — 결론을 만드는 것이 렌더러인데 그게 커밋에 없으면 재현
사슬이 끊긴다. 제품 코드가 아니라 **연구 재현물**이고, 템플릿은 `lab/receipt.html` 이다.
"""

import argparse
import json
import os
import sys

TEMPLATE = os.path.join(os.path.dirname(__file__), "lab", "receipt.html")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", required=True, help="experience_scene 산출물")
    parser.add_argument("--basemap", required=True, help="basemap 산출물")
    parser.add_argument("--template", default=TEMPLATE)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    with open(args.template, encoding="utf-8") as handle:
        html = handle.read()
    for token in ("__BRIEF__", "__BASE__"):
        if token not in html:
            print(f"템플릿에 {token} 자리표시자가 없다: {args.template}")
            return 1

    with open(args.brief, encoding="utf-8") as handle:
        brief_raw = handle.read()
    with open(args.basemap, encoding="utf-8") as handle:
        base_raw = handle.read()

    html = html.replace("__BRIEF__", brief_raw).replace("__BASE__", base_raw)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(html)

    payload = json.loads(brief_raw)
    size = os.path.getsize(args.out) / 1024 / 1024
    print(f"장면 {len(payload['scenes'])}개 · 타일 {len(json.loads(base_raw)['tiles'])}장 "
          f"→ {args.out} ({size:.2f}MB)")
    for scene in payload["scenes"]:
        said = scene["briefing"]["chosen"]
        line = said["sentence"] if said else "— 말할 것 없음"
        others = len(scene["briefing"]["candidates"]) - (1 if said else 0)
        print(f"  {scene['persona']['id']}  \"{line}\"  (안 고른 것 {others})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
