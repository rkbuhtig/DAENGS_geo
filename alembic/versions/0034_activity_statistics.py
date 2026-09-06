"""Activity source streams, versioned projections and transactional receipts.

Revision ID: 0034
Revises: 0033
"""

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE activity_session_source (
            owner_id text NOT NULL, client_id uuid NOT NULL,
            kind text NOT NULL CHECK (kind IN ('WALK','GAME')),
            server_id text NOT NULL, payload jsonb NOT NULL,
            PRIMARY KEY(owner_id, client_id, kind), UNIQUE(kind, server_id)
        )
    """)
    op.execute("""
        CREATE TABLE activity_stat_stream (
            kind text NOT NULL CHECK (kind IN ('WALK','TERRITORY')),
            scope_id text NOT NULL, revision bigint NOT NULL DEFAULT 0 CHECK(revision >= 0),
            through_ms bigint NOT NULL CHECK(through_ms >= 0), coverage jsonb,
            PRIMARY KEY(kind, scope_id),
            CHECK ((kind='TERRITORY') = (coverage IS NOT NULL))
        )
    """)
    op.execute("""
        CREATE TABLE activity_stat_change (
            kind text NOT NULL, scope_id text NOT NULL,
            revision bigint NOT NULL CHECK(revision > 0), event_id text NOT NULL,
            payload jsonb NOT NULL,
            PRIMARY KEY(kind, scope_id, revision), UNIQUE(kind, scope_id, event_id),
            FOREIGN KEY(kind, scope_id) REFERENCES activity_stat_stream(kind, scope_id)
        )
    """)
    op.execute("""
        CREATE TABLE activity_stat_generation (
            generation_id text PRIMARY KEY, statistics_version text NOT NULL,
            analysis_versions jsonb NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE activity_stat_checkpoint (
            generation_id text NOT NULL REFERENCES activity_stat_generation(generation_id),
            kind text NOT NULL, scope_id text NOT NULL,
            revision bigint NOT NULL CHECK(revision > 0), through_ms bigint NOT NULL,
            metadata jsonb NOT NULL,
            PRIMARY KEY(generation_id, kind, scope_id),
            FOREIGN KEY(kind, scope_id) REFERENCES activity_stat_stream(kind, scope_id)
        )
    """)
    op.execute("""
        CREATE TABLE activity_walk_contribution (
            generation_id text NOT NULL, kind text NOT NULL DEFAULT 'WALK' CHECK(kind='WALK'),
            scope_id text NOT NULL, owner_id text NOT NULL, analysis_id text NOT NULL,
            payload jsonb NOT NULL, PRIMARY KEY(generation_id, scope_id),
            FOREIGN KEY(generation_id,kind,scope_id)
                REFERENCES activity_stat_checkpoint(generation_id,kind,scope_id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE INDEX activity_walk_owner ON activity_walk_contribution(generation_id,owner_id)
    """)
    op.execute("""
        CREATE TABLE activity_holding_period (
            generation_id text NOT NULL, kind text NOT NULL DEFAULT 'TERRITORY'
                CHECK(kind='TERRITORY'), scope_id text NOT NULL,
            start_event_id text NOT NULL, site_id text NOT NULL, pet_id text NOT NULL,
            started_ms bigint NOT NULL, ended_ms bigint, payload jsonb NOT NULL,
            PRIMARY KEY(generation_id,scope_id,start_event_id,site_id),
            CHECK(ended_ms IS NULL OR ended_ms >= started_ms),
            FOREIGN KEY(generation_id,kind,scope_id)
                REFERENCES activity_stat_checkpoint(generation_id,kind,scope_id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX activity_one_open_period
        ON activity_holding_period(generation_id,scope_id,site_id) WHERE ended_ms IS NULL
    """)
    op.execute("""
        CREATE TABLE activity_stat_applied (
            generation_id text NOT NULL, kind text NOT NULL, scope_id text NOT NULL,
            revision bigint NOT NULL,
            PRIMARY KEY(generation_id,kind,scope_id,revision),
            FOREIGN KEY(generation_id,kind,scope_id)
                REFERENCES activity_stat_checkpoint(generation_id,kind,scope_id) ON DELETE CASCADE,
            FOREIGN KEY(kind,scope_id,revision)
                REFERENCES activity_stat_change(kind,scope_id,revision)
        )
    """)
    op.execute("""
        CREATE FUNCTION activity_stat_no_update() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'activity statistics immutable source/config'; END $$
    """)
    for table in ("activity_stat_change", "activity_stat_generation"):
        op.execute(f"""
            CREATE TRIGGER activity_no_update BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION activity_stat_no_update()
        """)
    # Once activated, accidentally using the original policy writer must fail at commit.
    op.execute("""
        CREATE FUNCTION activity_require_policy_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (SELECT 1 FROM activity_stat_stream
                       WHERE kind='TERRITORY' AND scope_id=NEW.season_id) THEN
                IF TG_TABLE_NAME='territory_policy_event' THEN
                    IF NOT EXISTS (SELECT 1 FROM activity_stat_change WHERE kind='TERRITORY'
                        AND scope_id=NEW.season_id AND event_id='policy:' || NEW.event_id) THEN
                        RAISE EXCEPTION 'missing activity ownership change';
                    END IF;
                ELSIF NEW.status='FINALIZED' THEN
                    IF NOT EXISTS (SELECT 1 FROM activity_stat_change WHERE kind='TERRITORY'
                        AND scope_id=NEW.season_id AND event_id='season-closed') THEN
                        RAISE EXCEPTION 'missing activity season close';
                    END IF;
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER activity_policy_event_required
        AFTER INSERT ON territory_policy_event DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION activity_require_policy_change()
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER activity_policy_close_required
        AFTER UPDATE ON territory_policy_season DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION activity_require_policy_change()
    """)


def downgrade():
    op.execute("DROP TRIGGER activity_policy_close_required ON territory_policy_season")
    op.execute("DROP TRIGGER activity_policy_event_required ON territory_policy_event")
    op.execute("DROP FUNCTION activity_require_policy_change()")
    for table in (
        "activity_stat_applied",
        "activity_holding_period",
        "activity_walk_contribution",
        "activity_stat_checkpoint",
        "activity_stat_generation",
        "activity_stat_change",
        "activity_stat_stream",
        "activity_session_source",
    ):
        op.execute(f"DROP TABLE {table}")
    op.execute("DROP FUNCTION activity_stat_no_update()")
