"""Reproducible synthetic route cases and SVG inspection of extracted HOW material."""

import argparse
import html
import json
import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

from app.features.walk.facts import compute_facts
from app.features.walk.models import WalkFix

from .how_materials import HowPolicy, HowSource, build_how

START = datetime(2026, 9, 8, 6, tzinfo=UTC)
ORIGIN = (37.0, 130.0)  # Synthetic geometry, not a real person's walk.
LABELS = {"local_stay": "국소 체류", "straight_run": "직선 이동",
          "turn": "방향 전환", "retrace": "되짚기"}


def route(name, waypoints, *, noise_m=0, step_s=5):
    """Waypoints are (elapsed seconds, east metres, north metres)."""
    samples = []
    for k, (a, b) in enumerate(pairwise(waypoints)):
        times = list(range(a[0], b[0], step_s))
        if k == len(waypoints) - 2:
            times.append(b[0])
        for t in times:
            ratio = (t - a[0]) / (b[0] - a[0])
            x, y = a[1] + ratio * (b[1] - a[1]), a[2] + ratio * (b[2] - a[2])
            x += noise_m * math.sin(t * 1.71)
            y += noise_m * math.cos(t * 1.19)
            samples.append(WalkFix(
                client_seq=len(samples), at=START + timedelta(seconds=t),
                lat=ORIGIN[0] + math.degrees(y / 6_371_000),
                lng=ORIGIN[1] + math.degrees(x / (6_371_000 * math.cos(math.radians(ORIGIN[0])))),
                accuracy_m=5, is_mock=True,
            ))
    return HowSource(session_id=name, dog_id="synthetic-dog", started_at=START,
                     ended_at=samples[-1].at, fixes=tuple(samples))


def scenarios():
    routes = {
        "straight": ("직선 + 작은 흔들림", [(0, 0, 0), (120, 120, 0)], 2),
        "right": ("뚜렷한 우회전", [(0, 0, 0), (90, 0, 90), (180, 90, 90)], 1),
        "left": ("뚜렷한 좌회전", [(0, 0, 0), (90, 0, 90), (180, -90, 90)], 1),
        "stay": ("제자리 관측 + 흔들림", [(0, 0, 0), (90, 0, 0)], 2),
        "pause_turn": ("머문 뒤 우회전", [(0, 0, 0), (90, 0, 90), (150, 0, 90),
                                     (240, 90, 90)], 1),
        "out_back": ("같은 구간 되짚기", [(0, 0, 0), (120, 0, 120), (200, 0, 40)], 1),
        "parallel": ("다른 쪽으로 돌아오기", [(0, 0, 0), (120, 0, 120), (155, 35, 120),
                                           (275, 35, 0)], 0),
        "shallow": ("완만한 방향 변화", [(0, 0, 0), (90, 0, 90), (180, 24, 180)], 0),
        "short": ("짧은 꺾임", [(0, 0, 0), (15, 0, 15), (30, 15, 15)], 0),
    }
    result = {name: {"label": label, "source": route(name, points, noise_m=noise)}
              for name, (label, points, noise) in routes.items()}
    gap = route("gap", [(0, 0, 0), (90, 0, 90), (210, 0, 90), (300, 90, 90)])
    gap = gap.model_copy(update={"fixes": tuple(
        p for p in gap.fixes if not 90 < (p.at - START).total_seconds() < 210
    )})
    result["gap"] = {"label": "모서리에서 GPS 공백", "source": gap}
    return result


