"""按同日优先级精确叠加多分辨率瓦片，并把分类面积分配到地块。

坐标与像元边界均使用 Fraction 精确表示，避免半像元偏移和不同分辨率叠加时
产生浮点累积误差。瓦片像元按左闭右开区间解释；地块按闭区间包含判断。
"""

import math
from dataclasses import dataclass
from fractions import Fraction


def _exact(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)):
        raise ValueError(f"{label}不是有效数值")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{label}不是有限数值")
        # 使用最短十进制表示，避免把 JSON 中的 0.1 展开成二进制长尾。
        return Fraction(str(value))
    return Fraction(value)


def _positive_int(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}必须是正整数")
    if int(value) != value or value <= 0:
        raise ValueError(f"{label}必须是正整数")
    return int(value)


def area_number(value):
    """把精确面积转换为 JSON 数值；整数面积保持整数。"""
    return int(value) if value.denominator == 1 else float(value)


@dataclass(frozen=True)
class Tile:
    tile_id: str
    day: str
    origin_x: Fraction
    origin_y: Fraction
    cell_size: Fraction
    rows: int
    cols: int
    values: tuple
    priority: Fraction
    classification_version: str

    @property
    def x0(self):
        return self.origin_x

    @property
    def y0(self):
        return self.origin_y

    @property
    def x1(self):
        return self.origin_x + self.cols * self.cell_size

    @property
    def y1(self):
        return self.origin_y + self.rows * self.cell_size

    def covers(self, x, y):
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1

    def class_at(self, x, y):
        col = (x - self.x0) // self.cell_size
        row = (y - self.y0) // self.cell_size
        return self.values[row][col]


@dataclass(frozen=True)
class Plot:
    plot_id: str
    x0: Fraction
    y0: Fraction
    x1: Fraction
    y1: Fraction

    @property
    def area(self):
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def contains(self, x, y):
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1


@dataclass(frozen=True)
class DayRaster:
    day: str
    tiles: tuple
    classification_versions: tuple
    cell_sizes: tuple

    def point(self, x, y):
        return _point_class(self.tiles, x, y)


def _make_tile(row):
    tile_id = row["tile_id"]
    if not isinstance(tile_id, str) or not tile_id:
        raise ValueError("瓦片标识不能为空")
    day = row["day"]
    if not isinstance(day, str) or not day:
        raise ValueError("瓦片日期不能为空")
    cell_size = _exact(row["cell_size"], "瓦片分辨率")
    if cell_size <= 0:
        raise ValueError("瓦片分辨率或行数不合法")
    rows = _positive_int(row["rows"], "瓦片行数")
    cols = _positive_int(row["cols"], "瓦片列数")
    raw_values = row["values"]
    if not isinstance(raw_values, list) or len(raw_values) != rows:
        raise ValueError("瓦片分辨率或行数不合法")
    values = []
    for line in raw_values:
        if not isinstance(line, list) or len(line) != cols:
            raise ValueError("瓦片列数不合法")
        checked = []
        for value in line:
            if isinstance(value, bool) or value not in (0, 1, None):
                raise ValueError("未知积水分类值")
            checked.append(value)
        values.append(tuple(checked))
    version = row["classification_version"]
    if not isinstance(version, str) or not version:
        raise ValueError("瓦片分类口径不能为空")
    return Tile(tile_id, day, _exact(row["origin_x"], "瓦片原点 x"),
                _exact(row["origin_y"], "瓦片原点 y"), cell_size, rows, cols,
                tuple(values), _exact(row["priority"], "瓦片优先级"), version)


def build_day_rasters(tile_rows):
    """校验瓦片并返回 day -> DayRaster 映射。"""
    grouped = {}
    seen = set()
    for row in tile_rows:
        tile = _make_tile(row)
        if tile.tile_id in seen:
            raise ValueError("瓦片标识重复：" + tile.tile_id)
        seen.add(tile.tile_id)
        grouped.setdefault(tile.day, []).append(tile)
    rasters = {}
    for day in sorted(grouped):
        tiles = tuple(sorted(grouped[day], key=lambda item: item.tile_id))
        rasters[day] = DayRaster(
            day, tiles,
            tuple(sorted({tile.classification_version for tile in tiles})),
            tuple(sorted({tile.cell_size for tile in tiles})),
        )
    return rasters


