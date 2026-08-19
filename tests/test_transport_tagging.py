from app.geo.tagging import dog_ok, tags_for
from app.geo.transport import walk_advice
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
    assert lvl == "caution" and "underpass" in why[0]


async def test_fake_route_is_deterministic_and_no_stairs_longer():
    f = FakeProvider()
    o, d = LatLng(37.4979, 127.0276), LatLng(37.5145, 127.0316)
    a = await f.route("walk", o, d, "recommended")
    b = await f.route("walk", o, d, "no_stairs")
    assert a.facilities.stairs == 1 and b.facilities.stairs == 0
    assert b.distance_m > a.distance_m
    c = await f.route("car", o, d)
    assert c.taxi_fare and c.taxi_fare >= 4800


def test_parse_tmap_counts_facilities():
    data = {"features": [
        {"properties": {"totalDistance": 2500, "totalTime": 2580, "turnType": 200}, "geometry": {"type": "Point"}},
        {"properties": {"turnType": 211}, "geometry": {"type": "Point"}},
        {"properties": {"turnType": 127}, "geometry": {"type": "Point"}},
        {"properties": {"turnType": 126}, "geometry": {"type": "Point"}},
        {"properties": {"turnType": 213}, "geometry": {"type": "Point"}},
        {"properties": {"facilityType": "15"}, "geometry": {"type": "LineString", "coordinates": [[127.0, 37.5], [127.01, 37.51]]}},
    ]}
    r = parse_tmap(data, "recommended")
    assert r.distance_m == 2500 and r.duration_s == 2580
    assert r.facilities.crosswalk == 2 and r.facilities.stairs == 1 and r.facilities.underpass == 1
    assert len(r.polyline) == 2 and r.polyline[0].lat == 37.5
