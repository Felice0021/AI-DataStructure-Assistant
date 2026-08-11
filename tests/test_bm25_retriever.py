import unittest

from rag.retrievers.bm25 import BM25Retriever


class BM25RetrieverTest(unittest.TestCase):
    @staticmethod
    def whitespace_tokenize(text: str):
        return text.lower().split()

    def setUp(self):
        self.chunks = [
            {
                "chunk_id": "seq",
                "text": "顺序表 随机访问 时间复杂度 o1",
                "chapter": "第二章 线性表",
                "section": "顺序表",
                "source_file": "test.pdf",
                "page": 1,
                "content_type": "concept",
            },
            {
                "chunk_id": "list",
                "text": "单链表 插入 删除 指针 next",
                "chapter": "第二章 线性表",
                "section": "单链表",
                "source_file": "test.pdf",
                "page": 2,
                "content_type": "concept",
            },
            {
                "chunk_id": "tree",
                "text": "二叉树 先序遍历 根 左 右",
                "chapter": "第六章 树和二叉树",
                "section": "遍历",
                "source_file": "test.pdf",
                "page": 3,
                "content_type": "algorithm",
            },
        ]
        self.retriever = BM25Retriever(
            self.chunks,
            tokenizer=self.whitespace_tokenize,
        )

    def test_expected_document_ranks_first(self):
        results = self.retriever.retrieve("单链表 指针", top_k=3)
        self.assertEqual(results[0]["chunk_id"], "list")
        self.assertGreater(results[0]["score"], results[1]["score"])

    def test_metadata_is_preserved(self):
        result = self.retriever.retrieve("二叉树", top_k=1)[0]
        self.assertEqual(result["chapter"], "第六章 树和二叉树")
        self.assertIn("score", result)

    def test_empty_query_returns_empty(self):
        self.assertEqual(self.retriever.retrieve("", top_k=3), [])

    def test_invalid_parameters(self):
        with self.assertRaises(ValueError):
            BM25Retriever(self.chunks, k1=0, tokenizer=self.whitespace_tokenize)
        with self.assertRaises(ValueError):
            BM25Retriever(self.chunks, b=1.1, tokenizer=self.whitespace_tokenize)


if __name__ == "__main__":
    unittest.main()
