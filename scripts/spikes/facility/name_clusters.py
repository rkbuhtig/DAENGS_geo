"""§8~9 측정: 이름 임베딩이 행 태깅을 대신할 수 있나 — 그리고 발견에는 쓸 만한가.

    uv run --with sentence-transformers --with scikit-learn \\
        python -m scripts.spikes.facility.name_clusters --kinds shopping cafe travel

## 무엇을 묻나

[결정 #70](../../../docs/decisions/2026-08-27-place-row-tags.md) 이 태그를 행에 붙이기로
했다. 33,611행을 사람이 다 볼 수는 없으니 자동화가 필요한데, 후보가 셋이었다:

    앵커 문장 → kNN    태그 정의문을 임베딩해 가까운 행에 그 태그를 붙인다
    씨앗 확장          예시 행 몇 개의 평균 벡터로 같은 것을 한다
    군집 → 사람 승인    어휘를 정하지 않고 군집을 먼저 보고 태그 후보를 발견한다

`bge-m3` 는 로컬 모델이라 외부 호출이 0 이다 — Usage Gate 와 무관하다.

## 왜 정규식과 대조하나

임베딩이 "된다" 는 것으로는 부족하다. **손으로 쓴 정규식보다 나은가**가 실제 질문이다.
정규식은 공짜이고 결정론이며 감사 가능하므로, 임베딩이 그것을 못 이기면 런타임에 둘 이유가
없다. 그래서 `--mode compare` 는 앵커·씨앗의 결과를 정규식 히트와 교차한다.

**정답 집합을 이 스크립트의 정규식으로 정의하므로 recall 은 순환이다.** precision 과
"정규식 밖에서 무엇을 찾았나" 만 읽어야 한다 — 측정 문서 §8-3 이 같은 경고를 단다.

## 왜 지점명을 떼고 군집하나

`탑텐 스타필드 하남점` 을 그대로 임베딩하면 `스타필드` 가 브랜드보다 강하게 묶여 군집이
"같은 건물" 이 된다. 그건 공간 관계이지 탐색 축이 아니다 (측정 §7 의 venue 문제).
`--mode discover` 는 venue 토큰을 떼고 중복 브랜드를 접은 뒤 고유명만 군집한다 —
`올리브영` 1,141행이 군집 크기를 지배하는 과적합도 같이 사라진다.
"""

import argparse
import asyncio
import collections
import re
import sys
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

MODEL = "BAAI/bge-m3"

# 지점·건물 토큰. 이름 끝에서부터 떼어낸다 — `탑텐 스타필드 하남점` → `탑텐`.
VENUE = re.compile(
    r"점$|아울렛|백화점|스타필드|프리미엄|플라자|몰$|롯데|신세계|현대|AK|NC|이마트|IFC"
    r"|캐슬|팝업스토어|타임빌라스|LF스퀘어|세이브존|갤러리아|명품관|에비뉴엘|더현대"
    r"|시티$|타운$|스퀘어|아이파크|엔터식스"
)
_TAX_FREE = re.compile(r"\[면세점\(TAX REFUND SHOP\)\]")


def normalize(name: str) -> str:
    """지점·건물 접미를 떼어 브랜드만 남긴다. 뗄 것이 없으면 원본."""
    toks = _TAX_FREE.sub("", name).strip().split()
    while len(toks) > 1 and VENUE.search(toks[-1]):
        toks.pop()
    return " ".join(toks) or name


@dataclass(frozen=True)
class Probe:
    """대조 한 건 — 앵커 문장 · 씨앗 행 · 정답 정규식."""

    label: str
    kind: str
    anchor: str
    seeds: tuple[str, ...]
    truth: re.Pattern[str]


PROBES = (
    Probe(
        label="beauty",
        kind="shopping",
        anchor="화장품과 미용용품을 파는 매장",
        seeds=("올리브영", "롭스", "아리따움"),
        truth=re.compile(
            r"올리브영|롭스|아리따움|이니스프리|네이처리퍼블릭|더페이스샵|미샤|에뛰드"
            r"|시코르|화장품|뷰티|코스메틱|랑콤|에스티로더|키엘|헤라|설화수|아모레|이솝",
            re.IGNORECASE,
        ),
    ),
    Probe(
        label="dog_primary",
        kind="cafe",
        anchor="반려견이 주인공인 곳. 강아지를 위한 애견 전용 공간",
        seeds=("애견카페 어썸", "내강아지애견카페", "개이득 애견카페"),
        truth=re.compile(r"애견|반려견|강아지|댕|퍼피|펫|독|도그|dog|pet|멍|개", re.IGNORECASE),
    ),
    Probe(
        label="dog_park",
        kind="travel",
        anchor="반려견이 뛰어놀 수 있는 놀이터와 운동장",
        seeds=("반려견놀이터", "애견운동장", "반려견 놀이터"),
        truth=re.compile(r"(반려견|애견|강아지|반려동물).{0,4}(놀이터|운동장|파크|공원)"),
    ),
)

# `#개주인공` 을 물었는데 캣카페가 나오는 것이 임베딩의 실패 모드다 (측정 §8-3).
CAT = re.compile(r"고양이|냥|캣|야옹|cat", re.IGNORECASE)


