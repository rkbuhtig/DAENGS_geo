from datetime import UTC, datetime

from app.geo.tagging import dog_ok, tags_for
from app.journey.advice import walk_advice
from app.planning.facts import RuntimeFacts
from app.planning.resolver import resolve_request
from app.planning.state import EditableState
from app.profile.source import PERSONAS
from app.providers.base import LatLng
from app.providers.fake import FakeProvider
from app.providers.tmap import parse_tmap
from tests.conftest import route


def test_tags_from_names():
    assert tags_for("강남24시동물의료센터") == ["24h", "center"]
    assert "ortho" in tags_for("서초동물정형외과") and "surgery" in tags_for("서초동물정형외과")
    assert tags_for("역삼동물안과") == ["eye"]
    assert not dog_ok(tags_for("강남고양이전문병원"))
    assert dog_ok(tags_for("역삼동물병원"))


def test_advice_senior_joint_avoids_stairs():
    lvl, why = walk_advice(route(10, stairs=1), PERSONAS["halmae"], None, [])
    assert lvl == "avoid" and any("계단" in w for w in why)


def test_advice_young_dog_ok_long_walk():
    assert walk_advice(route(30), PERSONAS["kong"], None, [])[0] == "ok"


def test_advice_brachy_caution_over_cap():
    lvl, _ = walk_advice(route(25), PERSONAS["dubu"], None, [])
    assert lvl == "caution"


def test_advice_user_max_min():
    assert walk_advice(route(12), None, 10, [])[0] == "avoid"


def test_advice_avoid_request_flags_caution():
    lvl, why = walk_advice(route(5, underpass=1), None, None, ["underpass"])
    assert lvl == "caution" and "지하 통로" in why[0]


async def test_fake_route_gives_numbers_but_never_facilities():
    """추정은 거리·시간·요금까지다. **시설은 지어내지 않는다** (결정 #21, #38).

    예전엔 "400m마다 횡단보도 1 · 1.5km 넘으면 계단 1" 을 만들어 냈고, 그게 walk_advice 로
    흘러 노령견 경로에 실측된 적 없는 계단 경고를 붙였다.
    """
    f = FakeProvider()
    o, d = LatLng(37.4979, 127.0276), LatLng(37.5145, 127.0316)
    a = await f.route("walk", o, d, "recommended")
    b = await f.route("walk", o, d, "no_stairs")
    assert a.facilities is None and b.facilities is None
    assert a.distance_m > 0 and a.duration_s > 0
    # 계단이 있는지도 모르는데 "계단을 피해 돌아간다" 고 할 수 없다 — 옵션이 숫자를 안 바꾼다
    assert (b.distance_m, b.duration_s) == (a.distance_m, a.duration_s)
    c = await f.route("car", o, d)
    assert c.taxi_fare and c.taxi_fare >= 4800


def test_parse_tmap_counts_facilities_like_real_response():
    # 실측 형태: 횡단보도=포인트 211/212, 지하보도=연속 LineString facilityType 14 (하나의 통로), 계단=포인트 127
    L = lambda ft, m: {"properties": {"facilityType": ft, "distance": m},
                       "geometry": {"type": "LineString", "coordinates": [[127.0, 37.5], [127.01, 37.51]]}}
    P = lambda tt: {"properties": {"turnType": tt}, "geometry": {"type": "Point", "coordinates": [127.0, 37.5]}}
    data = {"features": [
        {"properties": {"totalDistance": 2306, "totalTime": 1880, "turnType": 200}, "geometry": {"type": "Point", "coordinates": [127.0, 37.5]}},
        L("14", 18), P(12), L("14", 66), P(12), L("14", 26),      # 지하 통로 하나 (110m), 안에서 좌회전 2번
        P(211), L("15", 10), L("11", 300),
        P(127), L("11", 50),                                       # 계단
        P(212), L("15", 12), L("17", 651),                          # 17은 무시
        L("11", 200), L("14", 40),                                  # 별개 지하 통로
        P(201),
    ]}
    r = parse_tmap(data, "recommended")
    assert r.distance_m == 2306 and r.duration_s == 1880
    f = r.facilities
    assert f.crosswalk == 2 and f.stairs == 1
    assert f.origin_passage_m == 110          # 출발 직후 역 통로 — 장애물 아님
    assert f.underpass == 1 and f.underpass_m == 40
    assert len(r.polyline) == 2 * 10


