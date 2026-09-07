-- Local R&D database only. Not a migration for Geo PostGIS or DEV #260.
CREATE TABLE IF NOT EXISTS seasons (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'FINALIZED')),
    initial_state TEXT NOT NULL,
    state TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_season ON seasons(status) WHERE status = 'ACTIVE';
CREATE TABLE IF NOT EXISTS commands (
    season_id TEXT NOT NULL REFERENCES seasons(id),
    request_id TEXT NOT NULL,
    command TEXT NOT NULL,
    result TEXT NOT NULL,
    PRIMARY KEY (season_id, request_id)
);
CREATE TABLE IF NOT EXISTS events (
    season_id TEXT NOT NULL REFERENCES seasons(id),
    seq INTEGER NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (season_id, seq)
);
PRAGMA user_version = 1;
