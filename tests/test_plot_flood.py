"""验证地块受淹面积统计的几何、证据与解释边界。"""

import copy
import json
import unittest
from pathlib import Path

from dispatch_scenarios.analysis import plot_flood_summary, summarize


def tables_with(tiles, plots=None, checks=None):
    return {"tiles": tiles, "plots": plots or [], "checks": checks or []}


def tile(tile_id, values, cell_size=10, origin=(0, 0), priority=0, day="2025-06-01",
         version="wet-v1"):
    return {"tile_id": tile_id, "day": day, "origin_x": origin[0], "origin_y": origin[1],
            "cell_size": cell_size, "rows": len(values), "cols": len(values[0]),
            "values": values, "priority": priority, "classification_version": version}


def plot(plot_id, xmin, ymin, xmax, ymax):
    return {"plot_id": plot_id, "xmin": xmin, "ymin": ymin,
            "xmax": xmax, "ymax": ymax}


class PlotAreaTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(
            (Path(__file__).resolve().parents[1] / "fixtures/dataset.json").read_text())

    def test_overlapping_tiles_do_not_double_count(self):
        tiles = [tile("a", [[1, 1], [1, 1]]),
                 tile("b", [[1, 1], [1, 1]], origin=(10, 0), priority=1)]
        summary = plot_flood_summary(tables_with(tiles, [plot("p", 0, 0, 20, 20)]))
        row = summary["days"][0]["plots"][0]
        self.assertEqual(400, row["plot_area"])
        self.assertEqual(400, row["wet_area"])
        self.assertEqual(400, row["wet_area_upper"])

    def test_half_cell_shift_allocates_exact_fractions(self):
        tiles = [tile("a", [[1, 1]])]
        summary = plot_flood_summary(tables_with(tiles, [plot("p", 5, 0, 15, 10)]))
        row = summary["days"][0]["plots"][0]
        self.assertEqual(100, row["plot_area"])
        self.assertEqual(100, row["wet_area"])
        tiles = [tile("a", [[1, 0]])]
        summary = plot_flood_summary(tables_with(tiles, [plot("p", 5, 0, 15, 10)]))
        row = summary["days"][0]["plots"][0]
        self.assertEqual(50, row["wet_area"])
        self.assertEqual(50, row["dry_area"])

    def test_mixed_resolution_same_day_uses_priority_not_sum(self):
        tiles = [tile("coarse", [[0, 0], [0, 0]], cell_size=10, priority=0),
                 tile("fine", [[1, 1], [1, 1]], cell_size=5, origin=(10, 0), priority=1)]
        summary = plot_flood_summary(tables_with(tiles, [plot("p", 0, 0, 20, 20)]))
        row = summary["days"][0]["plots"][0]
        self.assertEqual(400, row["plot_area"])
        self.assertEqual(100, row["wet_area"])
        self.assertIn("fine", row["winning_tile_ids"])
        self.assertIn("coarse", row["winning_tile_ids"])

    def test_plot_crossing_tile_boundary_is_not_double_counted(self):
        tiles = [tile("a", [[1, 1], [1, 1]]),
                 tile("b", [[1, 1], [1, 1]], origin=(20, 0))]
        summary = plot_flood_summary(tables_with(tiles, [plot("p", 5, 5, 35, 15)]))
        row = summary["days"][0]["plots"][0]
        self.assertEqual(300, row["plot_area"])
        self.assertEqual(300, row["wet_area"])

    def test_plot_extending_beyond_coverage_reports_unobserved(self):
        tiles = [tile("a", [[1, 1], [1, 1]])]
        summary = plot_flood_summary(tables_with(tiles, [plot("p", 0, 0, 40, 20)]))
        row = summary["days"][0]["plots"][0]
        self.assertEqual(800, row["plot_area"])
        self.assertEqual(400, row["wet_area"])
        self.assertEqual(400, row["unobserved_area"])
        self.assertEqual(800, row["wet_area_upper"])

    def test_unknown_is_reported_as_range_not_dry(self):
        tiles = [tile("a", [[1, None]])]
        summary = plot_flood_summary(tables_with(tiles, [plot("p", 0, 0, 20, 10)]))
        row = summary["days"][0]["plots"][0]
        self.assertEqual(100, row["wet_area"])
        self.assertEqual(0, row["dry_area"])
        self.assertEqual(100, row["unknown_area"])
        self.assertEqual(100, row["wet_area_lower"])
        self.assertEqual(200, row["wet_area_upper"])

    def test_high_priority_null_is_not_backfilled_by_lower_tile(self):
        tiles = [tile("low", [[1, 1]], priority=0),
                 tile("high", [[None, None]], priority=1)]
        summary = plot_flood_summary(tables_with(tiles, [plot("p", 0, 0, 20, 10)]))
        row = summary["days"][0]["plots"][0]
        self.assertEqual(0, row["wet_area"])
        self.assertEqual(200, row["unknown_area"])
        self.assertEqual(0, row["dry_area"])

    def test_equal_priority_conflict_is_not_resolved_silently(self):
        tiles = [tile("a", [[1, 1]], priority=2),
                 tile("b", [[0, 1]], priority=2)]
        summary = plot_flood_summary(tables_with(tiles, [plot("p", 0, 0, 20, 10)]))
        day = summary["days"][0]
        row = day["plots"][0]
        self.assertEqual(100, row["conflict_area"])
        self.assertEqual(100, row["wet_area"])
        self.assertEqual(200, row["wet_area_upper"])
        self.assertEqual(["a", "b"], day["conflicts"][0]["tile_ids"])
        self.assertEqual([0, 1], day["conflicts"][0]["classes"])
        self.assertEqual(100, day["conflicts"][0]["area"])

    def test_overlapping_plots_are_rejected(self):
        with self.assertRaises(ValueError):
            plot_flood_summary(tables_with(
                [tile("a", [[1, 1], [1, 1]])],
                [plot("p", 0, 0, 15, 15), plot("q", 10, 10, 20, 20)]))

    def test_fixture_areas_match_total_plot_area(self):
        summary = plot_flood_summary(self.fixture["tables"])
        for day in summary["days"]:
            for row in day["plots"]:
                self.assertEqual(row["plot_area"], 348)
                self.assertEqual(
                    row["plot_area"],
                    row["observed_area"] + row["unobserved_area"]
                    + row["unknown_area"] + row["conflict_area"])
                self.assertEqual(row["observed_area"], row["wet_area"] + row["dry_area"])
                self.assertEqual(row["wet_area_upper"],
                                 row["wet_area"] + row["undetermined_area"])

    def test_tile_summary_is_marked_as_duplicating_overlap(self):
        summary = summarize(self.fixture["tables"])
        self.assertIn("不能当作地块受淹面积", summary["tile_note"])
        self.assertTrue(summary["tiles"])


