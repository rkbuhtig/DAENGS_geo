"""Normalized Geo territory ownership, policy accounts and immutable season history.

Revision ID: 0033
Revises: 0032
"""

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE territory_policy_season (
            season_id text PRIMARY KEY CHECK (btrim(season_id) <> ''),
            scope_id text NOT NULL CHECK (btrim(scope_id) <> ''),
            starts_ms bigint NOT NULL,
            ends_ms bigint NOT NULL CHECK (ends_ms > starts_ms),
            status text NOT NULL CHECK (status IN ('ACTIVE', 'FINALIZED')),
            contract_version text NOT NULL,
            rules jsonb NOT NULL CHECK (jsonb_typeof(rules) = 'object')
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX territory_policy_one_active
        ON territory_policy_season(scope_id) WHERE status = 'ACTIVE'
    """)
    op.execute("""
        CREATE TABLE territory_policy_account (
            season_id text NOT NULL REFERENCES territory_policy_season(season_id),
            pet_id text NOT NULL CHECK (btrim(pet_id) <> ''),
            bonus numeric(60, 0) NOT NULL CHECK (bonus >= 0),
            holding_units numeric(60, 0) NOT NULL CHECK (holding_units >= 0),
            held_site_ms numeric(60, 0) NOT NULL CHECK (held_site_ms >= 0),
            current_count bigint NOT NULL CHECK (current_count >= 0),
            scoring_count bigint NOT NULL CHECK (scoring_count >= 0),
            peak bigint NOT NULL CHECK (peak >= current_count),
            claims bigint NOT NULL CHECK (claims >= 0),
            takeovers bigint NOT NULL CHECK (takeovers >= 0 AND takeovers <= claims),
            last_ms bigint NOT NULL,
            CHECK (scoring_count <= current_count),
            PRIMARY KEY (season_id, pet_id)
        )
    """)
    op.execute("""
        CREATE TABLE territory_policy_site (
            season_id text NOT NULL REFERENCES territory_policy_season(season_id),
            site_id text NOT NULL REFERENCES territory_site(site_id),
            version bigint NOT NULL CHECK (version >= 0),
            pet_id text,
            session_id text,
            attempt_id text,
            certification text CHECK (certification IN ('UNVERIFIED', 'VERIFIED')),
            occupied_ms bigint,
            imported_occupied_ms bigint,
            CHECK (
                (pet_id IS NULL AND session_id IS NULL AND attempt_id IS NULL
                    AND certification IS NULL AND occupied_ms IS NULL) OR
                (pet_id IS NOT NULL AND session_id IS NOT NULL AND attempt_id IS NOT NULL
                    AND certification IS NOT NULL AND occupied_ms IS NOT NULL
                    AND btrim(pet_id) <> '' AND btrim(session_id) <> '' AND btrim(attempt_id) <> '')
            ),
            PRIMARY KEY (season_id, site_id),
            FOREIGN KEY (season_id, pet_id)
                REFERENCES territory_policy_account(season_id, pet_id)
                DEFERRABLE INITIALLY DEFERRED
        )
    """)
    op.execute("""
        CREATE INDEX territory_policy_owned_by_pet
        ON territory_policy_site(season_id, pet_id) WHERE pet_id IS NOT NULL
    """)
    op.execute("""
        CREATE TABLE territory_policy_attempt (
            attempt_id text PRIMARY KEY CHECK (btrim(attempt_id) <> ''),
            season_id text NOT NULL,
            site_id text NOT NULL,
            pet_id text NOT NULL CHECK (btrim(pet_id) <> ''),
            session_id text NOT NULL CHECK (btrim(session_id) <> ''),
            FOREIGN KEY (season_id, site_id)
                REFERENCES territory_policy_site(season_id, site_id)
        )
    """)
    op.execute("""
        CREATE TABLE territory_policy_receipt (
            season_id text NOT NULL,
            event_id text NOT NULL CHECK (btrim(event_id) <> ''),
            site_id text NOT NULL,
            pet_id text NOT NULL,
            attempt_id text NOT NULL REFERENCES territory_policy_attempt(attempt_id),
            payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            PRIMARY KEY (season_id, event_id),
            FOREIGN KEY (season_id, site_id)
                REFERENCES territory_policy_site(season_id, site_id),
            FOREIGN KEY (season_id, pet_id)
                REFERENCES territory_policy_account(season_id, pet_id)
        )
    """)
    op.execute("""
        CREATE TABLE territory_policy_event (
            season_id text NOT NULL,
            event_id text NOT NULL,
            payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            PRIMARY KEY (season_id, event_id),
            FOREIGN KEY (season_id, event_id)
                REFERENCES territory_policy_receipt(season_id, event_id)
                DEFERRABLE INITIALLY DEFERRED
        )
    """)
    op.execute("""
        CREATE TABLE territory_policy_bonus (
            season_id text NOT NULL,
            pet_id text NOT NULL,
            site_id text NOT NULL,
            utc_day bigint NOT NULL,
            PRIMARY KEY (season_id, pet_id, site_id, utc_day),
            FOREIGN KEY (season_id, pet_id)
                REFERENCES territory_policy_account(season_id, pet_id),
            FOREIGN KEY (season_id, site_id)
                REFERENCES territory_policy_site(season_id, site_id)
        )
    """)
    op.execute("""
        CREATE TABLE territory_policy_result (
            season_id text NOT NULL,
            pet_id text NOT NULL,
            rank bigint NOT NULL CHECK (rank > 0),
            total_units numeric(60, 0) NOT NULL CHECK (total_units >= 0),
            score jsonb NOT NULL CHECK (jsonb_typeof(score) = 'object'),
            PRIMARY KEY (season_id, pet_id),
            FOREIGN KEY (season_id, pet_id)
                REFERENCES territory_policy_account(season_id, pet_id)
        )
    """)
    op.execute("""
        CREATE FUNCTION territory_policy_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'territory policy history is immutable';
        END $$
    """)
    for table in ("attempt", "receipt", "event", "bonus", "result"):
        op.execute(f"""
            CREATE TRIGGER territory_policy_immutable BEFORE UPDATE OR DELETE
            ON territory_policy_{table} FOR EACH ROW
            EXECUTE FUNCTION territory_policy_immutable()
        """)
    op.execute("""
        CREATE FUNCTION territory_policy_season_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status = 'FINALIZED' OR
               (to_jsonb(OLD) - 'status') IS DISTINCT FROM (to_jsonb(NEW) - 'status') THEN
                RAISE EXCEPTION 'territory policy season configuration is immutable';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER territory_policy_season_guard BEFORE UPDATE
        ON territory_policy_season FOR EACH ROW EXECUTE FUNCTION territory_policy_season_guard()
    """)


def downgrade() -> None:
    for table in ("result", "bonus", "event", "receipt", "attempt", "site", "account", "season"):
        op.drop_table(f"territory_policy_{table}")
    op.execute("DROP FUNCTION territory_policy_immutable()")
    op.execute("DROP FUNCTION territory_policy_season_guard()")
