"""Finite HOW projection for a fixed writing selection; no model or scene edits.

The model sees short request-local aliases. Exact material/stamp versions and
full supports remain in the local manifest and StampTool, outside model input.
"""

import json
from copy import deepcopy

from .record_envelopes import payload_hash
from .stamp_storyboard import WRITE_PROMPT, writing_request
from .stamp_tool import StampRef

POLICY = {"version": "how-writing-v1", "scope": "fixed_stamps",
          "definitions": "once_per_exact_material_ref", "how_support": "retain_locally",
          "relations": "preserve", "non_how": "preserve"}


def json_size(value):
    """Exact minified UTF-8 JSON size, not a tokenizer or a provider usage estimate."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8"))


def _definition(material):
    kind, metrics = material["kind"], material["metrics"]
    result = {"kind": kind, "status": material["status"], "subject": material["subject"],
              "route_run": {"chain": material["support"]["chain_index"],
                            "run": material["support"]["how_run_index"]}}
    if kind == "turn":
        result.update({"direction": metrics["direction"],
                       "time_basis": "route_vertex_not_exact_turn_time"})
    elif kind == "local_stay":
        result["observed_window_s"] = metrics["observed_duration_s"]
        result["duration_basis"] = "bounded_observation_window_not_action_duration"
    elif kind == "retrace":
        result.update({"comparison": "adjacent_previous_leg_corridor",
                       "return_displacement_m": metrics["return_displacement_m"]})
    elif kind == "straight_run":
        result["shape"] = "approximately_straight"
    else:
        raise ValueError("unsupported HOW kind; a projector is required")
    # Do not turn missing accuracy into high confidence when dropping diagnostics.
    result["accuracy"] = {"p50_m": material["quality"]["accuracy_p50_m"],
                          "unknown_fixes": material["quality"]["unknown_accuracy_count"]}
    return result


def _statistics(baseline, compact):
    before, after = json_size(baseline), json_size(compact)
    uses = sum(len(s["how"]) for s in baseline["stamps"])
    definitions = len(compact["how_dictionary"])
    return {"measure": "minified_utf8_input_json_bytes", "before_bytes": before,
            "after_bytes": after, "reduction_pct": round(100 * (before - after) / before, 2),
            "how_definitions_before": uses, "how_definitions_after": definitions,
            "repeated_definitions_removed": uses - definitions, "how_links_preserved": uses,
            "stamp_count": len(baseline["stamps"]),
            "token_usage": None, "llm_calls": 0}


def prepare_comparison(tool, selected):
    """Build both writing inputs over exactly the same selected stamp versions.

    Existing writing_request owns order, required records, capacity and response
    schema. The caller chooses the selection; this projection never chooses it.
    """
    book = tool.dump()
    if book["source_kind"] != "record_how":
        raise ValueError("HOW writing projection requires record_how")
    baseline, response = writing_request(tool, tuple(selected))
    wanted = {s["id"] for s in baseline["stamps"]}
    refs = [r for r in tool.refs if r.id in wanted]
    catalog = {(m["ref"]["id"], m["ref"]["version"]): m
               for m in book["how_catalog"]["materials"]}
    dictionary, bindings, aliases, projected, audit = {}, {}, {}, [], []
    for stamp in baseline["stamps"]:
        # Keep original record text, time basis, past-action relations and WHERE
        # envelopes unchanged; this experiment only compacts HOW material.
        row = {k: deepcopy(v) for k, v in stamp.items()
               if k not in {"how", "how_limits", "available_at", "mode"}}
        row["how"] = []
        for member in stamp["how"]:
            ref = member["material_ref"]
            key = ref["id"], ref["version"]
            material = catalog[key]
            if key not in aliases:
                alias = f"h{len(aliases) + 1}"
                aliases[key] = alias
                dictionary[alias] = _definition(material)
                bindings[alias] = {"material_ref": deepcopy(ref), "stamp_ids": []}
            alias = aliases[key]
            bindings[alias]["stamp_ids"].append(stamp["id"])
            row["how"].append({"use": alias, "role": member["role"],
                               "relation": deepcopy(member["relation"])})
        projected.append(row)
        audit.append({"stamp_id": stamp["id"],
                      "record_and_when": "unchanged", "roles_and_relations": "unchanged",
                      "how_member_count": len(row["how"]),
                      "local_only": ["material_ref_versions", "support", "available_at",
                                     "geometry_diagnostics"]})
    compact = {"format": POLICY["version"], "mode": "post_walk", "actors": baseline["actors"],
               "how_limits": {**deepcopy(book["how_catalog"]["limits"]),
                              "cross_route_run_continuity": "not_established"},
               "how_dictionary": dictionary, "stamps": projected}
    manifest = {"source_version": tool.source_version, "policy": deepcopy(POLICY),
                "stamp_refs": [r.model_dump(mode="json") for r in refs],
                "how_bindings": bindings, "baseline_sha256": payload_hash(baseline),
                "compact_sha256": payload_hash(compact),
                "response_schema_sha256": payload_hash(response.model_json_schema()),
                "prompt_sha256": payload_hash({"prompt": WRITE_PROMPT})}
    return {"schema_version": "how-writing-comparison-v1", "status": "not_sent",
            "prompt": WRITE_PROMPT, "response_schema": response.model_json_schema(),
            "baseline_input": baseline, "compact_input": compact, "manifest": manifest,
            "projection_version": payload_hash(manifest), "audit": audit,
            "statistics": _statistics(baseline, compact)}


def verify_comparison(tool, saved):
    refs = [StampRef.model_validate(r) for r in saved["manifest"]["stamp_refs"]]
    rebuilt = prepare_comparison(tool, refs)
    if rebuilt != saved:
        raise ValueError("writing comparison changed or failed deterministic replay")
    return rebuilt


def comparison_display(comparison):
    """Disposable view using the same JSON encoder as the measured inputs.

    Re-stringifying floats in JavaScript would change 8.0 into 8 and produce a
    different byte count. These text/count pairs stay outside the model input.
    """
    baseline, compact = comparison["baseline_input"], comparison["compact_input"]

    def pair(before, after):
        return {key: {"text": json.dumps(value, ensure_ascii=False, indent=2),
                      "bytes": json_size(value)} for key, value in
                (("before", before), ("after", after))}

    by_stamp = {}
    for old, new in zip(baseline["stamps"], compact["stamps"]):
        uses = {h["use"] for h in new["how"]}
        excerpt = {"how_limits": compact["how_limits"], "how_dictionary": {
            k: v for k, v in compact["how_dictionary"].items() if k in uses
        }, "stamp": new}
        by_stamp[new["id"]] = pair(old, excerpt)
    return {"all": pair(baseline, compact), "by_stamp": by_stamp}


def resolve_how(tool, saved, alias):
    """Local inspection only. No model-triggered lookups or automatic HTTP calls."""
    checked = verify_comparison(tool, saved)
    binding = checked["manifest"]["how_bindings"].get(alias)
    if binding is None:
        raise ValueError("unknown request-local HOW alias")
    return next(m for m in tool.dump()["how_catalog"]["materials"]
                if m["ref"] == binding["material_ref"])