async def fetch(kinds: list[str]) -> list[tuple[str, str]]:
    """(kind, name). DB 를 읽기만 한다."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT kind, name FROM facility WHERE kind = ANY(:kinds) ORDER BY id"),
                {"kinds": kinds},
            )
            return [(row[0], row[1]) for row in result if not row[1].startswith("dev-")]
    finally:
        await engine.dispose()


def _encode(texts: list[str]):
    """모델 적재는 여기서만 — 레포 의존성 밖이라 import 도 함수 안에 둔다."""
    import torch
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL, device="cuda" if torch.cuda.is_available() else "cpu")
    model.max_seq_length = 64
    return model, model.encode(
        texts, batch_size=64, normalize_embeddings=True, convert_to_tensor=True
    ).cpu()


def compare(rows: list[tuple[str, str]]) -> None:
    """앵커 문장 · 씨앗 확장 · 정규식 셋을 같은 자로 잰다."""
    names = [name for _, name in rows]
    model, emb = _encode(names)
    for probe in PROBES:
        pool = [j for j, (kind, _) in enumerate(rows) if kind == probe.kind]
        if not pool:
            print(f"\n[{probe.label}] {probe.kind} 행이 없다")
            continue
        truth = {j for j in pool if probe.truth.search(names[j])}
        cats = {j for j in pool if CAT.search(names[j])}
        anchor_vec = model.encode(
            [probe.anchor], normalize_embeddings=True, convert_to_tensor=True
        )[0].cpu()
        seed_idx = [next((j for j in pool if seed in names[j]), None) for seed in probe.seeds]
        seed_idx = [j for j in seed_idx if j is not None]
        print(f"\n[{probe.label}] {probe.kind} {len(pool)}행 · 정규식 히트 {len(truth)}")
        queries = [("앵커문장", anchor_vec)]
        if seed_idx:
            centroid = emb[seed_idx].mean(0)
            queries.append(("씨앗확장", centroid / centroid.norm()))
        for label, query in queries:
            scores = emb @ query
            order = [j for j in scores.argsort(descending=True).tolist() if j in set(pool)]
            cells = []
            for k in (20, 50, 100, 200):
                top = order[:k]
                if not top:
                    continue
                hit = sum(1 for j in top if j in truth)
                cat = sum(1 for j in top if j in cats)
                cells.append(f"@{k} 정규식겹침 {100 * hit // len(top):3d}%  오탐(고양이) {cat:2d}")
            print(f"  {label:8s} " + " | ".join(cells))
        if seed_idx:
            centroid = emb[seed_idx].mean(0)
            centroid = centroid / centroid.norm()
            order = [
                j for j in (emb @ centroid).argsort(descending=True).tolist() if j in set(pool)
            ][:200]
            extra = [names[j] for j in order if j not in truth]
            print(f"  정규식 밖 {len(extra)}곳: {' · '.join(extra[:10])}")
            missed = [names[j] for j in truth if j not in set(order)]
            print(f"  임베딩이 놓친 정규식 히트 {len(missed)}곳: {' · '.join(missed[:10])}")


def discover(rows: list[tuple[str, str]], min_cluster_size: int) -> None:
    """어휘를 정하지 않고 군집을 본다 — 태그 후보 발견."""
    from sklearn.cluster import HDBSCAN

    per_kind: dict[str, collections.Counter] = {}
    for kind, name in rows:
        per_kind.setdefault(kind, collections.Counter())[normalize(name)] += 1

    for kind, counter in per_kind.items():
        uniq = list(counter)
        _, emb = _encode(uniq)
        labels = (
            HDBSCAN(min_cluster_size=min_cluster_size, cluster_selection_method="leaf")
            .fit(emb.numpy())
            .labels_
        )
        clusters: dict[int, list[int]] = collections.defaultdict(list)
        for j, label in enumerate(labels):
            if label >= 0:
                clusters[label].append(j)
        ranked = sorted(clusters.items(), key=lambda kv: -sum(counter[uniq[j]] for j in kv[1]))
        total = sum(counter.values())
        covered = sum(sum(counter[uniq[j]] for j in js) for _, js in ranked)
        print(
            f"\n=== {kind}: {total}행 → 고유 {len(uniq)} → 군집 {len(ranked)}개 "
            f"(소속 {100 * covered // total}%행)"
        )
        for rank, (_, js) in enumerate(ranked[:20], 1):
            rowcov = sum(counter[uniq[j]] for j in js)
            sample = sorted(js, key=lambda j: -counter[uniq[j]])[:6]
            print(f"  [{rank:2d}] {rowcov:5d}행  " + " · ".join(uniq[j] for j in sample))


def mine(rows: list[tuple[str, str]], kind: str, floor: int) -> None:
    """접미어 빈도. 유형어 이름은 임베딩보다 이게 낫다 (측정 §9-1)."""
    counter: collections.Counter = collections.Counter()
    for row_kind, name in rows:
        if row_kind != kind:
            continue
        for token in re.split(r"[\s()\[\]]+", name):
            for length in (2, 3, 4):
                if len(token) > length:
                    counter[token[-length:]] += 1
    seen: list[str] = []
    for word, count in counter.most_common(300):
        if count < floor or any(word in s or s in word for s in seen):
            continue
        seen.append(word)
    print(f"\n=== {kind} 접미어 (빈도 {floor}+)")
    print("  " + " · ".join(f"{w}({counter[w]})" for w in seen[:40]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("compare", "discover", "mine"), default="compare")
    parser.add_argument("--kinds", nargs="+", default=["shopping", "cafe", "travel"])
    parser.add_argument("--min-cluster-size", type=int, default=5)
    parser.add_argument("--mine-kind", default="travel")
    parser.add_argument("--mine-floor", type=int, default=5)
    args = parser.parse_args()

    rows = asyncio.run(fetch(args.kinds))
    if not rows:
        print("행이 없다. 적재된 스냅샷이 있는지 확인할 것", file=sys.stderr)
        return 1
    print(f"{len(rows)}행 · {collections.Counter(k for k, _ in rows)}")

    if args.mode == "mine":
        mine(rows, args.mine_kind, args.mine_floor)
    elif args.mode == "discover":
        discover(rows, args.min_cluster_size)
    else:
        compare(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