def test_dog_time_factor_orders_personas():
    from app.journey.advice import dog_time_factor
    f_kong, f_dubu, f_hal = (dog_time_factor(PERSONAS[k]) for k in ("kong", "dubu", "halmae"))
    assert f_kong < f_dubu < f_hal <= 2.0
    assert dog_time_factor(None) == 1.2


def test_walk_options_to_try():
    from app.journey.advice import walk_options_to_try
    # 콩이(반응성)·할매(겁) → 골목 vs 큰길 비교. 두부(성격 플래그 없음, 낮) → 비교 없음. 밤이면 누구나 큰길 후보
    assert walk_options_to_try("recommended", [], PERSONAS["kong"]) == ["recommended", "main_road"]
    assert walk_options_to_try("no_stairs", [], PERSONAS["halmae"]) == ["no_stairs", "recommended", "main_road"]  # 추천은 항상 기준선
    assert walk_options_to_try("recommended", [], PERSONAS["dubu"]) == ["recommended"]
    assert walk_options_to_try("recommended", [], PERSONAS["dubu"], is_night=True) == ["recommended", "main_road"]
    assert walk_options_to_try("recommended", ["stairs"], None) == ["recommended", "no_stairs"]


def test_facilities_penalty_weights_avoid():
    from app.providers.base import Facilities
    f = Facilities(crosswalk=2, stairs=1, underpass=1)
    assert f.penalty() < f.penalty(("underpass",)) < f.penalty(("underpass", "stairs"))


# ------------------------------------------------- 수단별 적용 범위 (계층 불변식)
async def test_walk_avoid_changes_walk_leg_only():
    """도보 설정은 도보 leg 에만 닿는다. Transport 가 셋을 다 반환하므로
    '차량 모드인데 도보 판정이 있다'는 정상 — 문제는 **범위가 새는 것**이다."""
    from app.journey.engine import snapshot
    from app.providers.base import LatLng as LL

    o, d = LL(37.4979, 127.0276), LL(37.5145, 127.0316)
    facts = RuntimeFacts(now=datetime(2026, 8, 21, 3, 0, tzinfo=UTC), profile=PERSONAS["halmae"])
    plain_state = EditableState(lat=o.lat, lng=o.lng)
    avoided_state = EditableState(lat=o.lat, lng=o.lng)
    avoided_state.journey.walk.avoid = ["stairs", "underpass"]
    plain_plan = resolve_request(
        plain_state, facts, kind=None, companion="dog", measured=False,
    ).journey
    avoided_plan = resolve_request(
        avoided_state, facts, kind=None, companion="dog", measured=False,
    ).journey
    plain = await snapshot(plain_plan, d)
    avoided = await snapshot(avoided_plan, d)

    assert (plain.car.min, plain.car.m, plain.car.advice, plain.car.why) == \
           (avoided.car.min, avoided.car.m, avoided.car.advice, avoided.car.why), "차량 leg 가 변했다"
    # 설정은 도보 plan 에만 실린다 — 범위가 새지 않는다
    assert avoided_plan.walk.avoid == ("stairs", "underpass") and plain_plan.walk.avoid == ()
    # **추정에서는 avoid 가 경고를 못 만든다.** 시설을 모르니 "계단 있음" 이라 말할 재료가 없다.
    # 재료가 있을 때 경고가 뜨는지는 test_advice_avoid_request_flags_caution 이 본다.
    assert plain.walk.why == avoided.walk.why
    assert plain.walk.status == "estimate" and plain.walk.facilities is None


def test_arrive_note_is_injected_not_hardcoded():
    """공용 route 층은 '진료' 같은 도메인 어휘를 몰라야 한다. 산책·약국이 같은 층을 쓴다."""
    from app.journey.spots import DEFAULT_ARRIVE_NOTE, spot_note
    from app.providers.base import LatLng as LL
    from app.providers.base import Spot

    sp = Spot("arrive", LL(37.5, 127.0), 0, "도착")
    assert "진료" not in DEFAULT_ARRIVE_NOTE, "공용 기본값에 병원 어휘가 있다"
    assert spot_note(sp, None)[0] == DEFAULT_ARRIVE_NOTE
    assert spot_note(sp, None, "도착 — 처방전 챙기기")[0] == "도착 — 처방전 챙기기"


def test_hospital_feature_owns_its_arrive_note():
    from app.features.hospital.api import ARRIVE_NOTE
    assert "진료" in ARRIVE_NOTE
