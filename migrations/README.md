# migrations/ — 동결됨

이 디렉터리의 `.sql` 파일은 **역사**다. 2026-08-24 이후로는 여기에 파일을 추가해도
아무도 실행하지 않는다. 스키마 변경은 alembic 리비전으로 만든다.

```bash
uv run alembic revision -m "무엇을 바꾸는지"   # alembic/versions/ 에 파일 생성
uv run alembic upgrade head
```

전부 `alembic/versions/0001_baseline.py` 안에 그대로 들어가 있고, 빈 DB 는 그 리비전
하나로 여기까지의 스키마가 된다. 파일을 남겨 두는 이유는 각 변경의 이유를 적은 주석이
원본 위치에 그대로 있는 게 읽기 좋아서다.

`011` 이 두 개인 것도 그대로다. 서로 다른 브랜치가 같은 번호를 집어서 main 에서 만난
결과이고, 둘이 각각 다른 테이블을 건드려서 **우연히** 무사했다. 번호로 순서를 정하던
방식이 실패한 지점이고, alembic 을 넣은 이유이기도 하다.

alembic 도입 전부터 쓰던 DB 는 이 중 어디까지 적용됐는지 각자 다르다 (그게 initdb 방식의
문제였다). 그래서 일괄 stamp 하지 않고 판별부터 한다:

```bash
uv run python -m scripts.detect_schema_revision
```

`dev_seed.sql` 은 마이그레이션이 아니라 개발용 시드다. 계속 수동으로 쓴다.
