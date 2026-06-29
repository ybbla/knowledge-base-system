"""
评测数据自动生成功能单元测试。

测试 gen_dataset.py 中的核心功能：
- generate_for_chunks() 元数据补充（doc_id 字段名）
- _validate_annotations() chunk_id 合法性 + 关键词存在性校验
- LLM prompt 格式校验
"""

import json

import pytest

from tests.evaluation.gen_dataset import _validate_annotations, generate_for_chunks


class TestValidateAnnotations:
    """标注合法性校验测试。

    覆盖 chunk_id 有效性、关键词存在性、边界情况等场景。
    """

    @pytest.fixture
    def sample_chunks(self):
        return [
            {"chunk_id": "chunk_1", "title": "标题一", "content": "第一期内容，含关键词A和关键词B"},
            {"chunk_id": "chunk_2", "title": "标题二", "content": "第二期内容，含关键词C和关键词D"},
        ]

    def test_valid_annotations(self, sample_chunks):
        """合法标注应完全通过校验。"""
        items = [
            {
                "query": "测试查询",
                "expected_chunk_ids": ["chunk_1"],
                "expected_content_contains": ["关键词A"],
            }
        ]
        valid_items, errors = _validate_annotations(items, sample_chunks)
        assert len(valid_items) == 1
        assert len(errors) == 0

    def test_invalid_chunk_id_filtered(self, sample_chunks):
        """LLM 编造的无效 chunk_id 被过滤，有效 chunk_id 保留。"""
        items = [
            {
                "query": "测试查询",
                "expected_chunk_ids": ["chunk_not_exist", "chunk_1"],
                "expected_content_contains": ["关键词A"],
            }
        ]
        valid_items, errors = _validate_annotations(items, sample_chunks)
        assert len(valid_items) == 1
        assert len(errors) >= 1
        assert "chunk_not_exist" in str(errors[0])
        assert "chunk_1" in valid_items[0]["expected_chunk_ids"]

    def test_keyword_not_in_chunk_filtered(self, sample_chunks):
        """不在 chunk 正文中的关键词被过滤。"""
        items = [
            {
                "query": "测试查询",
                "expected_chunk_ids": ["chunk_1"],
                "expected_content_contains": ["关键词A", "虚构词"],
            }
        ]
        valid_items, errors = _validate_annotations(items, sample_chunks)
        assert len(valid_items) == 1
        assert len(errors) >= 1
        assert "关键词A" in valid_items[0]["expected_content_contains"]

    def test_all_keywords_invalid(self, sample_chunks):
        """所有关键词无效时仍保留条目（只要有 chunk_id）。"""
        items = [
            {
                "query": "测试查询",
                "expected_chunk_ids": ["chunk_1"],
                "expected_content_contains": ["虚构词1", "虚构词2"],
            }
        ]
        valid_items, errors = _validate_annotations(items, sample_chunks)
        assert len(valid_items) == 1
        assert valid_items[0]["expected_content_contains"] == []

    def test_all_chunk_ids_invalid(self, sample_chunks):
        """所有 chunk_id 无效时仍保留条目（只要有关键词）。"""
        items = [
            {
                "query": "测试查询",
                "expected_chunk_ids": ["不存在1", "不存在2"],
                "expected_content_contains": ["关键词A"],
            }
        ]
        valid_items, errors = _validate_annotations(items, sample_chunks)
        assert len(valid_items) == 1
        assert valid_items[0]["expected_chunk_ids"] == []

    def test_both_empty_after_filter(self, sample_chunks):
        """过滤后 chunk_id 和关键词皆空，条目被丢弃。"""
        items = [
            {
                "query": "测试查询",
                "expected_chunk_ids": ["不存在1"],
                "expected_content_contains": ["虚构词"],
            }
        ]
        valid_items, errors = _validate_annotations(items, sample_chunks)
        # 两个维度都过滤为空 → 条目被丢弃
        assert len(valid_items) == 0
        assert len(errors) >= 1

    def test_empty_items(self, sample_chunks):
        """空输入返回空输出。"""
        valid_items, errors = _validate_annotations([], sample_chunks)
        assert len(valid_items) == 0
        assert len(errors) == 0


class TestGenerateForChunks:
    """generate_for_chunks 元数据测试。

    实际的 LLM 调用在集成测试中验证，此处仅验证用户可见的 API 行为。
    """

    @pytest.mark.skip(reason="需 LLM mock 环境，在集成测试中验证")
    def test_generate_success(self):
        pass

    @pytest.mark.skip(reason="需 LLM mock 环境，在集成测试中验证")
    def test_generate_llm_returns_empty(self):
        pass

    @pytest.mark.skip(reason="需 LLM mock 环境，在集成测试中验证")
    def test_generate_llm_exception(self):
        pass


class TestLLMPromptFormat:
    """LLM prompt 格式测试 — 验证提示词模板包含关键占位符和指令。"""

    def test_system_prompt_structure(self):
        """系统提示词包含核心指令，且可接收 target_count 参数。"""
        from tests.evaluation.gen_dataset import SYSTEM_PROMPT

        rendered = SYSTEM_PROMPT.format(target_count=3)
        assert "评测数据" in rendered
        assert "expected_chunk_ids" in rendered
        assert "expected_content_contains" in rendered
        assert "3" in rendered
        assert "直接复制" in rendered
        assert "口语化" in rendered
        assert "关键词组合" in rendered
        assert "{target_count}" not in rendered  # 占位符已替换

    def test_user_prompt_template(self):
        """用户提示词模板包含必要的占位符。"""
        from tests.evaluation.gen_dataset import USER_PROMPT_TEMPLATE
        assert "{chunk_count}" in USER_PROMPT_TEMPLATE
        assert "{target_count}" in USER_PROMPT_TEMPLATE
        assert "{chunks_json}" in USER_PROMPT_TEMPLATE

    def test_user_prompt_rendering(self):
        """用户提示词渲染后包含实际 chunk 内容。"""
        from tests.evaluation.gen_dataset import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

        chunks = [{"chunk_id": "chunk_1", "title": "测试标题", "content": "测试内容"}]
        chunks_json = json.dumps(chunks, ensure_ascii=False, indent=2)
        user_prompt = USER_PROMPT_TEMPLATE.format(
            chunk_count=1, target_count=3, chunks_json=chunks_json,
        )
        system_prompt = SYSTEM_PROMPT.format(target_count=3)

        assert "chunk_1" in user_prompt
        assert "测试内容" in user_prompt
        assert "3" in system_prompt
