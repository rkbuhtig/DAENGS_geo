"""버튼과 적용 결과가 공유하는 짧은 사용자 어휘."""

VALUE_LABELS = {
    "recommended": "추천", "main_road": "큰길 우선", "shortest": "최단", "no_stairs": "계단 제외",
    "walk": "도보", "car": "차량", "transit": "대중교통",
    "distance": "거리순", "duration": "소요시간순", "open_first": "영업중 우선",
    "ortho": "정형", "eye": "안과", "dental": "치과", "derma": "피부", "cardio": "심장", "rehab": "재활",
    "24h": "24시", "center": "의료센터", "secondary": "2차", "surgery": "외과",
    "stairs": "계단", "underpass": "지하도", "overpass": "육교",
}


def value_label(value: object) -> str:
    return VALUE_LABELS.get(value, str(value))


def format_distance_m(distance_m: int) -> str:
    return f"{distance_m / 1000:g}km" if distance_m >= 1000 else f"{distance_m}m"
