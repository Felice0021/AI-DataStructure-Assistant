# Tests and Evaluation

本目录只保留系统测试、正式 Benchmark、人工标注资产以及冻结的历史研究实验。

## 目录

```text
tests/
├── system/
│   ├── metrics.py
│   ├── run_retrieval_eval.py
│   ├── compare_retrievers.py
│   └── test_bm25_retriever.py
│
├── benchmarks/
│   ├── dev/
│   └── heldout/
│
├── annotations/
│   ├── dev/
│   └── heldout/
│
├── research/
│   ├── data/
│   └── 历史研究脚本
│
└── results/
```

## system

当前系统开发持续使用的测试与评测工具。

新增系统测试优先放入该目录。

## benchmarks

冻结的评测问题集。

`dev/` 用于开发和回归测试。

`heldout/` 保存独立的 100 题 held-out benchmark。

## annotations

人工 relevance / facet 标注和 retrieval pool。

这些文件属于评测资产，不应根据算法结果反向修改。

## research

2026-09 暂停的 evidence-set construction 论文探索。

历史版本脚本统一归档在这里，不再继续在 `tests/` 根目录增加
`v1 / v11 / v12 / v2x` 等实验脚本。

阶段总结：

`docs/RESEARCH_CHECKPOINT_2026-09.md`

## results

运行时产生的实验结果目录。

该目录已被 Git 忽略，不再提交生成结果。
