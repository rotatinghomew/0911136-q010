"""地块受淹面积统计：去重、精确面积分配、证据范围与可比性判断。

保留逐瓦片摘要作为原始记录，但不把它当作地块面积；地块面积由 overlay 模块
按同日优先级叠加瓦片后精确分配。无法确定的面积单列，不并入未受淹。
"""

from .overlay import (_exact, area_number, build_day_rasters, build_plots,
                      classify_point, daily_and_pair_statistics)

UNITS = "m2"

METHOD_NOTES = [
    "瓦片按同日 priority 从高到低叠加；较高优先级像元为 null 时该处按无有效观测处理，不用低优先级回填。",
    "同优先级同时给出不同分类时该处记为 conflict，不擅自取值，并报告冲突瓦片、类别与范围；"
    "同优先级一方为 null、另一方有分类时采用已有分类。",
    "坐标与像元边界用精确有理数计算，支持不同分辨率与半像元平移，像元按左闭右开、地块按闭区间。",
    "地块面积按像元与地块边界的交集精确分配；地块跨瓦片边界或瓦片边界时不会重复计入。",
    "unknown 与 unobserved 都不是未受淹；wet_area 是已判定受淹面积，wet_area_upper 再加上全部无法确定面积。",
]

SCOPE = ("地块受淹面积统计：同日瓦片按优先级拼接去重，按精确几何把分类面积分配到地块，"
         "分别报告有效观测覆盖与无法确定面积；仅使用本地合成记录，不接入地图，不代替现场灾损认定。")


def _check_record(check, rasters, plots_by_id):
    record = {"check_id": check["check_id"], "plot_id": check["plot_id"],
              "day": check["day"], "x": area_number(check["_x"]),
              "y": area_number(check["_y"]), "field_wet": check["wet"],
              "selection_reason": check["selection_reason"]}
    reasons = []
    plot = plots_by_id.get(check["plot_id"])
    if plot is None:
        reasons.append("核实点引用了不存在的地块")
    elif not plot.contains(check["_x"], check["_y"]):
        reasons.append("核实点不在地块范围内")
    state = classify_point(rasters, check["day"], check["_x"], check["_y"])
    record["raster_state"] = state["state"]
    record["raster_wet"] = state["value"] == 1 if state["state"] == "observed" else None
    record["raster_tile_ids"] = state["tile_ids"]
    if state["state"] == "no_raster_for_day":
        reasons.append("核实日期没有对应瓦片观测")
    elif state["state"] == "unobserved":
        reasons.append("核实点位没有瓦片覆盖")
    elif state["state"] == "unknown":
        reasons.append("核实点位为无有效观测")
    elif state["state"] == "conflict":
        reasons.append("核实点位存在同优先级分类冲突")
    record["usable_for_comparison"] = not reasons
    record["reasons"] = reasons
    return record


def _check_summary(raw_checks, day, rasters, plots_by_id):
    records = [_check_record(check, rasters, plots_by_id)
               for check in raw_checks if check["day"] == day]
    usable = [record for record in records if record["usable_for_comparison"]]
    agree = sum(record["raster_wet"] == record["field_wet"] for record in usable)
    raster_wet_field_dry = sum(record["raster_wet"] and not record["field_wet"]
                               for record in usable)
    raster_dry_field_wet = sum((not record["raster_wet"]) and record["field_wet"]
                               for record in usable)
    return {
        "day": day,
        "check_count": len(records),
        "usable_count": len(usable),
        "agree_count": agree,
        "raster_wet_field_dry_count": raster_wet_field_dry,
        "raster_dry_field_wet_count": raster_dry_field_wet,
        "records": [{key: value for key, value in record.items() if not key.startswith("_")}
                    for record in records],
        "_records": records,
    }

CHECK_USE = {
    "selection": "现场核实标签来自定向巡查，不是概率抽样，不能代表全部地块或总体分类精度。",
    "supports": ("可在被核实点位指出栅格分类与现场标签是否一致，为个别地块的疑似误判提供线索，"
                 "并说明这些点位为何被选中。"),
    "does_not_support": ("不能据此纠正全网分类、估计总体漏判或误判比例、给未核实地块赋真值，"
                         "也不能替代现场灾损认定。"),
}


