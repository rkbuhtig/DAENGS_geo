"""판단 재료의 출처·시점·용도를 보존하는 공용 Context Plane.

제품 기능과 LLM은 이 패키지의 닫힌 capability 계약을 통해서만 문맥을 소비한다. Provider
호출과 기존 도메인 객체 변환은 응용층 ``features.context_plane``이 담당한다.
"""

