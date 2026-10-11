# Research Checkpoint — 2026-09

本文档记录项目在 2026 年 9 月阶段开展的论文型研究探索。

当前该研究路线暂停继续投稿，项目后续优先转向系统开发、功能完善、稳定性和大创成果落地。

## 1. 研究问题

研究阶段主要关注：

> passage-level relevance（单段相关性）并不一定意味着 evidence-set sufficiency（证据集合充分性）。

对于比较类和结构化技术问答，多个局部相关 Chunk 可能需要组合后才能覆盖完整答案。

实验中使用 facet（核心答案要点）描述问题需要被证据支持的信息。

## 2. Dev 阶段观察

冻结 Dev 共 50 题，其中 49 题为 in-scope。

SetR-inspired zero-shot set-wise selector 在整体 facet coverage 已较高的情况下，剩余失败主要集中于 comparison 问题。

由此形成了后续方法假设：

Scope-aware Contrastive Obligations

核心思想是对比较问题显式建模：

- 比较对象；
- 问题范围；
- 双侧信息需求；
- 需要被满足的 evidence obligations。

该方法尚未完成正式 held-out 验证，因此不能表述为已经验证有效。

## 3. Held-out Benchmark

已冻结 100 道 held-out 问题：

- 50 道 comparison；
- 50 道 matched non-comparison；
- 覆盖数据结构主要章节；
- 每题定义 core facets；
- Benchmark 在最终方法结果出现前已经冻结。

初始候选池：

BM25 Top10 ∪ Dense Top10

最终得到 1546 个唯一 question-chunk pair，并完成人工 facet 标注。

第一轮标签统计：

- label 0：1277
- label 1：223
- label 2：46
- 总计：1546

结构一致性审计通过。

## 4. 第一轮 Coverage 结果

100 道题可以划分为：

- 39 道：存在单个 Chunk 可以覆盖全部 core facets；
- 33 道：需要多个 Chunk 联合才能完整覆盖；
- 28 道：初始候选池仍存在至少一个缺失 facet，即 pool gap。

Comparison 组中 multi-evidence 现象更加明显。

但该现象可能同时受到以下因素影响：

- Query 类型；
- Corpus coverage；
- Chunking；
- Benchmark facet 设计。

因此不能直接推广为“比较问题天然需要多证据”。

## 5. Corpus Grounding 风险

28 道 pool-gap 问题共涉及 44 个缺失 facet。

随后使用完整 463-chunk corpus 对这些缺失 facet 进行了 coverage audit。

第一轮人工审计过程中，前 43 个高优先级候选均没有支持对应缺失 facet。

这提示部分 benchmark facet 可能超出当前知识库显式覆盖范围，或者存在 chunking / representation gap。

因此当前不能把 pool gap 简单归因于 retrieval failure。

至少需要区分：

- Retrieval gap：证据存在，但检索排序未找到；
- Corpus gap：当前知识库不存在对应知识；
- Chunking / representation gap：知识存在，但被拆散或表达不足。

## 6. 暂停论文路线的原因

如果继续达到正式投稿标准，还需要完成：

- Corpus grounding audit；
- Held-out qrels 补全；
- 二次人工复核；
- 正式 baseline reproduction；
- 最终方法实现；
- Held-out 主实验；
- 消融实验；
- End-to-end QA 评测；
- Error analysis；
- 论文写作和投稿。

当前投入已经明显超过系统项目本身的开发需求，因此阶段性停止论文型实验。

## 7. 已保留的可复用资产

后续系统开发仍可以直接使用：

- `knowledge_base/ds_chunks.jsonl`
- `tests/benchmarks/heldout/heldout_100_v1.jsonl`
- `tests/annotations/heldout/heldout_annotation_facets_v1.csv`
- `tests/annotations/heldout/heldout_annotation_labeled_v1.csv`
- `tests/system/run_retrieval_eval.py`
- BM25 Retriever
- Dense Retriever
- facet coverage / Full-Facet 等评测思想
- comparison query 的多证据覆盖观察

这些资产后续主要作为：

- regression benchmark；
- 检索算法回归测试；
- evidence-selection 模块开发依据；
- 系统质量评测资产。

## 8. 如果未来重新启动论文研究

优先重新建立 corpus-grounded benchmark：

1. 确认每个问题能够由当前知识库完整支撑；
2. 冻结问题和 facets；
3. 建立完整 qrels；
4. 冻结算法设计；
5. 再进行正式 held-out 对比。

在此之前，不应使用当前阶段结果声称最终方法优于 baseline。
