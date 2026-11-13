import unittest
from datetime import datetime, timezone

from dispatch_scenarios.scenario import Scenario, open_edges


class ScenarioTests(unittest.TestCase):
    def test_closed_roads_are_excluded(self):
        scenario = Scenario("s1", datetime.now(timezone.utc), (("a", "b", True), ("b", "c", False)))
        self.assertEqual({("a", "b")}, open_edges(scenario))