def _changes(rasters, pair_rows):
    output = []
    for (day_a, day_b) in sorted(pair_rows):
        versions_a = set(rasters[day_a].classification_versions)
        versions_b = set(rasters[day_b].classification_versions)
        sizes_a = set(rasters[day_a].cell_sizes)
        sizes_b = set(rasters[day_b].cell_sizes)
        blockers = []
        notes = []
        if versions_a != versions_b or len(versions_a) > 1 or len(versions_b) > 1:
            blockers.append("两天分类口径不同或单日存在多种分类口径，分类结果不可直接相减")
        if sizes_a != sizes_b:
            notes.append("两天源像元分辨率不同，可检测的最小图斑与灵敏度不同；"
                         "变化只在共同有效观测范围内计算，不能解释为灾情扩大或缩小。")
        rows = []
        for row in pair_rows[(day_a, day_b)]:
            common = row["both_observed_area"]
            fraction = _ratio(common, row["plot_area"])
            row_blockers = list(blockers)
            if common == 0:
                row_blockers.append("两天没有共同有效观测，无面积可比")
            entry = {"plot_id": row["plot_id"], "plot_area": row["plot_area"],
                     "both_observed_area": common,
                     "common_observed_fraction": fraction,
                     "excluded_area": row["excluded_area"],
                     "comparable": not row_blockers,
                     "notes": row_blockers + notes}
            if row_blockers:
                entry.update({key: None for key in (
                    "wet_area_a_in_common", "wet_area_b_in_common", "wet_change_in_common",
                    "wet_change_lower", "wet_change_upper", "wet_to_wet_area",
                    "wet_to_dry_area", "dry_to_wet_area", "dry_to_dry_area")})
            else:
                entry.update({key: row[key] for key in (
                    "wet_area_a_in_common", "wet_area_b_in_common", "wet_change_in_common",
                    "wet_change_lower", "wet_change_upper", "wet_to_wet_area",
                    "wet_to_dry_area", "dry_to_wet_area", "dry_to_dry_area")})
            rows.append(entry)
        output.append({
            "day_a": day_a,
            "day_b": day_b,
            "classification_versions_a": sorted(versions_a),
            "classification_versions_b": sorted(versions_b),
            "cell_sizes_a": [area_number(value) for value in sorted(sizes_a)],
            "cell_sizes_b": [area_number(value) for value in sorted(sizes_b)],
            "comparable": not blockers,
            "blockers": sorted(set(blockers)),
            "notes": notes,
            "plots": rows,
            "interpretation": ("仅在共同有效观测范围内比较分类结果；"
                               "comparable 为 false 时不应讨论受淹变化。"
                               "即使 comparable 为 true，共同观测比例不足、分辨率或覆盖差异"
                               "也不能被解释为灾情变化；本摘要不推断灾情因果。"),
        })
    return output


def _dispatch(daily_rows, checks_by_plot, days, rasters):
    by_day = {}
    reference = {}
    for day in days:
        reference[day] = {
            "tile_ids": sorted(tile.tile_id for tile in rasters[day].tiles),
            "classification_versions": list(rasters[day].classification_versions),
            "cell_sizes": [area_number(value) for value in rasters[day].cell_sizes],
        }
        candidates = []
        for row in daily_rows[day]:
            if row["wet_area_upper"] <= 0:
                continue
            checks = checks_by_plot.get(row["plot_id"], [])
            checks = [check for check in checks if check["day"] == day]
            candidate = {
                "plot_id": row["plot_id"],
                "day": day,
                "wet_area_lower_m2": row["wet_area_lower"],
                "wet_area_upper_m2": row["wet_area_upper"],
                "observed_area_m2": row["observed_area"],
                "observed_fraction": _ratio(row["observed_area"], row["plot_area"]),
                "undetermined_fraction": _ratio(row["undetermined_area"],
                                                row["plot_area"]),
                "tile_ids": row["tile_ids"],
                "classification_versions": row["classification_versions"],
                "source_cell_sizes": row["source_cell_sizes"],
                "field_checks": checks,
                "basis": "按已判定受淹面积下限降序；相同下限时按无法确定面积升序。",
            }
            candidates.append(candidate)
        candidates.sort(key=lambda item: (-item["wet_area_lower_m2"],
                                          item["wet_area_upper_m2"] - item["wet_area_lower_m2"],
                                          item["plot_id"]))
        for rank, candidate in enumerate(candidates, start=1):
            candidate["priority_rank"] = rank
        by_day[day] = candidates
    return {
        "purpose": "为现场核实提供排序线索，不是灾损认定，也不接入地图或调度系统。",
        "latest_day": days[-1] if days else None,
        "by_day": by_day,
        "raster_reference": reference,
        "requirements": ["保留地块标识", "保留当天栅格版本与瓦片标识", "保留已判定与无法确定面积证据"],
    }


