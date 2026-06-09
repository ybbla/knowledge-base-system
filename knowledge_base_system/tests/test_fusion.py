from indexing.fusion import rrf_fusion


class TestRRFFusion:
    def test_basic_fusion(self):
        vec = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
        bm25 = [("b", 5.0), ("c", 3.0), ("a", 1.0)]

        result = rrf_fusion(vec, bm25, k=60)

        # All three should appear
        assert set(result.keys()) == {"a", "b", "c"}

        # b appears in both lists near top → highest fused score
        assert result["b"] > result["a"]
        assert result["b"] > result["c"]

    def test_single_list(self):
        vec = [("a", 0.9), ("b", 0.8)]
        result = rrf_fusion(vec, [], k=60)
        assert len(result) == 2
        assert result["a"] > result["b"]

    def test_empty(self):
        result = rrf_fusion([], [], k=60)
        assert result == {}

    def test_disjoint_results(self):
        vec = [("a", 0.9)]
        bm25 = [("b", 0.8)]
        result = rrf_fusion(vec, bm25, k=60)
        assert "a" in result
        assert "b" in result
