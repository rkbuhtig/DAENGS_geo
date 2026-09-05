"""GPS simulator adapter for the shared observation-only selector."""
from app.features.walk.storyboard_selection import ReferenceWalk, SelectionPolicy, select_nodes

__all__ = ["ReferenceWalk", "SelectionPolicy", "route_nodes", "select"]

def route_nodes(artifacts):
    nodes, offset, block, previous = [], 0.0, -1, None
    for segment in artifacts.computed.trail.segments:
        if previous != (segment.chain_index, segment.a.client_seq):
            block += 1
            nodes.append(node(segment.a, offset, block, artifacts))
        offset += segment.dist if segment.moving else 0
        end = node(segment.b, offset, block, artifacts)
        end.update(speed=segment.dist/segment.dt, duration_s=segment.dt,
                   start_s=(segment.a.at-artifacts.observed.started_at).total_seconds())
        nodes.append(end)
        previous = (segment.chain_index, segment.b.client_seq)
    return nodes


def node(fix, offset, block, artifacts):
    return {"route_m": offset, "block": block,
            "elapsed_s": (fix.at-artifacts.observed.started_at).total_seconds(),
            "location": {"lat": fix.lat, "lng": fix.lng, "accuracy_m": fix.accuracy_m,
                         "captured_at": fix.at.isoformat()}}


def select(artifacts, entries, policy, references):
    return select_nodes(route_nodes(artifacts), entries, policy, references,
                        session_id=artifacts.scenario["session_id"],
                        pet_id=artifacts.scenario["dog_id"], started_at=artifacts.observed.started_at)
