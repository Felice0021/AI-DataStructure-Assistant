import unittest

from rag.retrievers.dense_rerank import DenseRerankRetriever


class FakeDense:
    def __init__(self):
        self.last_top_k = None

    def prepare(self, chunks, use_cache=True):
        pass

    def get_config(self):
        return {
            "retriever": "fake_dense",
        }

    def retrieve(
        self,
        query,
        chunks,
        top_k,
    ):
        self.last_top_k = top_k

        return [
            {
                "chunk_id": f"c{i}",
                "text": f"text {i}",
                "score": 0.90 - i * 0.05,
            }
            for i in range(top_k)
        ]


class FakeReranker:
    def __init__(self):
        self.last_candidate_count = None
        self.last_top_n = None

    def get_config(self):
        return {
            "reranker": "fake",
        }

    def rerank(
        self,
        query,
        candidates,
        *,
        top_n,
    ):
        self.last_candidate_count = len(candidates)
        self.last_top_n = top_n

        scores = {
            "c0": 0.50,
            "c1": 0.00,
            "c2": 1.00,
        }

        results = []

        for item in candidates:
            cid = item["chunk_id"]

            result = dict(item)
            result["rerank_score"] = scores.get(
                cid,
                0.10,
            )

            results.append(result)

        results.sort(
            key=lambda x: -x["rerank_score"]
        )

        return results[:top_n]


class BrokenReranker:
    def get_config(self):
        return {
            "reranker": "broken",
        }

    def rerank(
        self,
        *args,
        **kwargs,
    ):
        raise RuntimeError(
            "intentional test failure"
        )


class DenseRerankRetrieverTest(
    unittest.TestCase
):
    def setUp(self):
        self.chunks = [
            {
                "chunk_id": f"source_{i}",
                "text": f"source text {i}",
            }
            for i in range(20)
        ]

    def test_dense_top10_is_fused_to_top5(self):
        dense = FakeDense()
        reranker = FakeReranker()

        retriever = DenseRerankRetriever(
            dense=dense,
            reranker=reranker,
            candidate_k=10,
            fusion_alpha=0.40,
        )

        results = retriever.retrieve(
            query="test query",
            chunks=self.chunks,
            top_k=5,
        )

        self.assertEqual(
            dense.last_top_k,
            10,
        )

        self.assertEqual(
            reranker.last_candidate_count,
            10,
        )

        self.assertEqual(
            reranker.last_top_n,
            10,
        )

        self.assertEqual(
            len(results),
            5,
        )

        # c2 的 rerank 分数最高，
        # 经过 0.6 Dense + 0.4 Rerank 后应升至第一。
        self.assertEqual(
            results[0]["chunk_id"],
            "c2",
        )

        self.assertAlmostEqual(
            results[0]["dense_top1_score"],
            0.90,
        )

        self.assertTrue(
            all(
                item["rerank_fallback"] is False
                for item in results
            )
        )

        self.assertTrue(
            all(
                item["score"]
                == item["fusion_score"]
                for item in results
            )
        )

    def test_reranker_failure_falls_back_to_dense(self):
        dense = FakeDense()

        retriever = DenseRerankRetriever(
            dense=dense,
            reranker=BrokenReranker(),
            candidate_k=10,
            fusion_alpha=0.40,
        )

        with self.assertLogs(
            "rag.retrievers.dense_rerank",
            level="WARNING",
        ) as logs:
            results = retriever.retrieve(
                query="test query",
                chunks=self.chunks,
                top_k=5,
            )

        self.assertEqual(
            len(results),
            5,
        )

        self.assertEqual(
            [
                item["chunk_id"]
                for item in results
            ],
            [
                "c0",
                "c1",
                "c2",
                "c3",
                "c4",
            ],
        )

        self.assertTrue(
            all(
                item["rerank_fallback"] is True
                for item in results
            )
        )

        self.assertAlmostEqual(
            results[0]["dense_top1_score"],
            0.90,
        )

        self.assertIn(
            "falling back to Dense Top-K",
            logs.output[0],
        )

    def test_invalid_fusion_alpha_is_rejected(self):
        with self.assertRaises(ValueError):
            DenseRerankRetriever(
                dense=FakeDense(),
                reranker=FakeReranker(),
                fusion_alpha=-0.01,
            )

        with self.assertRaises(ValueError):
            DenseRerankRetriever(
                dense=FakeDense(),
                reranker=FakeReranker(),
                fusion_alpha=1.01,
            )


if __name__ == "__main__":
    unittest.main()
