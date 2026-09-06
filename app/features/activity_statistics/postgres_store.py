"""Transactional PostgreSQL reference runner. Caller owns commit and rollback.

One adapter per transaction; propagate every error out of the transaction context.
Replay is scoped to one walk/season. No engine, environment fallback or worker daemon.
"""

import json
from dataclasses import asdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import codec
from .common import ProjectionIdentity, identifier, require
from .sessions import SessionSource, resolve_session_links
from .territory import (
    ConfirmedCut,
    TerritoryCoverage,
    TerritoryProjection,
    TerritoryStatEvent,
    project_territory,
)
from .walk import AnalysisVersions, WalkProjection, WalkSelection, project_walks


class PostgresStatisticsTransaction:
    def __init__(self, session: AsyncSession):
        require(session.in_transaction(), "statistics_transaction_required")
        self.session = session
        self.transaction = session.get_transaction()

    async def rows(self, sql, params=None):
        require(
            self.session.get_transaction() is self.transaction, "statistics_transaction_changed"
        )
        return (await self.session.execute(text(sql), params or {})).mappings()

    async def record_session(self, source: SessionSource, *, correction=False):
        # Covers first insert as well as cross-kind arrival; uniqueness handles server-ID reuse.
        await self.rows(
            "SELECT pg_advisory_xact_lock(hashtextextended(:key,0))",
            {
                "key": json.dumps([source.owner_id, source.client_walk_session_id]),
            },
        )
        params = {
            "owner": source.owner_id,
            "client": source.client_walk_session_id,
            "kind": source.kind,
            "server": source.server_session_id,
            "payload": codec.encode(source),
        }
        old = (
            await self.rows(
                """
            SELECT payload FROM activity_session_source
            WHERE owner_id=:owner AND client_id=CAST(:client AS uuid) AND kind=:kind
        """,
                params,
            )
        ).one_or_none()
        if old:
            previous = codec.session_source(old["payload"])
            if previous == source:
                return
            require(
                correction
                and previous.server_session_id == source.server_session_id
                and previous.started_ms == source.started_ms,
                "session_payload_conflict",
            )
            await self.rows(
                """
                UPDATE activity_session_source SET payload=CAST(:payload AS jsonb)
                WHERE owner_id=:owner AND client_id=CAST(:client AS uuid) AND kind=:kind
            """,
                params,
            )
        else:
            await self.rows(
                """
                INSERT INTO activity_session_source(owner_id,client_id,kind,server_id,payload)
                VALUES (:owner,CAST(:client AS uuid),:kind,:server,CAST(:payload AS jsonb))
            """,
                params,
            )

    async def links(self, owner_id: str):
        rows = await self.rows(
            "SELECT payload FROM activity_session_source WHERE owner_id=:owner",
            {
                "owner": owner_id,
            },
        )
        return resolve_session_links(codec.session_source(row["payload"]) for row in rows)

    async def register_generation(self, identity: ProjectionIdentity, versions: AnalysisVersions):
        params = {
            "gid": identity.generation_id,
            "version": identity.statistics_version,
            "versions": codec.encode(versions),
        }
        await self.rows(
            """
            INSERT INTO activity_stat_generation VALUES (:gid,:version,CAST(:versions AS jsonb))
            ON CONFLICT DO NOTHING
        """,
            params,
        )
        row = await self.generation(identity.generation_id)
        require(row == (identity, versions), "generation_config_conflict")

    async def generation(self, generation_id):
        row = (
            await self.rows(
                """
            SELECT * FROM activity_stat_generation WHERE generation_id=:gid FOR UPDATE
        """,
                {"gid": generation_id},
            )
        ).one_or_none()
        require(row is not None, "unknown_generation")
        return (
            ProjectionIdentity(row["generation_id"], row["statistics_version"]),
            AnalysisVersions(**row["analysis_versions"]),
        )

    async def stream(self, kind, scope_id):
        row = (
            await self.rows(
                """
            SELECT * FROM activity_stat_stream WHERE kind=:kind AND scope_id=:scope FOR UPDATE
        """,
                {"kind": kind, "scope": scope_id},
            )
        ).one_or_none()
        require(row is not None, "unknown_statistics_stream")
        return row

    async def changes(self, kind, scope_id, revision):
        return (
            await self.rows(
                """
            SELECT payload FROM activity_stat_change WHERE kind=:kind AND scope_id=:scope
            AND revision<=:revision ORDER BY revision
        """,
                {"kind": kind, "scope": scope_id, "revision": revision},
            )
        ).all()

    async def _append(self, kind, scope_id, event_id, revision, at_ms, value):
        await self.rows(
            """
            INSERT INTO activity_stat_change(kind,scope_id,revision,event_id,payload)
            VALUES (:kind,:scope,:revision,:event,CAST(:payload AS jsonb))
        """,
            {
                "kind": kind,
                "scope": scope_id,
                "revision": revision,
                "event": event_id,
                "payload": codec.encode(value),
            },
        )
        await self.rows(
            """
            UPDATE activity_stat_stream SET revision=:revision,through_ms=:at
            WHERE kind=:kind AND scope_id=:scope
        """,
            {"kind": kind, "scope": scope_id, "revision": revision, "at": at_ms},
        )

    async def append_walk(self, change: WalkSelection):
        """Call alongside the host's sealed analysis/head transaction, never after commit."""
        await self.rows(
            """
            INSERT INTO activity_stat_stream(kind,scope_id,through_ms)
            VALUES ('WALK',:scope,0) ON CONFLICT DO NOTHING
        """,
            {"scope": change.walk_id},
        )
        stream = await self.stream("WALK", change.walk_id)
        history = [
            codec.selection(row["payload"])
            for row in await self.changes("WALK", change.walk_id, stream["revision"])
        ]
        if change.revision <= stream["revision"]:
            require(history[change.revision - 1] == change, "selection_payload_conflict")
            return
        require(change.revision == stream["revision"] + 1, "selection_gap")
        # Validate semantic identity/correction/withdrawal before storing the change.
        versions = change.source.versions if change.source else AnalysisVersions(1, 1, 1, 1)
        project_walks(
            [*history, change],
            identity=ProjectionIdentity("input-validation"),
            expected_versions=versions,
        )
        if change.source:
            await self.record_session(change.source.session, correction=change.revision > 1)
        await self._append(
            "WALK",
            change.walk_id,
            str(change.revision),
            change.revision,
            stream["through_ms"],
            change,
        )

    async def initialize_territory(self, coverage: TerritoryCoverage, initial: TerritoryStatEvent):
        require(initial.kind == "INITIALIZED", "initialization_required")
        project_territory(
            [initial],
            identity=ProjectionIdentity("input-validation"),
            coverage=coverage,
            cut=ConfirmedCut(coverage.season_id, initial.revision, initial.at_ms),
        )
        await self.rows(
            """
            INSERT INTO activity_stat_stream(kind,scope_id,revision,through_ms,coverage)
            VALUES ('TERRITORY',:scope,:revision,:at,CAST(:coverage AS jsonb))
        """,
            {
                "scope": coverage.season_id,
                "revision": coverage.base_revision,
                "at": coverage.coverage_start_ms,
                "coverage": codec.encode(coverage),
            },
        )
        await self._append(
            "TERRITORY",
            coverage.season_id,
            initial.event_id,
            initial.revision,
            initial.at_ms,
            initial,
        )

    async def append_territory(self, event: TerritoryStatEvent):
        stream = await self.stream("TERRITORY", event.season_id)
        old = (
            await self.rows(
                """
            SELECT payload FROM activity_stat_change WHERE kind='TERRITORY'
            AND scope_id=:scope AND event_id=:event
        """,
                {"scope": event.season_id, "event": event.event_id},
            )
        ).one_or_none()
        if old:
            require(codec.event(old["payload"]) == event, "event_payload_conflict")
            return
        require(event.revision == stream["revision"] + 1, "event_gap")
        require(event.at_ms >= stream["through_ms"], "event_before_confirmed_cut")
        # The producer has validated ownership. The runner validates the complete replay.
        await self._append(
            "TERRITORY", event.season_id, event.event_id, event.revision, event.at_ms, event
        )

    async def confirm_territory(self, season_id, through_ms):
        """Only a host holding the authoritative season barrier may advance this cut."""
        stream = await self.stream("TERRITORY", season_id)
        coverage = TerritoryCoverage(**stream["coverage"])
        cut = ConfirmedCut(season_id, stream["revision"], through_ms)
        require(through_ms >= stream["through_ms"], "cut_time_reversed")
        events = [
            codec.event(row["payload"])
            for row in await self.changes("TERRITORY", season_id, stream["revision"])
        ]
        project_territory(
            events, identity=ProjectionIdentity("cut-validation"), coverage=coverage, cut=cut
        )
        await self.rows(
            """
            UPDATE activity_stat_stream SET through_ms=:at WHERE kind='TERRITORY' AND scope_id=:scope
        """,
            {"scope": season_id, "at": through_ms},
        )
        return cut

    async def pending(self, generation_id, limit=100):
        require(type(limit) is int and 0 < limit <= 1000, "invalid_batch_limit")
        await self.generation(generation_id)
        return (
            await self.rows(
                """
            SELECT s.kind,s.scope_id FROM activity_stat_stream s
            LEFT JOIN activity_stat_checkpoint c ON c.kind=s.kind AND c.scope_id=s.scope_id
                AND c.generation_id=:gid
            WHERE c.revision IS NULL OR c.revision<s.revision OR c.through_ms<s.through_ms
            ORDER BY s.kind,s.scope_id LIMIT :limit
        """,
                {"gid": generation_id, "limit": limit},
            )
        ).all()

    async def refresh(self, generation_id, kind, scope_id):
        """Atomic result + applied receipts + checkpoint; safe to retry after rollback.

        Lock order is generation then stream. Producers never acquire generation locks.
        This reference implementation replays a whole scope under its stream lock.
        """
        identity, versions = await self.generation(generation_id)
        stream = await self.stream(kind, scope_id)
        params = {"gid": generation_id, "kind": kind, "scope": scope_id}
        previous = (
            await self.rows(
                """
            SELECT * FROM activity_stat_checkpoint
            WHERE generation_id=:gid AND kind=:kind AND scope_id=:scope
        """,
                params,
            )
        ).one_or_none()
        if previous and (previous["revision"], previous["through_ms"]) == (
            stream["revision"],
            stream["through_ms"],
        ):
            return False
        rows = await self.changes(kind, scope_id, stream["revision"])
        if kind == "WALK":
            result = project_walks(
                [codec.selection(row["payload"]) for row in rows],
                identity=identity,
                expected_versions=versions,
            )
            metadata = {}
        else:
            result = project_territory(
                [codec.event(row["payload"]) for row in rows],
                identity=identity,
                coverage=TerritoryCoverage(**stream["coverage"]),
                cut=ConfirmedCut(scope_id, stream["revision"], stream["through_ms"]),
            )
            metadata = {"coverage": asdict(result.coverage), "peaks": result.peaks}
        await self.rows(
            """
            INSERT INTO activity_stat_checkpoint
                (generation_id,kind,scope_id,revision,through_ms,metadata)
            VALUES (:gid,:kind,:scope,:revision,:at,CAST(:metadata AS jsonb))
            ON CONFLICT(generation_id,kind,scope_id) DO UPDATE
            SET revision=EXCLUDED.revision,through_ms=EXCLUDED.through_ms,metadata=EXCLUDED.metadata
        """,
            {
                **params,
                "revision": stream["revision"],
                "at": stream["through_ms"],
                "metadata": json.dumps(metadata),
            },
        )
        if kind == "WALK":
            await self.rows(
                """
                DELETE FROM activity_walk_contribution WHERE generation_id=:gid AND scope_id=:scope
            """,
                params,
            )
            for contribution in result.contributions:
                await self.rows(
                    """
                    INSERT INTO activity_walk_contribution
                        (generation_id,scope_id,owner_id,analysis_id,payload)
                    VALUES (:gid,:scope,:owner,:analysis,CAST(:payload AS jsonb))
                """,
                    {
                        **params,
                        "owner": contribution.source.session.owner_id,
                        "analysis": contribution.source.analysis_id,
                        "payload": codec.encode(contribution),
                    },
                )
        else:
            await self.rows(
                """
                DELETE FROM activity_holding_period WHERE generation_id=:gid AND scope_id=:scope
            """,
                params,
            )
            for period in result.periods:
                await self.rows(
                    """
                    INSERT INTO activity_holding_period
                        (generation_id,scope_id,start_event_id,site_id,pet_id,started_ms,ended_ms,payload)
                    VALUES (:gid,:scope,:event,:site,:pet,:start,:end,CAST(:payload AS jsonb))
                """,
                    {
                        **params,
                        "event": period.period_id[1],
                        "site": period.site_id,
                        "pet": period.pet_id,
                        "start": period.started_ms,
                        "end": period.ended_ms,
                        "payload": codec.encode(period),
                    },
                )
        await self._mark_applied(params, stream["revision"])
        return True

    async def _mark_applied(self, params, revision):
        await self.rows(
            """
            INSERT INTO activity_stat_applied(generation_id,kind,scope_id,revision)
            SELECT :gid,kind,scope_id,revision FROM activity_stat_change
            WHERE kind=:kind AND scope_id=:scope AND revision<=:revision ON CONFLICT DO NOTHING
        """,
            {**params, "revision": revision},
        )

    async def read(self, generation_id, kind, scope_id):
        """Read persisted output plus lineage consistently, without rerunning the projector."""
        identity, versions = await self.generation(generation_id)
        params = {"gid": generation_id, "kind": kind, "scope": scope_id}
        checkpoint = (
            await self.rows(
                """
            SELECT * FROM activity_stat_checkpoint
            WHERE generation_id=:gid AND kind=:kind AND scope_id=:scope
        """,
                params,
            )
        ).one_or_none()
        if checkpoint is None:
            return None
        changes = await self.changes(kind, scope_id, checkpoint["revision"])
        if kind == "WALK":
            rows = await self.rows(
                """
                SELECT payload FROM activity_walk_contribution WHERE generation_id=:gid AND scope_id=:scope
            """,
                params,
            )
            return WalkProjection(
                identity,
                versions,
                tuple(codec.contribution(r["payload"]) for r in rows),
                tuple(codec.selection(r["payload"]) for r in changes),
            )
        rows = await self.rows(
            """
            SELECT payload FROM activity_holding_period WHERE generation_id=:gid AND scope_id=:scope
            ORDER BY (payload->>'start_revision')::bigint,site_id COLLATE "C"
        """,
            params,
        )
        return TerritoryProjection(
            identity,
            TerritoryCoverage(**checkpoint["metadata"]["coverage"]),
            ConfirmedCut(scope_id, checkpoint["revision"], checkpoint["through_ms"]),
            tuple(codec.period(r["payload"]) for r in rows),
            tuple(tuple(v) for v in checkpoint["metadata"]["peaks"]),
            tuple(codec.event(r["payload"]) for r in changes),
        )

    async def progress(self, generation_id, kind, scope_id):
        """Freshness relative to the durable source, not to undiscovered client uploads."""
        await self.generation(generation_id)
        row = (
            await self.rows(
                """
            SELECT s.revision AS source_revision,s.through_ms AS source_through_ms,
                c.revision AS applied_revision,c.through_ms AS confirmed_through_ms
            FROM activity_stat_stream s LEFT JOIN activity_stat_checkpoint c
                ON c.kind=s.kind AND c.scope_id=s.scope_id AND c.generation_id=:gid
            WHERE s.kind=:kind AND s.scope_id=:scope
        """,
                {"gid": generation_id, "kind": kind, "scope": scope_id},
            )
        ).one_or_none()
        require(row is not None, "unknown_statistics_stream")
        status = (
            "PENDING"
            if row["applied_revision"] is None
            else (
                "READY"
                if (row["source_revision"], row["source_through_ms"])
                == (row["applied_revision"], row["confirmed_through_ms"])
                else "STALE"
            )
        )
        return {"status": status, **dict(row)}


async def run_pending(sessions, generation_id, *, limit=100):
    """One transaction per scope; invoke periodically or from a CLI/job host."""
    identifier(generation_id)
    async with sessions.begin() as session:
        pending = await PostgresStatisticsTransaction(session).pending(generation_id, limit)
    completed = 0
    for row in pending:
        async with sessions.begin() as session:
            completed += await PostgresStatisticsTransaction(session).refresh(
                generation_id,
                row["kind"],
                row["scope_id"],
            )
    return completed
