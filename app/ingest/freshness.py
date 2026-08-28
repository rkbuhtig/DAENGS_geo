"""파생값이 **아직 유효한가** — 재파생 배치 공통 규약.

    fresh = (같은 규칙 버전) AND (같은 입력)

두 축이 다 맞아야 한다. 리비전 0018 은 첫 축만 갖고 있었고, 그래서 재적재가
`facility.pet` 을 덮어써도 파생값이 스스로 낡았다고 말하지 못했다 —
`목줄` 이 `대형견 입장 불가` 로 바뀐 행이 `require:leash` 를 계속 내보냈다.

## 왜 여기 있나

`restrictions` 와 `pet_axes` 가 **같은 결함**을 갖고 있었다. 한 축의 버그가 아니라
재파생 패턴의 결함이므로 규약을 한 자리에 둔다. 다음 파생 축(태그)도 이것을 쓴다.

## 왜 해시인가 — 타임스탬프가 아니라

`synced_at` 비교는 값이 안 바뀐 재적재에서도 33,611행을 전부 다시 판다. 지문은
**실제로 바뀐 행만** 고른다. 정확성이 아니라 비용의 문제이고, 배치가 싸야 자주 돈다.

## 지문의 입력은 파생이 **실제로 읽는 것**이어야 한다

`pet` 봉투 전체를 해싱하면 `restrictions` 와 무관한 키가 바뀌어도 재파생한다.
반대로 너무 좁게 잡으면 진짜 변경을 놓친다. 각 파생층이 자기 입력을 명시한다.
"""

import hashlib

# 입력이 비어 있는 행(원문 없음)도 지문을 가져야 한다 — NULL 이면 "아직 안 팠다" 와
# 구분이 안 되고, 배치가 매번 다시 판다.
#
# **NUL(`\x00`) 을 쓰지 않는다.** PostgreSQL `text` 가 그 바이트를 거부해서
# 배치의 `md5(COALESCE(입력, :empty))` 가 통째로 죽는다. 실제 원문에 나타나지
# 않으면서 전송 가능한 값이어야 한다.
EMPTY_INPUT = "␟<empty>"
_SEPARATOR = "␞"


def fingerprint(*parts: str | None) -> str:
    """파생 입력의 지문. 같은 입력이면 같은 값, 다르면 다른 값.

    md5 를 쓰는 이유는 충돌 저항이 아니라 **변경 감지**이기 때문이다. 이 값은
    보안 경계가 아니라 캐시 무효화에 쓰인다.

    **배치의 미처리 SQL 이 같은 값을 계산할 수 있어야 한다.** 입력이 하나면
    `md5(COALESCE(입력, EMPTY_INPUT))` 과 일치한다 — 파이썬에서만 계산하면
    행을 전부 끌어와야 하고, 그러면 지문을 쓰는 이유(싼 배치)가 없어진다.
    등가성은 테스트가 실DB 로 고정한다.
    """
    joined = _SEPARATOR.join(EMPTY_INPUT if part is None else part for part in parts)
    return hashlib.md5(joined.encode("utf-8"), usedforsecurity=False).hexdigest()


def is_stale(
    *,
    stored_fp: str | None,
    current_fp: str,
    stored_version: str | None,
    current_version: str,
) -> bool:
    """다시 파야 하는가. **모르면 판다** — 지문이 없는 행은 낡은 것으로 본다."""
    if stored_fp is None or stored_version is None:
        return True
    return stored_fp != current_fp or stored_version != current_version
