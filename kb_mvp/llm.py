from __future__ import annotations

from typing import Protocol

from .models import Asset, AssetRef, KnowledgeChunk, ParsedDocument, ParsedElement, SourceRef
from .text import tokenize


class LLMService(Protocol):
    """LLM 服务抽象接口。

    业务流水线只依赖该协议，不依赖具体模型厂商。MVP 默认使用
    `MockLLMService`，后续可实现火山引擎 Doubao 客户端来替换。
    """

    def extract_chunks(self, parsed: ParsedDocument) -> list[KnowledgeChunk]:
        """把解析后的文档转换为知识块。

        参数:
            parsed: 标准化后的文档解析结果。

        返回:
            可向量化、可检索的知识块列表。
        """

        ...

    def rewrite_query(self, query: str) -> dict:
        """改写用户查询，使其更适合召回。

        参数:
            query: 用户原始问题。

        返回:
            包含 `rewritten_query`、`keywords` 和 `intent` 的字典。
        """

        ...

    def rerank(self, query: str, chunks: list[KnowledgeChunk]) -> list[tuple[str, float, str]]:
        """对候选知识块进行重排。

        参数:
            query: 改写后的查询。
            chunks: 混合召回得到的候选知识块。

        返回:
            `(chunk_id, relevance_score, reason)` 元组列表，按相关性降序排列。
        """

        ...


