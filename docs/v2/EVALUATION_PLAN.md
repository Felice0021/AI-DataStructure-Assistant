# V2 小规模评测计划

数据：backend/v2/evaluation/cases.jsonl，36题，全部作者合成（概念、线性表、树图、排序查找、复杂度、C/C++、易混点、多步骤、证据不足、课程外、引用及冲突）。未复制V1评测资产。题目仅是待标注候选，不是已有Ground Truth。

字段：id/category/query/source/annotation_status/reference_answer/related_chunk_ids/relevance/evidence_sufficient/reviewer/reviewed_at。当前全部 pending，参考答案、Chunk映射、充分性和审查人待补。必须人工确认资料版本、答案和0–3级相关度，填写 reviewer、ISO日期、human_approved 和布尔 evidence_sufficient，才进入正式统计。数据集应与特定知识库/Chunk代次一并冻结；重新切分后复核映射，不能把旧UUID当成新真值。

```sh
python -m backend.v2.evaluation.score
python -m backend.v2.evaluation.score --cases <approved-cases.jsonl> --runs <reviewed-runs.jsonl>
```

run 结构：id、provider_kind（real/local_semantic/deterministic）、retrieved_chunk_ids（有序）、refused、citation_validity（0–1）、citation_faithfulness（0–1）、faithfulness_reviewed_by、latency_ms、api_calls、cost_cny。真实运行应另记录模型、空间revision、参数和资料版本；不得包含Key、私人正文或完整Prompt。当前脚本消费结果，不会自动发起付费调用。确定性Provider只用于工程验收，质量指标明确排除。

指标：Recall@5为前5个去重Chunk命中全部正相关Chunk的比例；MRR@10取前10中首个正相关的倒数排名；nDCG@5采用(2^relevance−1)/log2(rank+1)，按理想排序归一化。无正相关标签不纳入检索均值。Refusal Accuracy依据人工充分性和实际refused比较。Citation Validity由本次授权映射程序核查；Citation Faithfulness必须人工逐事实核对，不能由合法引用编号推导。脚本仅在有faithfulness_reviewed_by时统计该人工分值。端到端延迟、Token/API费用与质量分开记录，缺数据不补0。

当前执行结果：approved_cases=0，pending_cases=36，evaluated_cases=0，quality_metrics={}。**没有可发布的真实语义效果指标**。真实云端小样本只验证可用性、协议及正常/拒答，不是评测集结果。下一步由负责人确认公共资料授权与版本，再安排独立人工标注和复审、检索/重排消融；不得无预算开展全量付费评测。