def build_plots(plot_rows):
    """校验地块矩形，并拒绝重叠地块导致的面积重复分配。"""
    plots = []
    seen = set()
    for row in plot_rows:
        plot_id = row["plot_id"]
        if not isinstance(plot_id, str) or not plot_id:
            raise ValueError("地块标识不能为空")
        if plot_id in seen:
            raise ValueError("地块标识重复：" + plot_id)
        seen.add(plot_id)
        x0 = _exact(row["xmin"], "地块 xmin")
        y0 = _exact(row["ymin"], "地块 ymin")
        x1 = _exact(row["xmax"], "地块 xmax")
        y1 = _exact(row["ymax"], "地块 ymax")
        if x1 <= x0 or y1 <= y0:
            raise ValueError("地块范围不合法：" + plot_id)
        plots.append(Plot(plot_id, x0, y0, x1, y1))
    ordered = sorted(plots, key=lambda item: (item.x0, item.plot_id))
    active = []
    for plot in ordered:
        active = [other for other in active if other.x1 > plot.x0]
        for other in active:
            if min(plot.y1, other.y1) > max(plot.y0, other.y0):
                raise ValueError("地块相互重叠：" + other.plot_id + " / " + plot.plot_id)
        active.append(plot)
    return sorted(plots, key=lambda item: item.plot_id)


def _point_class(tiles, x, y):
    """返回点位上最高优先级的分类；同优先级分类冲突不擅自取值。

    较高优先级瓦片为 null 时该点无有效观测，不用较低优先级瓦片回填，
    避免把不同来源的观测缺口混成同一分类。
    """
    covering = [tile for tile in tiles if tile.covers(x, y)]
    if not covering:
        return {"state": "unobserved", "value": None, "classes": [],
                "tile_ids": [], "priority": None}
    best = max(tile.priority for tile in covering)
    top = [tile for tile in covering if tile.priority == best]
    values = {tile.class_at(x, y) for tile in top}
    known = sorted(value for value in values if value is not None)
    tile_ids = sorted(tile.tile_id for tile in top)
    if len(known) > 1:
        return {"state": "conflict", "value": None, "classes": known,
                "tile_ids": tile_ids, "priority": best}
    if known:
        return {"state": "observed", "value": known[0], "classes": known,
                "tile_ids": tile_ids, "priority": best}
    return {"state": "unknown", "value": None, "classes": [],
            "tile_ids": tile_ids, "priority": best}


def classify_point(rasters, day, x, y):
    """按某日叠加规则分类单点，供现场核实标签与栅格对照。"""
    if day not in rasters:
        return {"state": "no_raster_for_day", "value": None, "classes": [],
                "tile_ids": [], "priority": None}
    return rasters[day].point(_exact(x, "核实点 x"), _exact(y, "核实点 y"))


def _add_edges(start, cell_size, count, low, high, edges):
    first = max(0, math.ceil((low - start) / cell_size))
    last = min(count, math.floor((high - start) / cell_size))
    for index in range(first, last + 1):
        edges.add(start + index * cell_size)


def _empty_daily(plot):
    return {"plot": plot, "plot_area": Fraction(0), "covered_area": Fraction(0),
            "observed_area": Fraction(0), "unobserved_area": Fraction(0),
            "unknown_area": Fraction(0), "conflict_area": Fraction(0),
            "wet_area": Fraction(0), "dry_area": Fraction(0),
            "winning_tile_ids": set()}


def _empty_pair(plot):
    return {"plot": plot, "plot_area": plot.area, "both_observed_area": Fraction(0),
            "wet_area_a": Fraction(0), "wet_area_b": Fraction(0),
            "wet_to_wet_area": Fraction(0), "wet_to_dry_area": Fraction(0),
            "dry_to_wet_area": Fraction(0), "dry_to_dry_area": Fraction(0)}