class MockLLMService:
    """MVP 阶段的确定性本地 LLM 替身。

    该类不调用外部模型，而是用简单规则模拟三个 LLM 能力：语义块生成、查询
    重写和结果重排。它的目标是帮助端到端流程先跑通，后续可整体替换为
    Doubao-Seed-2.0-pro 实现。
    """

    def __init__(self) -> None:
        """初始化知识块自增序列。"""

        self._chunk_seq = 0

    def extract_chunks(self, parsed: ParsedDocument) -> list[KnowledgeChunk]:
        """基于解析元素生成 MVP 知识块。

        参数:
            parsed: 标准化文档解析结果。

        返回:
            知识块列表。段落会按较小窗口合并，表格会被转写为自然语言陈述。
        """

        asset_by_id = {asset.asset_id: asset for asset in parsed.assets}
        chunks: list[KnowledgeChunk] = []
        pending_paragraphs: list[ParsedElement] = []

        for element in parsed.root_elements:
            if element.element_type == "title":
                continue
            if element.element_type == "paragraph":
                pending_paragraphs.append(element)
                if len(" ".join(item.text for item in pending_paragraphs)) > 180:
                    chunks.append(self._chunk_from_elements(parsed, pending_paragraphs, asset_by_id))
                    pending_paragraphs = []
            elif element.element_type == "table":
                if pending_paragraphs:
                    chunks.append(self._chunk_from_elements(parsed, pending_paragraphs, asset_by_id))
                    pending_paragraphs = []
                if element.children:
                    chunks.append(self._chunk_from_table(parsed, element, asset_by_id))
                elif element.text:
                    chunks.append(self._chunk_from_elements(parsed, [element], asset_by_id))

        if pending_paragraphs:
            chunks.append(self._chunk_from_elements(parsed, pending_paragraphs, asset_by_id))

        return [chunk for chunk in chunks if chunk.content]

    def rewrite_query(self, query: str) -> dict:
        """用少量规则模拟查询重写。

        参数:
            query: 用户原始查询。

        返回:
            包含改写查询、关键词和意图的字典。

        说明:
            当前只处理少数演示用同义表达，例如“进库”到“进入知识库”。
            正式版本应交给 LLM 生成结构化 JSON。
        """

        normalized = " ".join(query.split())
        rewritten = normalized
        replacements = {
            "进库": "进入知识库",
            "成功了没": "是否成功",
            "成功没": "是否成功",
            "怎么看": "如何查看",
        }
        for source, target in replacements.items():
            rewritten = rewritten.replace(source, target)
        keywords = list(dict.fromkeys(tokenize(rewritten)))
        return {
            "rewritten_query": rewritten,
            "keywords": keywords[:8],
            "intent": "search_knowledge_base",
        }

    def rerank(self, query: str, chunks: list[KnowledgeChunk]) -> list[tuple[str, float, str]]:
        """用词项重合度模拟 LLM 重排。

        参数:
            query: 改写后的查询。
            chunks: 待重排的候选知识块。

        返回:
            `(chunk_id, score, reason)` 列表，按 score 从高到低排序。
        """

        query_terms = set(tokenize(query))
        ranked: list[tuple[str, float, str]] = []
        for chunk in chunks:
            chunk_terms = set(tokenize(chunk.content))
            overlap = len(query_terms & chunk_terms)
            score = overlap / max(len(query_terms), 1)
            ranked.append((chunk.chunk_id, score, f"term_overlap={overlap}"))
        return sorted(ranked, key=lambda item: item[1], reverse=True)

    def _chunk_from_table(
        self,
        parsed: ParsedDocument,
        table: ParsedElement,
        asset_by_id: dict[str, Asset],
    ) -> KnowledgeChunk:
        """把表格元素转写为一个陈述型知识块。

        参数:
            parsed: 表格所属解析文档。
            table: 表格解析元素。
            asset_by_id: 当前文档资源 ID 到资源对象的映射。

        返回:
            由表格行和表头组合得到的自然语言知识块。
        """

        rows = []
        for child in table.children:
            if child.text:
                rows.append(child.text.replace("; ", "，"))
        content = "；".join(rows)
        if content:
            content = f"{self._title_prefix(table)}表格内容可转写为以下陈述：{content}。"
        return self._new_chunk(parsed, content, [table], asset_by_id, detected_type="relational")

    def _chunk_from_elements(
        self,
        parsed: ParsedDocument,
        elements: list[ParsedElement],
        asset_by_id: dict[str, Asset],
    ) -> KnowledgeChunk:
        """把普通解析元素合并成一个知识块。

        参数:
            parsed: 元素所属解析文档。
            elements: 待合并的段落或其他普通元素。
            asset_by_id: 当前文档资源 ID 到资源对象的映射。

        返回:
            包含标题路径、正文和资源说明的陈述型知识块。
        """

        text = " ".join(element.text for element in elements if element.text).strip()
        section = elements[-1].source_location.section_path if elements else [parsed.title]
        prefix = " > ".join(section)
        asset_texts = []
        for element in elements:
            for asset_id in element.assets:
                asset = asset_by_id.get(asset_id)
                if asset and asset.extracted_text:
                    asset_texts.append(asset.extracted_text)
        content = f"{prefix}：{text}"
        if asset_texts:
            content += " 关联资源说明：" + "；".join(asset_texts)
        return self._new_chunk(parsed, content, elements, asset_by_id, detected_type="declarative")

    def _new_chunk(
        self,
        parsed: ParsedDocument,
        content: str,
        elements: list[ParsedElement],
        asset_by_id: dict[str, Asset],
        detected_type: str,
    ) -> KnowledgeChunk:
        """构造标准 `KnowledgeChunk` 对象。

        参数:
            parsed: 知识块所属解析文档。
            content: 知识块正文。
            elements: 支撑该知识块的解析元素。
            asset_by_id: 当前文档资源 ID 到资源对象的映射。
            detected_type: 规则判断出的潜在知识类型，仅写入元数据。

        返回:
            已分配 `chunk_id`、资源引用和来源引用的知识块。
        """

        self._chunk_seq += 1
        asset_ids = list(dict.fromkeys(asset_id for element in elements for asset_id in element.assets))
        asset_refs = []
        for asset_id in asset_ids:
            asset = asset_by_id.get(asset_id)
            if asset is None:
                continue
            asset_refs.append(
                AssetRef(
                    asset_id=asset.asset_id,
                    asset_type=asset.asset_type,
                    storage_uri=asset.storage_uri,
                    caption=asset.extracted_text,
                )
            )
        return KnowledgeChunk(
            chunk_id=f"chunk_{self._chunk_seq:04d}",
            doc_id=parsed.doc_id,
            content=_normalize_sentence(content),
            knowledge_type="declarative",
            assets=asset_refs,
            source_refs=[
                SourceRef(
                    doc_id=element.doc_id,
                    element_id=element.element_id,
                    source_location=element.source_location,
                )
                for element in elements
            ],
            metadata={
                "title": parsed.title,
                "title_path": elements[-1].source_location.section_path if elements else [parsed.title],
                "detected_type": detected_type,
                "created_by": "mock-llm",
            },
        )

    @staticmethod
    def _title_prefix(element: ParsedElement) -> str:
        """根据元素来源位置生成标题路径前缀。

        参数:
            element: 解析元素。

        返回:
            形如 `文档 > 章节：` 的字符串；没有标题路径时返回空字符串。
        """

        section = " > ".join(element.source_location.section_path)
        return f"{section}：" if section else ""


def _normalize_sentence(text: str) -> str:
    """规范化知识块正文的空白和句末标点。

    参数:
        text: 原始正文。

    返回:
        压缩空白后的正文；如果末尾没有句号、问号或感叹号，则自动补中文句号。
    """

    normalized = " ".join(text.split())
    if normalized and normalized[-1] not in ".。!?！？":
        normalized += "。"
    return normalized
