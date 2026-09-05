"""Simulator boundary; generated route truth is never an input to the live adapter."""
from datetime import timedelta

from app.features.storyboard.scenes import StoryboardBundle, build_storyboard

__all__ = ["StoryboardBundle", "export_storyboard"]


def export_storyboard(artifacts, entries, selection, contexts):
    start = artifacts.observed.started_at
    return build_storyboard(artifacts.scenario["session_id"], start,
                            start+timedelta(seconds=artifacts.derived["truth_duration_s"]),
                            artifacts.computed.facts.moving_distance_m, entries, selection, contexts,
                            artifacts.computed.trail.gaps, synthetic=True)