def analyze_overlays(rasters, plots, pairs=()):
    """一次网格分解，同时得到每日地块统计与跨日公共观测范围统计。

    返回 (daily, pairs, conflicts)：daily[day][plot_id]、pairs[(a, b)][plot_id] 与
    conflicts[day] 列表。
    """
    days = sorted(rasters)
    daily = {day: {plot.plot_id: _empty_daily(plot) for plot in plots} for day in days}
    pair_stats = {(a, b): {plot.plot_id: _empty_pair(plot) for plot in plots}
                  for a, b in pairs}
    conflicts = {day: {} for day in days}
    if not plots or not days:
        return daily, pair_stats, conflicts

    global_x0 = min(plot.x0 for plot in plots)
    global_x1 = max(plot.x1 for plot in plots)
    x_edges = {global_x0, global_x1}
    for plot in plots:
        x_edges.add(plot.x0)
        x_edges.add(plot.x1)
    for day in days:
        for tile in rasters[day].tiles:
            _add_edges(tile.x0, tile.cell_size, tile.cols, global_x0, global_x1, x_edges)
    x_edges = sorted(edge for edge in x_edges if global_x0 <= edge <= global_x1)

    for left, right in zip(x_edges, x_edges[1:]):
        dx = right - left
        if dx <= 0:
            continue
        middle_x = (left + right) / 2
        relevant_plots = [plot for plot in plots if plot.x0 < right and plot.x1 > left]
        if not relevant_plots:
            continue
        active = {
            day: tuple(tile for tile in rasters[day].tiles
                        if tile.x0 < right and tile.x1 > left)
            for day in days
        }
        low_y = min(plot.y0 for plot in relevant_plots)
        high_y = max(plot.y1 for plot in relevant_plots)
        y_edges = {low_y, high_y}
        for plot in relevant_plots:
            y_edges.add(plot.y0)
            y_edges.add(plot.y1)
        for day in days:
            for tile in active[day]:
                _add_edges(tile.y0, tile.cell_size, tile.rows, low_y, high_y, y_edges)
        y_edges = sorted(edge for edge in y_edges if low_y <= edge <= high_y)

        for bottom, top in zip(y_edges, y_edges[1:]):
            dy = top - bottom
            if dy <= 0:
                continue
            middle_y = (bottom + top) / 2
            plot = next((item for item in relevant_plots
                         if item.y0 <= middle_y <= item.y1), None)
            if plot is None:
                continue
            area = dx * dy
            states = {day: _point_class(active[day], middle_x, middle_y)
                      for day in days}
            for day in days:
                _record_daily(daily[day][plot.plot_id], states[day], area,
                              conflicts[day], plot, left, bottom, right, top)
            for (a, b), values in pair_stats.items():
                _record_pair(values[plot.plot_id], states[a], states[b], area)
    return daily, pair_stats, conflicts


def _record_daily(current, state, area, conflicts, plot, left, bottom, right, top):
    current["plot_area"] += area
    if state["state"] == "unobserved":
        current["unobserved_area"] += area
        return
    current["covered_area"] += area
    current["winning_tile_ids"].update(state["tile_ids"])
    if state["state"] == "observed":
        current["observed_area"] += area
        if state["value"] == 1:
            current["wet_area"] += area
        else:
            current["dry_area"] += area
    elif state["state"] == "unknown":
        current["unknown_area"] += area
    else:
        current["conflict_area"] += area
        key = (state["priority"], tuple(state["tile_ids"]), tuple(state["classes"]))
        entry = conflicts.setdefault(key, {
            "tile_ids": list(state["tile_ids"]),
            "classes": list(state["classes"]),
            "priority": state["priority"],
            "area": Fraction(0),
            "plot_ids": set(),
            "bbox": [left, bottom, right, top],
        })
        entry["area"] += area
        entry["plot_ids"].add(plot.plot_id)
        entry["bbox"] = [min(entry["bbox"][0], left), min(entry["bbox"][1], bottom),
                         max(entry["bbox"][2], right), max(entry["bbox"][3], top)]


def _record_pair(current, state_a, state_b, area):
    if state_a["state"] != "observed" or state_b["state"] != "observed":
        return
    current["both_observed_area"] += area
    wet_a = state_a["value"] == 1
    wet_b = state_b["value"] == 1
    if wet_a:
        current["wet_area_a"] += area
    if wet_b:
        current["wet_area_b"] += area
    if wet_a and wet_b:
        current["wet_to_wet_area"] += area
    elif wet_a:
        current["wet_to_dry_area"] += area
    elif wet_b:
        current["dry_to_wet_area"] += area
    else:
        current["dry_to_dry_area"] += area


