"""逐瓦片计算有效分类面积，不进行瓦片拼接。"""


def tile_areas(tables):
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
    return {"tiles": tile_areas(tables), "plot_count": len(tables["plots"]),
            "scope": "逐瓦片分类面积摘要，不去除重叠、不统计地块受淹"}