def _svg(source, catalog):
    trail = compute_facts(source.session_id, source.dog_id, source.started_at,
                          source.ended_at, list(source.fixes)).trail
    points = [(p.lng, p.lat) for p in source.fixes]
    lo_x, hi_x = min(p[0] for p in points), max(p[0] for p in points)
    lo_y, hi_y = min(p[1] for p in points), max(p[1] for p in points)
    cos_lat = math.cos(math.radians(source.fixes[0].lat))
    dx, dy = (hi_x - lo_x) * cos_lat, hi_y - lo_y
    scale = 215 / max(dx, dy, math.degrees(40 / 6_371_000))

    def xy(lng, lat):
        return (160 + (lng - (lo_x + hi_x) / 2) * cos_lat * scale,
                140 - (lat - (lo_y + hi_y) / 2) * scale)

    paths = [('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 280" '
              'role="img" aria-label="관측 동선과 HOW 검출 지점">'),
             '<rect width="320" height="280" fill="#fafbf9"/>']
    marker = "arrow_" + catalog["source_sha256"][:8]
    paths.append(f'<defs><marker id="{marker}" viewBox="0 0 10 10" refX="9" refY="5" '
                 'markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
                 '<path d="M0,0 L10,5 L0,10 Z" fill="#23725c"/></marker></defs>')
    for seg in trail.segments:
        a, b = xy(seg.a.lng, seg.a.lat), xy(seg.b.lng, seg.b.lat)
        paths.append(f'<path d="M{a[0]:.2f},{a[1]:.2f} L{b[0]:.2f},{b[1]:.2f}" '
                     'fill="none" stroke="#acb4b1" stroke-width="2"/>')
    for run in catalog["shape_runs"]:
        coordinates = " ".join(f"{x:.2f},{y:.2f}" for x, y in
                               (xy(p["lng"], p["lat"]) for p in run["vertices"]))
        paths.append(f'<polyline points="{coordinates}" fill="none" stroke="#23725c" '
                     f'stroke-width="3" marker-end="url(#{marker})"/>')
    for m in catalog["materials"]:
        if m["kind"] == "straight_run":
            continue
        x, y = xy(m["anchor"]["lng"], m["anchor"]["lat"])
        text = {"local_stay": "머묾", "turn": "회전", "retrace": "되짚기"}[m["kind"]]
        color = {"local_stay": "#7e65ae", "turn": "#b65b24", "retrace": "#315dba"}[m["kind"]]
        offset = {"local_stay": -28, "turn": -10, "retrace": 24}[m["kind"]]
        paths.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="{color}"/>'
                     f'<text x="{x:.2f}" y="{y + offset:.2f}" text-anchor="middle" '
                     f'font-size="13" fill="{color}">{text}</text>')
    paths.append('</svg>')
    return "".join(paths)


def run(out, policy=None):
    policy = policy or HowPolicy()
    if out.exists() and any(out.iterdir()):
        raise ValueError("use an empty output directory")
    out.mkdir(parents=True, exist_ok=True)
    cards, report = [], {}
    for name, case in scenarios().items():
        source = case["source"]
        catalog = build_how(source, policy)
        folder = out / name
        folder.mkdir()
        for filename, value in (("source.json", source.model_dump(mode="json")),
                                ("how.json", catalog)):
            (folder / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        svg = _svg(source, catalog)
        (folder / "route.svg").write_text(svg, encoding="utf-8")
        counts = dict(Counter(m["kind"] for m in catalog["materials"]))
        report[name] = counts
        labels = " · ".join(f"{LABELS[k]} {v}" for k, v in counts.items()) or "검출 조각 없음"
        cards.append(f'<section><h2>{html.escape(case["label"])}</h2>{svg}'
                     f'<p>{labels}</p><details><summary>계산된 재료</summary><pre>'
                     f'{html.escape(json.dumps(catalog["materials"], ensure_ascii=False, indent=2))}'
                     '</pre></details></section>')
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    page = ('<!doctype html><html lang="ko"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>HOW 재료 실험</title><style>'
            'body{font:16px system-ui;background:#fafbf9;color:#22332c;margin:0;padding:28px}'
            'h1{font-size:24px}h2{font-size:18px;font-weight:500}'
            'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:28px}'
            'section{min-width:0;border-top:1px solid #ccd5d0;padding-top:8px}'
            'svg{width:100%;max-height:300px}pre{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}'
            'summary{cursor:pointer;padding:10px 0}p{line-height:1.6}'
            '</style><h1>HOW 재료 · 합성 동선 10조건</h1>'
            '<p>회색: 관측 동선 · 초록: 작은 흔들림을 줄인 형태 · 화살표: 진행 방향. '
            '국소 체류·방향 전환·되짚기를 표시했다. 모든 좌표는 합성값이다.</p>'
            '<p>룰베이스 계산 · WHERE/행동 의미 판정 없음 · LLM 호출 0회 · 임계값 실측 보정 전</p><main>'
            + "".join(cards) + '</main></html>')
    (out / "index.html").write_text(page, encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.out), ensure_ascii=False))


if __name__ == "__main__":
    main()
