from app.geo.tagging import dog_ok, tags_for
from app.journey.advice import walk_advice
from app.profile.source import PERSONAS
from app.providers.base import Facilities, LatLng, RouteResult
from app.providers.fake import FakeProvider
from app.providers.tmap import parse_tmap


def test_tags_from_names():
    assert tags_for("강남24시동물의료센터") == ["24h", "center"]
    assert "ortho" in tags_for("서초동물정형외과") and "surgery" in tags_for("서초동물정형외과")
    assert tags_for("역삼동물안과") == ["eye"]
    assert not dog_ok(tags_for("강남고양이전문병원"))
    assert dog_ok(tags_for("역삼동물병원"))


def _r(minutes, stairs=0, under=0, cross=1):
    return RouteResult("walk", int(minutes * 60), int(minutes * 60), "estimate",
                       facilities=Facilities(crosswalk=cross, stairs=stairs, underpass=under))


def test_advice_senior_joint_avoids_stairs():
    lvl, why = walk_advice(_r(10, stairs=1), PERSONAS["halmae"], None, [])
    assert lvl == "avoid" and any("계단" in w for w in why)


def test_advice_young_dog_ok_long_walk():
    assert walk_advice(_r(30), PERSONAS["kong"], None, [])[0] == "ok"


def test_advice_brachy_caution_over_cap():
    lvl, _ = walk_advice(_r(25), PERSONAS["dubu"], None, [])
    assert lvl == "caution"


def test_advice_user_max_min():
    assert walk_advice(_r(12), None, 10, [])[0] == "avoid"


def test_advice_avoid_request_flags_caution():
    lvl, why = walk_advice(_r(5, under=1), None, None, ["underpass"])
    assert lvl == "caution" and "지하 통로" in why[0]


async def test_fake_route_is_deterministic_and_no_stairs_longer():
    f = FakeProvider()
    o, d = LatLng(37.4979, 127.0276), LatLng(37.5145, 127.0316)
    a = await f.route("walk", o, d, "recommended")
    b = await f.route("walk", o, d, "no_stairs")
    assert a.facilities.stairs == 1 and b.facilities.stairs == 0
    assert b.distance_m > a.distance_m
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
