"""Offline spatial/action pools and immutable stamps from the archived V3 vocabulary.

This adapter parses the finite archived vocabulary, not arbitrary user text or live GPS.
Space labels are not canonical place identities. Cache eviction is not spatial departure.
"""

from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime

from .selection_adapter import from_selection_case
from .storage import digest


@dataclass(frozen=True)
class StampPolicy:
    version: str = "archived-slot-stamp-v1"
    space_slots: int = 3
    action_slots: int = 2
    recent_space_s: int = 300
    recent_action_s: int = 600
    recent_spaces_per_stamp: int = 1


class SlotPool:
    """Bounded recent context, separate from an append-only experiment record history."""

    def __init__(self, name, capacity, max_age_s):
        if capacity < 1 or max_age_s < 0:
            raise ValueError("invalid slot policy")
        self.name, self.capacity, self.max_age_s = name, capacity, max_age_s
        self.slots, self.history, self.audit = OrderedDict(), [], []
        self.chain, self.clock = None, -1

    def advance(self, at_s, chain):
        if at_s < self.clock:
            raise ValueError("pool updates must be chronological")
        self.clock = at_s
        for key, value in list(self.slots.items()):
            reason = "chain_reset" if chain != self.chain else "expired"
            if chain != self.chain or at_s - value["observed_at_s"] > self.max_age_s:
                self.slots.pop(key)
                self.audit.append({"at_s": at_s, "key": key, "reason": reason})
        self.chain = chain

    def put(self, key, value, at_s, chain):
        self.advance(at_s, chain)
        record = {**deepcopy(value), "observed_at_s": at_s, "chain": chain}
        self.history.append(deepcopy(record))
        hit = key in self.slots
        self.slots.pop(key, None)
        self.slots[key] = record
        self.audit.append({"at_s": at_s, "key": key, "reason": "refresh" if hit else "admit"})
        if len(self.slots) > self.capacity:
            evicted, _ = self.slots.popitem(last=False)
            self.audit.append({"at_s": at_s, "key": evicted, "reason": "capacity_eviction"})

    def snapshot(self):
        return deepcopy(list(self.slots.values()))


def space_descriptor(label):
    commercial = {
        "등록 상가가 산재한 구간": "scattered",
        "등록 상가가 모인 구간": "clustered",
        "등록 상가가 적은 구간": "sparse",
    }
    if label in commercial:
        return {
            "key": "commerce:" + commercial[label],
            "tag": "commercial_background",
            "distribution": commercial[label],
            "label": label,
            "identity": "type_only",
        }
    if label.endswith(" 가까운 구간"):
        name = label.removesuffix(" 가까운 구간")
        if name not in {"늘벗근린공원", "독골근린공원", "양재천"}:
            raise ValueError("unsupported archived landmark label")
        return {
            "key": "label:" + name,
            "tag": "river" if name == "양재천" else "park",
            "label": name,
            "relation": "near",
            "identity": "source_label_only",
        }
    raise ValueError("unsupported archived space label")


def spatial_change(text):
    suffix = "으로 주변 특징이 바뀜"
    if text.endswith(suffix) and "에서 " in text:
        before, after = text.removesuffix(suffix).split("에서 ", 1)
        return {
            "type": "background_change",
            "from": space_descriptor(before),
            "to": space_descriptor(after),
        }
    if text == "양재천까지 거리가 줄었다가 다시 늘어남":
        return {
            "type": "distance_trend",
            "target_label": "양재천",
            "sequence": ["decreasing", "increasing"],
        }
    raise ValueError("unsupported archived spatial relation")


def action_descriptor(atom):
    codes = {
        "두부가 여기서 냄새를 맡았다": "sniff_recorded",
        "여기서 두부와 함께 사진을 찍었다": "photo_recorded",
    }
    if atom["text"] not in codes:
        raise ValueError("unsupported archived action; preserve unknown user text elsewhere")
    return {
        "code": codes[atom["text"]],
        "actor_ids": atom["subject_ids"],
        "record_text": atom["text"],
        "target": None,
    }