def plot_flood_summary(tables):
    rasters = build_day_rasters(tables["tiles"])
    plots = build_plots(tables["plots"])
    plots_by_id = {plot.plot_id: plot for plot in plots}
    days = sorted(rasters)
    pairs = [(a, b) for index, a in enumerate(days) for b in days[index + 1:]]
    daily_rows, pair_rows, conflict_rows = daily_and_pair_statistics(rasters, plots, pairs)
    changes = _changes(rasters, pair_rows)

    raw_checks = []
    for row in tables["checks"]:
        raw_checks.append({
            "check_id": row["check_id"], "plot_id": row["plot_id"],
            "day": row["day"], "wet": row["wet"],
            "selection_reason": row["selection_reason"],
            "_x": _number(row["x"], "核实点 x"), "_y": _number(row["y"], "核实点 y"),
        })
    raw_checks.sort(key=lambda item: (item["day"], item["check_id"]))

    day_rows = []
    for day in days:
        checks = _check_summary(raw_checks, day, rasters, plots_by_id)
        day_rows.append({
            "day": day,
            "classification_versions": list(rasters[day].classification_versions),
            "cell_sizes": [area_number(value) for value in rasters[day].cell_sizes],
            "tile_ids": sorted(tile.tile_id for tile in rasters[day].tiles),
            "plots": daily_rows[day],
            "conflicts": conflict_rows[day],
            "checks": checks,
        })

    checks_by_plot = {}
    unmatched = []
    for day_row in day_rows:
        for record in day_row["checks"]["_records"]:
            if record["usable_for_comparison"]:
                checks_by_plot.setdefault(record["plot_id"], []).append({
                    "check_id": record["check_id"], "day": record["day"],
                    "field_wet": record["field_wet"],
                    "raster_wet": record["raster_wet"],
                    "x": record["x"], "y": record["y"],
                })
            else:
                unmatched.append(record["check_id"])
        del day_row["checks"]["_records"]

    # 核实日期没有对应瓦片的标签单列，不能悄悄丢弃，也不能拿来当比较依据。
    orphan_checks = [{key: value for key, value in record.items()
                      if not key.startswith("_")}
                     for record in (_check_record(check, rasters, plots_by_id)
                                    for check in raw_checks
                                    if check["day"] not in rasters)]
    unmatched.extend(record["check_id"] for record in orphan_checks)

    return {
        "units": UNITS,
        "scope": SCOPE,
        "method_notes": METHOD_NOTES,
        "days": day_rows,
        "changes": changes,
        "checks": {"use": CHECK_USE, "unmatched_check_ids": sorted(unmatched),
                   "unmatched_records": orphan_checks,
                   "usable_check_count": sum(len(value)
                                             for value in checks_by_plot.values())},
        "dispatch": _dispatch(daily_rows, checks_by_plot, days, rasters),
        "plot_count": len(plots),
    }


def _number(value, label):
    return _exact(value, label)


def _ratio(part, whole):
    """返回 JSON 可序列化的比例；面积可能是精确分数。"""
    if whole == 0:
        return None
    return round(float(_exact(part, "分子") / _exact(whole, "分母")), 6)


def tile_areas(tables):
    """逐瓦片原始分类面积摘要；不去重，不能作为地块受淹面积。"""
    output = []
    for row in tables["tiles"]:
        if row["cell_size"] <= 0 or len(row["values"]) != row["rows"]:
            raise ValueError("瓦片分辨率或行数不合法")
        if any(len(values) != row["cols"] for values in row["values"]):
            raise ValueError("瓦片列数不合法")
        values = [value for line in row["values"] for value in line]
        if any(value not in (0, 1, None) for value in values):
            raise ValueError("未知积水分类值")
        area = row["cell_size"] ** 2
        output.append({"tile_id": row["tile_id"], "wet_area_m2": sum(value == 1 for value in values) * area,
                       "unknown_area_m2": sum(value is None for value in values) * area,
                       "total_area_m2": len(values) * area})
    return output


def summarize(tables):
    output = plot_flood_summary(tables)
    output["tiles"] = tile_areas(tables)
    output["tile_note"] = ("tiles 为逐瓦片原始累加，瓦片重叠会重复计算，"
                           "不能当作地块受淹面积；请使用 days[].plots 的精确分配结果。")
    return output