class ComparisonTests(unittest.TestCase):
    def test_different_classification_versions_block_change(self):
        tiles = [tile("a", [[1]], day="2025-06-01", version="wet-v1"),
                 tile("b", [[1]], day="2025-06-03", version="wet-v2")]
        summary = plot_flood_summary(tables_with(tiles, [plot("p", 0, 0, 10, 10)]))
        change = summary["changes"][0]
        self.assertFalse(change["comparable"])
        self.assertIsNone(change["plots"][0]["wet_change_in_common"])

    def test_no_common_observation_blocks_plot_change(self):
        tiles = [tile("a", [[1]], origin=(0, 0), day="2025-06-01"),
                 tile("b", [[1]], origin=(10, 0), day="2025-06-03")]
        summary = plot_flood_summary(
            tables_with(tiles, [plot("p", 0, 0, 20, 10)]))
        row = summary["changes"][0]["plots"][0]
        self.assertFalse(row["comparable"])
        self.assertEqual(0, row["both_observed_area"])

    def test_clearer_new_imagery_is_not_expansion(self):
        tiles = [tile("a", [[1, None]], day="2025-06-01"),
                 tile("b", [[1, 1]], day="2025-06-03")]
        summary = plot_flood_summary(
            tables_with(tiles, [plot("p", 0, 0, 20, 10)]))
        change = summary["changes"][0]
        row = change["plots"][0]
        self.assertEqual(100, row["both_observed_area"])
        self.assertEqual(0, row["wet_change_in_common"])
        self.assertIn("共同有效观测范围", change["interpretation"])

    def test_change_range_brackets_point_estimate(self):
        tiles = [tile("a", [[1, 0]], day="2025-06-01"),
                 tile("b", [[1, 1]], day="2025-06-03")]
        summary = plot_flood_summary(
            tables_with(tiles, [plot("p", 0, 0, 20, 10)]))
        row = summary["changes"][0]["plots"][0]
        self.assertLessEqual(row["wet_change_lower"], row["wet_change_in_common"])
        self.assertGreaterEqual(row["wet_change_upper"], row["wet_change_in_common"])


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(
            (Path(__file__).resolve().parents[1] / "fixtures/dataset.json").read_text())

    def test_purposive_checks_state_what_they_support(self):
        summary = plot_flood_summary(
            tables_with([tile("a", [[1, 1]])], [plot("p", 0, 0, 20, 10)],
                        [{"check_id": "c", "plot_id": "p", "x": 5, "y": 5,
                           "day": "2025-06-01", "wet": False,
                           "selection_reason": "巡查优先关注地块"}]))
        use = summary["checks"]["use"]
        for key in ("selection", "supports", "does_not_support"):
            self.assertTrue(use[key])
        record = summary["days"][0]["checks"]["records"][0]
        self.assertTrue(record["usable_for_comparison"])
        self.assertNotEqual(record["raster_wet"], record["field_wet"])

    def test_check_on_unknown_pixel_is_not_used_as_truth(self):
        summary = plot_flood_summary(
            tables_with([tile("a", [[None, 1]])], [plot("p", 0, 0, 20, 10)],
                        [{"check_id": "c", "plot_id": "p", "x": 5, "y": 5,
                           "day": "2025-06-01", "wet": True,
                           "selection_reason": "巡查优先关注地块"}]))
        record = summary["days"][0]["checks"]["records"][0]
        self.assertFalse(record["usable_for_comparison"])
        self.assertTrue(record["reasons"])
        self.assertIn("c", summary["checks"]["unmatched_check_ids"])

    def test_check_outside_plot_is_rejected(self):
        summary = plot_flood_summary(
            tables_with([tile("a", [[1, 1]])], [plot("p", 0, 0, 20, 10)],
                        [{"check_id": "c", "plot_id": "p", "x": 25, "y": 5,
                           "day": "2025-06-01", "wet": True,
                           "selection_reason": "巡查优先关注地块"}]))
        record = summary["days"][0]["checks"]["records"][0]
        self.assertFalse(record["usable_for_comparison"])
        self.assertIn("核实点不在地块范围内", record["reasons"])

    def test_check_on_day_without_raster_is_reported_not_dropped(self):
        summary = plot_flood_summary(
            tables_with([tile("a", [[1, 1]])], [plot("p", 0, 0, 20, 10)],
                        [{"check_id": "c", "plot_id": "p", "x": 5, "y": 5,
                           "day": "2025-06-09", "wet": True,
                           "selection_reason": "巡查优先关注地块"}]))
        self.assertEqual(["c"], summary["checks"]["unmatched_check_ids"])
        self.assertEqual("no_raster_for_day",
                         summary["checks"]["unmatched_records"][0]["raster_state"])
        self.assertEqual(0, summary["checks"]["usable_check_count"])

    def test_dispatch_keeps_plot_raster_and_area_evidence(self):
        summary = plot_flood_summary(self.fixture["tables"])
        latest = summary["dispatch"]["by_day"][summary["dispatch"]["latest_day"]]
        self.assertTrue(latest)
        for item in latest:
            self.assertIn("plot_id", item)
            self.assertTrue(item["tile_ids"])
            self.assertEqual(["wet-v1"], item["classification_versions"])
            self.assertLessEqual(item["wet_area_lower_m2"], item["wet_area_upper_m2"])
            self.assertIn("observed_fraction", item)
        self.assertIn("不接入地图", summary["dispatch"]["purpose"])


if __name__ == "__main__":
    unittest.main()
