"""alembic 리비전이 원본 `.sql` 을 실행할 때 쓰는 헬퍼.

앱 런타임은 import 하지 않는다. `alembic/` 은 패키지가 아니라 리비전 파일끼리 공용 모듈을
import 할 수 없어서, 이미 sys.path 에 있고 컨테이너에도 들어가는 여기에 둔다.
"""

from alembic import context, op


def run_legacy_sql(name: str, sql: str) -> None:
    """`migrations/<name>` 의 내용을 그대로 실행한다.

    online 은 드라이버 커서에 직접 넣는다. `op.execute` / `exec_driver_sql` 은 빈 파라미터를
    함께 넘기고, 그러면 psycopg 가 SQL 안의 `%` 를 자리표시자로 읽어 `011_anchor` 주석의
    `3.5%` 에서 죽는다. 파일 하나에 든 여러 문장을 한 번에 보내는 것도 이 경로에서만 된다.

    offline(`--sql`)은 실행할 연결이 없으니 스크립트에 그대로 찍는다.
    """
    if context.is_offline_mode():
        op.get_context().impl.static_output(f"-- migrations/{name}{chr(10)}{sql}")
        return

    raw = op.get_bind().connection.driver_connection
    try:
        with raw.cursor() as cursor:
            cursor.execute(sql)
    except Exception as exc:
        raise RuntimeError(f"legacy SQL 실패: {name}") from exc
