# 개발용 seed

`dev_seed.sql`은 강남역 주변의 가상 시설 9개다. 개발 화면·검색을 확인할 때 수동으로
적재한다. `source=dev`인 같은 행을 다시 실행하면 갱신하며 실제 운영 적재 자료가 아니다.

저장소 루트에서 로컬 DB를 시작하고 스키마를 적용한 뒤 실행한다.

```bash
docker compose up -d db
uv run alembic upgrade head
docker compose exec -T db psql -U daengs -d daengs < seeds/dev_seed.sql
```

기존 `migrations/dev_seed.sql`을 내용 그대로 이곳으로 옮겼다.
스키마 변경·기존 DB 판별·과거 SQL 이력은 [Alembic 안내](../alembic/README.md)를 따른다.
seed는 DB 최초 실행이나 API 시작 시 자동 적재되지 않는다.
