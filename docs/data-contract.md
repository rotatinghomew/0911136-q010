# 领域资料与供数约定

## 数据含义

栅格与地块均在同一局地等面积米制坐标系。values 为从 origin_y 起沿正 y 方向逐行、沿正 x 方向逐列的二维数组，0=明确未受淹，1=受淹，null=无有效观测。origin 为左下像元边界，cell_size 为正数，同日重叠按 priority 较高瓦片优先，优先级相同且分类冲突应显式报告。plots 为不重叠矩形，可跨多个像元。checks 为定向现场核实，不提供总体概率抽样保证。

## 现行摘要

`dispatch_scenarios/analysis.py` 生成现行资料摘要。源码和运行结果中的 scope 说明其统计边界，不能把未提供的推断当成已有能力。

## 供数接口

`GET /manifest` 返回 generation、tables（每表 count 与 sha256）及 metadata。`GET /tables/<name>?generation=<generation>` 返回同代 rows。供数换代时旧 generation 返回 HTTP 409，不允许将新代记录接入旧分析；不存在的表返回 404。表内容为稳定键唯一的完整同代记录，不是增量事件流。客户端对清单摘要进行核验。摘要使用 UTF-8、排序对象键、紧凑 JSON 的 SHA256，数组顺序保留供数端顺序。

字段与主键声明位于 `dispatch_scenarios/schema.json`，合成资料位于 `fixtures/dataset.json`。`metadata.cutoff` 是供数展示截点，不自动为分析选择训练截止点。服务可将整个 dataset 原子替换为新一代，但不在同一 generation 下更改内容。

## 结果保存

`reports.py` 保存现有摘要及来源表摘要，report_id 是内容摘要，不是随机编号。相同内容生成相同编号，临时文件写入完成后原子替换目标文件；历史内容是否保留由调用者选择不同目标路径。服务只监听本机，不接入生产系统。
