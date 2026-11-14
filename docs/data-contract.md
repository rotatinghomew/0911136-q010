# 领域资料与供数约定

## 数据含义

栅格与地块均在同一局地等面积米制坐标系。values 为从 origin_y 起沿正 y 方向逐行、沿正 x 方向逐列的二维数组，0=明确未受淹，1=受淹，null=无有效观测。origin 为左下像元边界，cell_size 为正数，同日重叠按 priority 较高瓦片优先，优先级相同且分类冲突应显式报告。plots 为不重叠矩形，可跨多个像元。checks 为定向现场核实，不提供总体概率抽样保证。

## 现行摘要

`dispatch_scenarios/analysis.py` 生成现行资料摘要。源码和运行结果中的 scope 说明其统计边界，不能把未提供的推断当成已有能力。

摘要同时保留两部分：`summary.tiles` 是逐瓦片原始分类面积，瓦片重叠会重复计算，只用于
核对原始记录，不能当作地块受淹面积；`summary.days[].plots` 是去重并按地块分配后的面积。
以地块面积讨论受淹情况时只能使用后者。

## 地块受淹面积统计

`dispatch_scenarios/overlay.py` 按同日 `priority` 从高到低叠加瓦片，把所有像元边界和地块
边界分解为不重叠的精确矩形，再按交集把面积分配到地块。坐标、分辨率和边界使用精确有理数，
因此不同分辨率、半像元平移、瓦片重叠以及地块跨瓦片或跨像元边界都不会重复计算或丢失面积。

每个瓦片像元解释为左闭右开的半开区间，地块矩形为闭区间。较高优先级瓦片在点位上为 `null`
时按无有效观测处理，不用较低优先级瓦片回填；同优先级已给出分类互相冲突时记为 `conflict`，
不擅自取值。地块统计口径如下：

- `observed_area_m2`：已取得明确 0/1 分类的面积，等于 `wet_area_m2 + dry_area_m2`。
- `unobserved_area_m2`：没有任何瓦片覆盖的面积。
- `unknown_area_m2`：被最高优先级瓦片覆盖但分类为 `null` 的面积。
- `conflict_area_m2`：同优先级分类冲突且未取值的面积。
- `undetermined_area_m2`：后三者之和，不能当作未受淹。
- `wet_area_lower_m2` / `wet_area_upper_m2`：已判定受淹面积与加上全部无法确定面积的上界。

`days[].checks` 把现场核实点与该日叠加规则逐点对照；`usable_for_comparison` 为 false 的点位
（不在任何地块内、无观测、未知或冲突）不会进入巡查证据，并在 `checks.unmatched_*` 单列。

## 跨日比较

`changes` 只在两日的共同有效观测范围内比较分类结果，并给出 `both_observed_area_m2`、
`excluded_area_m2` 与受淹变化的点估计及上下界。仅当两天分类口径一致、且每个地块都有共同
有效观测时，该地块才标记为 `comparable`。源像元分辨率不同只按共同观测范围计算，并在
`notes` 说明灵敏度差异；不得把分辨率更高或覆盖更清的新影像解释为灾情扩大。

## 巡查名单

`dispatch` 仅按已判定受淹面积下限排序，保留地块标识、当天瓦片标识与分类口径、源分辨率、
已判定与无法确定面积，以及该地块当日的可用核实标签。它不接入地图、不写回供数表，
也不代替现场灾损认定。

## 供数接口

`GET /manifest` 返回 generation、tables（每表 count 与 sha256）及 metadata。`GET /tables/<name>?generation=<generation>` 返回同代 rows。供数换代时旧 generation 返回 HTTP 409，不允许将新代记录接入旧分析；不存在的表返回 404。表内容为稳定键唯一的完整同代记录，不是增量事件流。客户端对清单摘要进行核验。摘要使用 UTF-8、排序对象键、紧凑 JSON 的 SHA256，数组顺序保留供数端顺序。

字段与主键声明位于 `dispatch_scenarios/schema.json`，合成资料位于 `fixtures/dataset.json`。`metadata.cutoff` 是供数展示截点，不自动为分析选择训练截止点。服务可将整个 dataset 原子替换为新一代，但不在同一 generation 下更改内容。

## 结果保存

`reports.py` 保存现有摘要及来源表摘要，report_id 是内容摘要，不是随机编号。相同内容生成相同编号，临时文件写入完成后原子替换目标文件；历史内容是否保留由调用者选择不同目标路径。服务只监听本机，不接入生产系统。
