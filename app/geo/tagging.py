"""사업장명 → 태그. docs/explorations/hospital-search/name-tagging.md

한국 동물병원은 응급 여부는 이름에 넣고 과목은 안 넣는다. 잡히는 것만 잡는다.
공공데이터(이름)만 쓰므로 저장 자유.
"""

import re

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("24h",       re.compile(r"24\s*시|24시간|24H", re.IGNORECASE)),
    ("emergency", re.compile(r"응급")),
    ("center",    re.compile(r"의료센터|메디컬센터|메디컬|센터")),
    ("secondary", re.compile(r"2차|이차")),
    ("surgery",   re.compile(r"외과")),
    ("ortho",     re.compile(r"정형|관절")),
    ("eye",       re.compile(r"안과")),
    ("dental",    re.compile(r"치과")),
    ("derma",     re.compile(r"피부")),
    ("cardio",    re.compile(r"심장")),
    ("rehab",     re.compile(r"재활")),
    ("cat_only",  re.compile(r"고양이\s*(전문|병원|클리닉)|캣\s*(전문|병원|클리닉)")),
]

SPECIALTY_TAGS = {"ortho", "eye", "dental", "derma", "cardio", "rehab", "surgery"}


def tags_for(name: str) -> list[str]:
    return [tag for tag, rx in RULES if rx.search(name)]


def dog_ok(tags: list[str]) -> bool:
    return "cat_only" not in tags
