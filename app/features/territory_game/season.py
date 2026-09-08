"""Deterministic territory game. No clock, database, network or app identity imports.

The adapter supplies trusted time/contact/photo evidence. The local lab supplies fakes.
Point numerators stay integral: queries and event splitting cannot introduce rounding.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from math import isfinite

from app.features.territory_game.policy import (
    DAY_MS,
    HOUR_MS,
    POINT_DENOMINATOR,
    GameError,
    Ownership,
    OwnershipCandidate,
    Rules,
    Score,
    SeasonContext,
    SiteSnapshot,
    is_protected,
    plan_finalization,
    plan_ownership,
    protected_until,
    require,
    settle,
)

# Existing local-lab import paths remain compatible; server adapters import policy directly.
__all__ = [
    "DAY_MS",
    "HOUR_MS",
    "POINT_DENOMINATOR",
    "Game",
    "GameError",
    "Rules",
    "Score",
    "require",
]


@dataclass
class Game:
    season_id: str
    starts_ms: int
    ends_ms: int
    now_ms: int
    rules: Rules
    pets: dict[str, str]
    sites: dict[str, dict]
    scores: dict[str, Score]
    status: str = "ACTIVE"
    sessions: dict[str, dict] = field(default_factory=dict)
    attempts: dict[str, dict] = field(default_factory=dict)
    captures: dict[str, str] = field(default_factory=dict)
    rewarded_days: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)

    @classmethod
    def create(cls, season_id, starts_ms, ends_ms, pets, site_ids, rules=None):
        require(bool(season_id.strip()), "empty_season")
        require(
            type(starts_ms) is int and type(ends_ms) is int and 0 <= starts_ms < ends_ms,
            "invalid_season_interval",
        )
        require(
            bool(pets) and all(k.strip() and v.strip() for k, v in pets.items()), "invalid_pets"
        )
        require(
            bool(site_ids)
            and len(set(site_ids)) == len(site_ids)
            and all(s.strip() for s in site_ids),
            "invalid_sites",
        )
        return cls(
            season_id,
            starts_ms,
            ends_ms,
            starts_ms,
            rules or Rules(),
            dict(pets),
            {s: {"owner": None, "version": 0} for s in site_ids},
            {p: Score(last_ms=starts_ms) for p in pets},
        )

    def serialize(self):
        return asdict(self)

    @classmethod
    def restore(cls, data):
        data = deepcopy(data)
        data["rules"] = Rules(**data["rules"])
        data["scores"] = {p: Score(**s) for p, s in data["scores"].items()}
        return cls(**data)

    def _context(self):
        return SeasonContext(self.season_id, self.starts_ms, self.ends_ms, self.rules, self.status)

    def _settle(self, pet, at_ms):
        self.scores[pet] = settle(self.scores[pet], at_ms, self.rules)

    def _event(self, kind, **values):
        self.events.append(
            {"seq": len(self.events) + 1, "kind": kind, "at_ms": self.now_ms, **values}
        )

    def _owned(self, attempt):
        owner = self.sites[attempt["site_id"]]["owner"]
        return owner and owner["pet_id"] == attempt["pet_id"]

    def _protected(self, site, pet):
        owner = Ownership(**site["owner"]) if site["owner"] else None
        return is_protected(owner, pet, self.now_ms, self.rules)

    def _grant(self, attempt, certification):
        site = self.sites[attempt["site_id"]]
        old = Ownership(**site["owner"]) if site["owner"] else None
        pet = attempt["pet_id"]
        affected = {pet} | ({old.pet_id} if old else set())
        day_key = f"{pet}\n{attempt['site_id']}\n{self.now_ms // DAY_MS}"
        verified = certification == "VERIFIED"
        candidate = OwnershipCandidate(
            self.season_id,
            f"photo:{attempt['capture_id']}" if verified else f"mark:{attempt['id']}",
            attempt["site_id"],
            site["version"],
            pet,
            attempt["session_id"],
            attempt["id"],
            certification,
            "PHOTO_VERIFIED" if verified else "MARK",
        )
        plan = plan_ownership(
            self._context(),
            SiteSnapshot(self.season_id, attempt["site_id"], site["version"], old),
            candidate,
            {p: self.scores[p] for p in affected},
            at_ms=self.now_ms,
            bonus_already_paid=day_key in self.rewarded_days,
        )
        site["owner"] = asdict(plan.after.owner)
        site["version"] = plan.after.version
        for account in plan.accounts:
            self.scores[account.pet_id] = account.score
        attempt["expected_version"] = site["version"]
        attempt["disposition"] = "GRANTED"
        if plan.bonus_key is not None:
            self.rewarded_days.append(day_key)
        if plan.kind != "UNCHANGED":
            self._event(
                plan.kind,
                site_id=attempt["site_id"],
                attempt_id=attempt["id"],
                pet_id=pet,
                previous_pet_id=old.pet_id if old else None,
                bonus=plan.bonus,
            )

    def _session(self, session_id, recording=False):
        require(session_id in self.sessions, "unknown_session")
        session = self.sessions[session_id]
        if recording:
            require(session["phase"] == "RECORDING", "not_recording")
        return session

    def _contact(self, command):
        distance = command.get("distance_m", 0)
        accuracy = command.get("accuracy_m", 5)
        age = command.get("contact_age_ms", 0)
        require(all(isfinite(v) and v >= 0 for v in (distance, accuracy, age)), "invalid_contact")
        require(command.get("trusted", True) and age <= 30_000, "untrusted_contact")
        require(distance + accuracy <= 20, "site_not_ready")

    def _mark(self, command):
        session_id, pet, site_id = (command[k] for k in ("session_id", "pet_id", "site_id"))
        session = self._session(session_id)
        require(site_id in self.sites, "unknown_site")
        require(pet in session["pet_ids"], "ineligible_pet")
        for attempt in self.attempts.values():
            if (attempt["session_id"], attempt["site_id"]) == (session_id, site_id):
                require(attempt["pet_id"] == pet, "attempt_identity_conflict")
                return {"attempt_id": attempt["id"], "disposition": attempt["disposition"]}
        self._session(session_id, recording=True)
        self._contact(command)
        site = self.sites[site_id]
        require(not self._protected(site, pet), "protected")
        owner = site["owner"]
        disposition = (
            "GRANTED"
            if owner is None
            else "ALREADY_OWNED"
            if owner["pet_id"] == pet
            else "PHOTO_REQUIRED"
            if owner["certification"] == "VERIFIED" or self.rules.version == "certified-protection-v2"
            else "POLICY_UNDECIDED"
        )
        attempt_id = command["attempt_id"]
        require(attempt_id not in self.attempts, "attempt_id_reused")
        attempt = {
            "id": attempt_id,
            "session_id": session_id,
            "pet_id": pet,
            "site_id": site_id,
            "expected_version": site["version"],
            "disposition": disposition,
            "photo": "NOT_SUBMITTED",
            "capture_id": None,
            "resolution_code": None,
        }
        self.attempts[attempt_id] = attempt
        if disposition == "GRANTED":
            self._grant(attempt, "UNVERIFIED")
        return {"attempt_id": attempt_id, "disposition": disposition}

    def _photo(self, command):
        require(command["attempt_id"] in self.attempts, "unknown_attempt")
        attempt = self.attempts[command["attempt_id"]]
        capture_id = command["capture_id"]
        if command["action"] == "submit":
            if attempt["capture_id"] == capture_id:
                if attempt["photo"] == "RETRY_PENDING":
                    attempt["photo"] = "PENDING"
                return {"photo": attempt["photo"]}
            v2 = self.rules.version == "certified-protection-v2"
            require(v2 or not attempt["resolution_code"], "attempt_closed")
            self._session(attempt["session_id"], recording=True)
            self._contact(command)
            require(
                attempt["photo"] != "PENDING"
                if v2
                else attempt["photo"] in {"NOT_SUBMITTED", "REJECTED"},
                "photo_not_available",
            )
            if v2:
                site = self.sites[attempt["site_id"]]
                require(not self._protected(site, attempt["pet_id"]), "protected")
                require(
                    not (self._owned(attempt) and site["owner"]["certification"] == "VERIFIED"),
                    "already_certified",
                )
                attempt["expected_version"] = site["version"]
                attempt["resolution_code"] = None
            require(capture_id not in self.captures, "capture_reused")
            self.captures[capture_id] = attempt["id"]
            attempt.update(capture_id=capture_id, photo="PENDING")
            return {"photo": "PENDING"}
        require(attempt["capture_id"] == capture_id, "stale_capture")
        if attempt["photo"] == "VERIFIED":
            return {"photo": "VERIFIED", "resolution_code": attempt["resolution_code"]}
        require(attempt["photo"] == "PENDING", "photo_not_pending")
        outcome = command["outcome"]
        require(outcome in {"ACCEPTED", "REJECTED", "RETRYABLE_FAILURE"}, "invalid_outcome")
        if outcome != "ACCEPTED":
            attempt["photo"] = "REJECTED" if outcome == "REJECTED" else "RETRY_PENDING"
            return {"photo": attempt["photo"]}
        # Photo evidence remains verified even when it cannot grant ownership.
        attempt["photo"] = "VERIFIED"
        site = self.sites[attempt["site_id"]]
        owner = site["owner"]
        reason = None
        if site["version"] != attempt["expected_version"]:
            reason = "site_changed"
        elif self._protected(site, attempt["pet_id"]):
            reason = "protected"
        elif (
            self.rules.version != "certified-protection-v2"
            and owner
            and not self._owned(attempt)
            and owner["session_id"] == attempt["session_id"]
        ):
            reason = "new_session_required"
        if reason:
            attempt["resolution_code"] = reason
            self._event("CLAIM_NOT_GRANTED", attempt_id=attempt["id"], reason=reason)
        elif not owner or not self._owned(attempt) or owner["certification"] != "VERIFIED":
            self._grant(attempt, "VERIFIED")
        return {"photo": "VERIFIED", "resolution_code": reason}

    def _finish(self):
        self.now_ms = self.ends_ms
        plan = plan_finalization(self._context(), self.scores, at_ms=self.ends_ms)
        self.scores = {r.pet_id: r.score for r in plan.results}
        self.results = self.standings()
        self.scores = {a.pet_id: a.score for a in plan.accounts}
        self.status = "FINALIZED"
        for attempt in self.attempts.values():
            if attempt["photo"] in {"PENDING", "RETRY_PENDING"}:
                attempt["resolution_code"] = "season_ended"
        for session in self.sessions.values():
            session["phase"] = "ENDED"
        for site in self.sites.values():
            if site["owner"]:
                site["version"] += 1
            site["owner"] = None
        self._event("SEASON_FINALIZED")

    def transition(self, command, *, at_ms):
        """Return a new state/result. Failure never mutates the caller's state."""
        require(type(at_ms) is int and at_ms >= self.now_ms, "time_reversed")
        require(self.status == "ACTIVE", "season_ended")
        result = deepcopy(self)
        if at_ms >= self.ends_ms:
            require(command["action"] in {"advance", "finalize"}, "season_ended")
            result._finish()
            return result, {"status": "FINALIZED"}
        require(command["action"] != "finalize", "season_not_ended")
        result.now_ms = at_ms
        return result, result._dispatch(command)

    def _dispatch(self, command):
        action = command["action"]
        if action == "advance":
            return {"now_ms": self.now_ms}
        if action == "start_session":
            sid, pet_ids = command["session_id"], command["pet_ids"]
            require(
                bool(pet_ids)
                and len(set(pet_ids)) == len(pet_ids)
                and set(pet_ids) <= self.pets.keys(),
                "invalid_participants",
            )
            if sid in self.sessions:
                require(self.sessions[sid]["pet_ids"] == pet_ids, "session_identity_conflict")
            else:
                self.sessions[sid] = {"pet_ids": list(pet_ids), "phase": "RECORDING"}
            return {"session_id": sid}
        if action == "phase":
            session = self._session(command["session_id"])
            phase = command["phase"]
            require(phase in {"RECORDING", "PAUSED", "ENDED"}, "invalid_phase")
            require(session["phase"] != "ENDED" or phase == "ENDED", "session_ended")
            session["phase"] = phase
            return {"phase": phase}
        if action == "mark":
            return self._mark(command)
        if action in {"submit", "resolve"}:
            return self._photo(command)
        raise GameError("unknown_action")

    def standings(self):
        projected = deepcopy(self)
        rows = []
        for pet in projected.scores:
            projected._settle(pet, min(self.now_ms, self.ends_ms))
            score = projected.scores[pet]
            total = score.bonus * POINT_DENOMINATOR + score.holding_units
            rows.append(
                {"pet_id": pet, "name": self.pets[pet], **asdict(score), "total_units": total}
            )
        rows.sort(key=lambda r: (-r["total_units"], r["pet_id"]))
        rank = 0
        previous = None
        for index, row in enumerate(rows):
            if row["total_units"] != previous:
                rank = index + 1
            previous = row["total_units"]
            row["rank"] = rank
            row["points"] = row["total_units"] / POINT_DENOMINATOR
            row["holding_points"] = row["holding_units"] / POINT_DENOMINATOR
            # Exact values are strings over HTTP, avoiding JavaScript's 53-bit limit.
            row["total_units"] = str(row["total_units"])
            row["holding_units"] = str(row["holding_units"])
            row["multiplier"] = self.rules.multiplier(row["scoring_count"]) / 10_000
        return rows

    def view(self):
        return {
            "season_id": self.season_id,
            "starts_ms": self.starts_ms,
            "ends_ms": self.ends_ms,
            "now_ms": self.now_ms,
            "status": self.status,
            "rules": asdict(self.rules),
            "pets": dict(self.pets),
            "sites": {
                key: {
                    **deepcopy(site),
                    "protected_until_ms": protected_until(Ownership(**site["owner"]), self.rules)
                    if site["owner"]
                    else None,
                }
                for key, site in self.sites.items()
            },
            "sessions": deepcopy(self.sessions),
            "attempts": deepcopy(self.attempts),
            "standings": deepcopy(self.results) if self.status == "FINALIZED" else self.standings(),
            "events": deepcopy(self.events),
        }