def daily_and_pair_statistics(rasters, plots, pairs=()):
    """返回 JSON 就绪的每日地块统计、冲突列表与跨日公共范围统计。"""
    daily, pair_stats, conflicts = analyze_overlays(rasters, plots, pairs)
    daily_rows = {}
    for day in sorted(daily):
        rows = []
        raster = rasters[day]
        for plot in plots:
            current = daily[day][plot.plot_id]
            if current["plot_area"] != plot.area:
                raise RuntimeError("地块面积分配不一致：" + plot.plot_id)
            overlapping = [tile for tile in raster.tiles
                           if tile.x0 < plot.x1 and tile.x1 > plot.x0
                           and tile.y0 < plot.y1 and tile.y1 > plot.y0]
            undetermined = (current["unobserved_area"] + current["unknown_area"]
                            + current["conflict_area"])
            rows.append({
                "plot_id": plot.plot_id,
                "plot_area": area_number(current["plot_area"]),
                "covered_area": area_number(current["covered_area"]),
                "observed_area": area_number(current["observed_area"]),
                "unobserved_area": area_number(current["unobserved_area"]),
                "unknown_area": area_number(current["unknown_area"]),
                "conflict_area": area_number(current["conflict_area"]),
                "undetermined_area": area_number(undetermined),
                "wet_area": area_number(current["wet_area"]),
                "dry_area": area_number(current["dry_area"]),
                "wet_area_lower": area_number(current["wet_area"]),
                "wet_area_upper": area_number(current["wet_area"] + undetermined),
                "tile_ids": sorted(tile.tile_id for tile in overlapping),
                "classification_versions": sorted(
                    {tile.classification_version for tile in overlapping}),
                "source_cell_sizes": [area_number(size) for size in sorted(
                    {tile.cell_size for tile in overlapping})],
                "winning_tile_ids": sorted(current["winning_tile_ids"]),
            })
        daily_rows[day] = rows
    pair_rows = {}
    for (a, b) in sorted(pair_stats):
        rows = []
        for plot in plots:
            current = pair_stats[(a, b)][plot.plot_id]
            excluded_a = current["plot_area"] - current["both_observed_area"]
            wet_a_lower = current["wet_area_a"]
            wet_a_upper = current["wet_area_a"] + excluded_a
            wet_b_lower = current["wet_area_b"]
            wet_b_upper = current["wet_area_b"] + excluded_a
            rows.append({
                "plot_id": plot.plot_id,
                "plot_area": area_number(current["plot_area"]),
                "both_observed_area": area_number(current["both_observed_area"]),
                "excluded_area": area_number(excluded_a),
                "wet_area_a_in_common": area_number(current["wet_area_a"]),
                "wet_area_b_in_common": area_number(current["wet_area_b"]),
                "wet_change_in_common": area_number(current["wet_area_b"]
                                                    - current["wet_area_a"]),
                "wet_change_lower": area_number(wet_b_lower - wet_a_upper),
                "wet_change_upper": area_number(wet_b_upper - wet_a_lower),
                "wet_to_wet_area": area_number(current["wet_to_wet_area"]),
                "wet_to_dry_area": area_number(current["wet_to_dry_area"]),
                "dry_to_wet_area": area_number(current["dry_to_wet_area"]),
                "dry_to_dry_area": area_number(current["dry_to_dry_area"]),
            })
        pair_rows[(a, b)] = rows
    conflict_rows = {}
    for day in sorted(conflicts):
        rows = []
        for entry in conflicts[day].values():
            rows.append({
                "tile_ids": list(entry["tile_ids"]),
                "classes": list(entry["classes"]),
                "priority": area_number(entry["priority"]),
                "area": area_number(entry["area"]),
                "plot_ids": sorted(entry["plot_ids"]),
                "bbox": [area_number(value) for value in entry["bbox"]],
            })
        rows.sort(key=lambda item: (item["tile_ids"], item["classes"], item["bbox"]))
        conflict_rows[day] = rows
    return daily_rows, pair_rows, conflict_rows
