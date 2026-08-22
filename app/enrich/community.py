"""커뮤니티 근거. docs/explorations/hospital-search/community-search.md

프로필+발화 → 주인 말투 쿼리 → 검색 API 스니펫 → 반경 안 병원명과 매칭 → evidence.
필터 아님. 부스트 + 표시. 저장 안 함.

Fake: 시드 스니펫 — `DAENGS_ALLOW_FAKE_EVIDENCE=true` 일 때만. Naver: 검색 API(블로그/
카페/지식iN) — 키 있을 때 (미구현 스텁).
"""

from dataclasses import dataclass
from typing import Protocol

from app.core.config import settings
from app.geo.schemas import PlaceOut
from app.profile.contract import DogProfile


@dataclass(frozen=True)
class Snippet:
    source: str      # cafe | blog | kin | web
    title: str
    text: str
    url: str


@dataclass(frozen=True)
class Evidence:
    source: str
    text: str
    url: str


class CommunitySearch(Protocol):
    async def search(self, queries: list[str]) -> list[Snippet]: ...


# ---- 쿼리 재작성 (LLM 없이도 되는 규칙 버전; 실제는 LLM이 주인 말투로) ------------
def rewrite_queries(symptoms: list[str], specialty: list[str],
                    profile: DogProfile | None, area: str = "강남") -> list[str]:
    """**state 에서** 쿼리를 만든다. utterance 를 직접 받지 않는다.

    그 턴에 말을 했는지가 아니라 state 에 뭐가 적혀 있는지가 쿼리를 정해야, 같은 state 가
    같은 근거·같은 순위를 낸다 (무상태 계약). 증상은 사용자의 말 그대로 들어온다 —
    정제하지 않는다. 실험에서 정제한 쿼리는 과목을 못 잡았고 증상 언어가 잡았다.
    """
    qs: list[str] = []
    breed = profile.breed[0].breed if profile and profile.breed else "강아지"
    for term in symptoms:
        qs.append(f"{breed} {term} {area} 동물병원 어디가 좋아요")
    _SPECIALTY_Q = {
        "ortho": f"{area} 슬개골 수술 잘하는 동물병원 후기",
        "eye": f"{area} 동물 안과 백내장 후기",
        "dental": f"{area} 강아지 치과 스케일링 후기",
        "derma": f"{breed} 피부 가려움 {area} 동물병원 추천",
        "cardio": f"{breed} 심장 진료 {area} 동물병원 후기",
        "rehab": f"{area} 강아지 재활 치료 후기",
    }
    qs += [_SPECIALTY_Q[t] for t in specialty if t in _SPECIALTY_Q]
    return qs[:3]


# ---- Fake ---------------------------------------------------------------
_SEED = [
    Snippet("cafe", "강남 슬개골 수술 어디서 하셨어요?", "저희는 논현동물의료센터에서 했어요. 재활까지 같이 봐주셔서 만족", "https://cafe.example/1"),
    Snippet("blog", "서초 정형외과 동물병원 다녀온 후기", "서초동물정형외과 원장님이 관절만 20년 보셨대요. 십자인대 상담", "https://blog.example/2"),
    Snippet("kin", "말티즈 노견 눈이 뿌옇게 됐어요", "역삼동물안과에서 백내장 진단받았어요. 안과 전문이라 장비가 좋더라구요", "https://kin.example/3"),
    Snippet("cafe", "밤에 퍼그가 숨을 헐떡여서", "강남24시동물병원 새벽에 갔는데 바로 봐주셨어요", "https://cafe.example/4"),
    Snippet("blog", "24시 동물병원 비교", "논현동물의료센터는 야간 응급 할증 없다고 해요", "https://blog.example/5"),
    Snippet("web", "틱톡 강아지 밈 모음", "관련 없음", "https://noise.example/6"),
]


class FakeCommunitySearch:
    async def search(self, queries: list[str]) -> list[Snippet]:
        return list(_SEED)


class NullCommunitySearch:
    async def search(self, queries: list[str]) -> list[Snippet]:
        return []


def community_search() -> CommunitySearch:
    if settings.community_provider == "fake":
        # 가짜 근거는 **순위를 바꾼다** (hospital/api.py boost). 운영 응답에 섞이면
        # 지역과 무관한 시드가 실제 병원 순서를 흔든다 — 이 값을 직접 켠 환경으로 한정한다.
        # `dev_console` 을 보지 않는다: /dev 를 여는 것과 순위를 흔드는 건 다른 결정이다.
        return FakeCommunitySearch() if settings.allow_fake_evidence else NullCommunitySearch()
    # TODO: NaverSearch(client_id, secret) — 블로그/카페글/지식iN 엔드포인트
    return NullCommunitySearch()


# ---- 매칭: 스니펫 → 반경 안 병원 ------------------------------------------
def match(snippets: list[Snippet], results: list[PlaceOut]) -> dict[int, list[Evidence]]:
    """이름이 스니펫에 그대로 들어있으면 매칭. (실제는 LLM에 반경 안 병원명 목록 주고 고르게 — 환각 억제)"""
    ev: dict[int, list[Evidence]] = {}
    for r in results:
        key = r.name.replace(" ", "")
        for s in snippets:
            if key in (s.title + s.text).replace(" ", ""):
                ev.setdefault(r.id, []).append(Evidence(s.source, s.text, s.url))
    return ev


async def attach_evidence(symptoms: list[str], specialty: list[str],
                          profile: DogProfile | None,
                          results: list[PlaceOut]) -> dict[int, list[Evidence]]:
    qs = rewrite_queries(symptoms, specialty, profile)
    if not qs:
        return {}
    snippets = await community_search().search(qs)
    return match(snippets, results)
