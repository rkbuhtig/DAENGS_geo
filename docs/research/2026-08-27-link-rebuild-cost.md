# `rebuild_links` 는 2억 쌍을 훑어 107행을 만든다 — 원인과 선택지

테스트 최적화(#124) 중에 `test_cross_kind_rows_are_neither_linked_nor_collapsed` 가 12초라
픽스처를 줄이려다, 쿼리 자체가 그만큼 걸린다는 것을 알았다. 테스트 문제가 아니라 **적재
경로의 문제**다.

측정 시점 `facility` 33,611 행 (kcisa 23,914 · kto 9,692 · dev 5), PostgreSQL 18.6.

## 무엇이 느린가

`rebuild_links()` 는 KCISA·KTO 적재가 끝날 때마다 돈다 (`ingest/kcisa.py:141`,
`ingest/kto.py:217`). 두 쿼리의 비용이 극단적으로 갈린다.

| | 시간 | 만드는 행 |
|---|---|---|
| `_LINK_MEDICAL` | 1.5s | 11,021 |
| `_LINK_CROSS` | **13.0s** | **107** |

8.6 배 느리게 100 분의 1 을 만든다.

## 원인 — 공간 인덱스가 있는데 안 쓰인다

```
Hash Join  (actual time=635..12259)
  Hash Cond: (n.kind = o.kind)
  Rows Removed by Join Filter: 195,971,053
```

`facility_gix` (GiST) 가 **존재하는데** 플래너가 `kind` 로만 해시 조인한다. CTE 에서
`regexp_replace` 로 파생 결과셋을 만드는 순간 `location` 이 인덱스와 끊기기 때문이다.

곱이 그대로 드러난다 — kind 분포가 shopping 8,647 · pharmacy 8,443 · pet_shop 5,389 이라
**같은 kind 쌍만 약 2억**이다 (Σ kind²  ≈ 201,874,124). 나머지 조건은 전부 per-pair 필터라
2억 번 평가된다.

`o.source < n.source` 가 **해시 조건이 아니라 필터**인 것도 같은 결과에 기여한다. 조인에
들어갔다면 쌍이 667,535 로 줄었다.

`_LINK_MEDICAL` 이 빠른 이유도 같은 원리다 — `kind IN ('hospital','pharmacy')` 로 CTE 를
먼저 줄여 곱이 작다. 규칙이 좋아서가 아니라 **대상이 작아서** 빠르다.

## 공간 조건이 먼저 걸리면 후보는 139 쌍이다

```sql
SELECT count(*) FROM facility n JOIN facility o
  ON o.source < n.source AND o.kind = n.kind
 AND ST_DWithin(n.location, o.location, 150)
→ 3.7s / 139 쌍
```

즉 이 작업의 **본질적 크기는 139 쌍**이고 나머지 2억은 낭비다.

## 그런데 재작성만으로는 안 풀린다

| 방식 | 시간 |
|---|---|
| 현재 (CTE + 해시 조인) | 13.0s |
| 원본 테이블 직접 조인 | 9.8s |
| 공간 우선 + `MATERIALIZED` (Nested Loop 로 전환됨) | 9.2s |
| 공간 조인 **단독** | 3.7s |

마지막 재작성은 실행계획이 실제로 `Nested Loop` 으로 바뀌어 GiST 를 타는데도 9.2 초다.
`Buffers: shared hit≈2,090,000` 에 병렬 워커 2 개를 쓰고도 그렇다 — **33k 행 자기조인
자체가 무겁다.** 30% 를 깎자고 쿼리를 복잡하게 만들 값어치는 없다.

## 선택지

### ① 증분화 — 효과가 제일 크다

지금은 `DELETE FROM facility_link` 후 33k 전체를 다시 건다. 실제로 바뀐 것은 방금 적재한
원천뿐이다. 정해야 할 것은 **"어느 쪽이 바뀌면 어느 링크가 무효인가"** 하나다.
`o.source < n.source` 방향 규칙 때문에 kcisa 가 바뀌면 kto→kcisa 링크가 전부 무효이므로,
그 경계를 명시하면 재구축 범위가 한 원천으로 줄어든다.

### ② 매칭 규칙 재검토와 함께

`LIKE '%' || norm || '%'` 양방향이 인덱스를 원천적으로 막는다. `pg_trgm` 은 이 DB 에서
**설치 가능하지만 아직 설치 안 됨**(`pg_available_extensions` 확인). 정규화된 이름에
trigram GIN 을 걸면 부분일치가 인덱스를 탄다.

다만 이 규칙 자체가 **잠정**이다 — `linking.py` docstring 이 밝힌다: 재현율 70% ·
전화 불일치 8.8% (2026-08-24 실측), 캘리브레이션은 보류. **성능만 먼저 고치면 곧 바뀔
규칙을 최적화하는 셈이다.**

### ③ 그대로 둔다

적재는 배치다. 13 초가 사용자를 기다리게 하지 않는다.

## 지금의 권고 — ③, 단 조건부

고치지 않는다. 테스트는 #124 로 35 초까지 내려왔고 이 13 초는 배치 안에 있다.

**다시 볼 조건 두 가지**:

- **원천이 셋째로 늘 때.** `o.source < n.source` 가 "최신 → 과거" 와 일치하는 것은 원천이
  둘일 때뿐이라고 `linking.py` 주석이 이미 경고한다. 그때 우선순위 표를 만들면서 같이 본다.
- **`facility` 가 눈에 띄게 커질 때.** 비용이 행 수의 제곱으로 는다 — 33k 에서 13 초면
  70k 에서는 한 자리 분이다.

매칭 규칙 캘리브레이션을 할 때는 **성능을 같이 본다.** ②가 규칙과 성능을 한 번에 바꾸는
유일한 지점이라 따로 하면 두 번 일한다.
