"""记录方案所用的信息时点。"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    known_at: datetime
    road_edges: tuple[tuple[str, str, bool], ...]


def open_edges(scenario: Scenario) -> set[tuple[str, str]]:
    return {(left, right) for left, right, open_now in scenario.road_edges if open_now}
