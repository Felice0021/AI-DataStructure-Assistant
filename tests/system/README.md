# System Tests

当前系统开发使用的测试和统一评测工具。

主要入口：

```bash
python3 tests/system/run_retrieval_eval.py --retriever dense
python3 tests/system/run_retrieval_eval.py --retriever bm25
python3 -m unittest tests.system.test_bm25_retriever
```

新增系统级测试优先放在本目录。