def build_stamps(case, policy=None):
    policy = policy or StampPolicy()
    # Validate archive provenance, bounds, roles and GPS chains with the existing adapter.
    from_selection_case(
        case,
        started_at=datetime.fromisoformat("2026-09-07T09:00+09:00"),
        session_id=case["id"],
        composition_mode="grouped",
    )
    packet = case["input"]
    space = SlotPool("space", policy.space_slots, policy.recent_space_s)
    action = SlotPool("action", policy.action_slots, policy.recent_action_s)
    stamps, previous_key, episode = [], None, None
    for event in sorted(packet["events"], key=lambda e: (e["end_s"], e["id"])):
        at, chain = event["end_s"], event["chain"]
        if space.chain != chain:
            previous_key, episode = None, None
        space.advance(at, chain)
        action.advance(at, chain)
        if not event["card_eligible"]:
            continue
        atoms = {a["id"]: a for a in event["evidence"]}
        primary = atoms[event["primary_evidence_id"]]
        background = atoms[event["id"] + ":where0"]
        descriptor = space_descriptor(background["text"])
        key = descriptor["key"]
        if previous_key != key or key not in space.slots:
            episode = {"event_id": event["id"], "source_segment_start_s": event["start_s"]}
        previous_key = key
        current = {
            "event_id": event["id"],
            "descriptor": descriptor,
            "support_s": [event["start_s"], event["end_s"]],
            "episode": deepcopy(episode),
        }
        space.put(key, current, at, chain)
        prior_actions = action.snapshot()
        action_value = action_descriptor(primary) if event["role"] == "action" else None
        if action_value:
            action.put(event["id"], {"event_id": event["id"], "action": action_value}, at, chain)
        recent = [s for s in reversed(space.snapshot()) if s["descriptor"]["key"] != key]
        recent = recent[: policy.recent_spaces_per_stamp]
        relations = []
        # Relationships are elapsed times, never durations of actions or proven continuous presence.
        if event["role"] == "action" and prior_actions:
            previous = prior_actions[-1]
            relations.append(
                {
                    "type": "after_action_record",
                    "event_id": previous["event_id"],
                    "action": previous["action"],
                    "elapsed_s": at - previous["observed_at_s"],
                }
            )
        if event["role"] == "action" and episode["event_id"] != event["id"]:
            relations.append(
                {
                    "type": "since_space_segment_start",
                    **deepcopy(episode),
                    "elapsed_s": at - episode["source_segment_start_s"],
                    "continuous_presence": "not_established",
                }
            )
        stamp = {
            "id": "stamp:" + event["id"],
            "trigger": event["role"],
            "required": event.get("required", False),
            "chain": chain,
            "anchor": {
                "event_id": event["id"],
                "support_s": [event["start_s"], at],
                "time_kind": "point" if event["start_s"] == at else "interval",
            },
            "who": event["who_ids"],
            "action": action_value,
            "where": {"current": current, "recent_observations": recent},
            "spatial_change": spatial_change(primary["text"])
            if event["role"] == "transition"
            else None,
            "relations": relations,
            "unavailable": ["coordinates", "weather", "view", "action_duration"],
        }
        refs = {event["id"]} | {s["event_id"] for s in recent} | {r["event_id"] for r in relations}
        stamps.append(
            {
                "snapshot": deepcopy(stamp),
                "sha256": digest(stamp),
                "source_event_ids": sorted(refs),
                "policy": policy.version,
            }
        )
    return {
        "version": "slot-stamp-materials-v1",
        "case": case["id"],
        "source_input_sha256": case["input_sha256"],
        "policy": asdict(policy),
        "actors": [{"id": a["id"], "label": a["text"]} for a in packet["actors"]],
        "gaps": packet["gaps"],
        "max_cards": packet["limits"]["scene_count_max"],
        "stamps": stamps,
        "pools": {
            "space": {"history": space.history, "audit": space.audit},
            "action": {"history": action.history, "audit": action.audit},
            "environment": {"status": "no_source", "history": [], "audit": []},
        },
    }


def compact_stamp(stamp):
    """Selected fields only; provenance hashes/history stay outside model input."""
    s = stamp["snapshot"]
    current = s["where"]["current"]
    result = {
        "id": s["id"],
        "tag": s["trigger"],
        "support_s": s["anchor"]["support_s"],
        "who": s["who"],
        "where": current["descriptor"],
    }
    if s["action"]:
        result["action"] = s["action"]
    if s["spatial_change"]:
        result["spatial_change"] = s["spatial_change"]
    if s["relations"]:
        result["relations"] = s["relations"]
    if s["where"]["recent_observations"]:
        result["recent_space_observations"] = [
            {
                "where": r["descriptor"],
                "seconds_ago": s["anchor"]["support_s"][1] - r["observed_at_s"],
            }
            for r in s["where"]["recent_observations"]
        ]
    return result
