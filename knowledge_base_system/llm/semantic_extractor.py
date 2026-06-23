"""语义抽取模块 — 通过 LLM 将解析元素转换为结构化的知识块。

核心流程：
1. 全文优先：token 不超安全阈值时所有元素一次提交 LLM
2. 递进降级：超限或 LLM 失败时按标题层级递进切分（h1→h2→h3→…）
3. 语义切分兜底：标题耗尽后用 embedding 相似度断点切分
4. Token 硬切兜底：embedding 不可用时按 token 上限硬切（20% 重叠）
5. 最终兜底：_fallback_chunks 纯文本拼接
"""

import json
import logging
from typing import Any

from app.core.config import settings
from app.core.models import (
    Asset,
    AssetRef,
    KnowledgeChunk,
    KnowledgeType,
    ParsedElement,
    Render,
    SourceRef,
    compute_hash,
)
from llm.prompts import build_extraction_messages
from llm.volcengine_client import llm_client

logger = logging.getLogger(__name__)


def _safe_knowledge_type(raw_value: str | None) -> KnowledgeType:
    """将原始 knowledge_type 字符串安全转换为 KnowledgeType 枚举。

    未知或缺失值时回退为 declarative。
    """
    if raw_value is None:
        return KnowledgeType.declarative
    try:
        return KnowledgeType(raw_value)
    except ValueError:
        logger.warning("Unknown knowledge_type '%s', falling back to declarative", raw_value)
        return KnowledgeType.declarative


EXTRACT_SCHEMA = {"required": ["chunks"]}


class SemanticExtractor:
    """语义抽取器 — 通过 LLM 将 ParsedElement 列表转换为 KnowledgeChunk 列表。

    全文优先策略：95%+ 的文档一次 LLM 调用即可完成抽取。
    极端大文档触发递进降级：h1 → h2 → h3 → … → embedding 切分 → token 硬切。
    LLM 不可用或返回空结果时自动回退为 fallback chunk。
    """

    def __init__(self) -> None:
        self._max_tokens = settings.max_window_tokens
        # 安全阈值：上下文窗口 × 0.8，给 prompt 模板和 LLM 输出留 20% buffer
        self._safe_threshold = int(settings.context_window_tokens * 0.8)

    def extract(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str = "通用",
    ) -> list[KnowledgeChunk]:
        """主入口：全文优先 → 递进降级。

        1. 全文 token < 安全阈值 → 单次 LLM 调用（95%+ 文档走此路径）
        2. 超限或 LLM 失败 → _split_recursive 按标题层级递进切分
        3. 最深层仍失败 → _fallback_chunks 纯文本兜底
        """
        if not elements:
            return []

        estimated = self._estimate_tokens(elements)
        if estimated < self._safe_threshold:
            try:
                chunks = self._extract_section(elements, assets, category)
                if self._chunks_have_content(chunks):
                    return chunks
                logger.warning("全文 LLM 返回空结果，进入降级路径")
            except Exception:
                logger.exception("全文 LLM 调用失败，进入降级路径")

        # 降级路径：按标题层级递进切分
        return self._split_recursive(elements, assets, category, level=1)

    @staticmethod
    def _chunks_have_content(chunks: list[KnowledgeChunk]) -> bool:
        """检查 chunk 列表是否有实际文本内容。"""
        if not chunks:
            return False
        return any(c.content.strip() for c in chunks)

    # ── 递进降级切分 ──────────────────────────────────────────────

    def _split_at_heading_level(
        self, elements: list[ParsedElement], level: int
    ) -> list[list[ParsedElement]]:
        """在指定 heading_level 处切分 elements。

        返回 sections 列表，每个 section 以该层级的标题元素开头。
        如果整个 elements 中没有目标层级的标题，返回单元素包装列表。
        """
        sections: list[list[ParsedElement]] = []
        current: list[ParsedElement] = []

        for el in elements:
            if (
                el.element_type.value == "title"
                and el.metadata.get("heading_level") == level
            ):
                if current:
                    sections.append(current)
                current = [el]
            else:
                current.append(el)

        if current:
            sections.append(current)

        return sections

    def _split_recursive(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
        level: int,
    ) -> list[KnowledgeChunk]:
        """递进切分核心：在 level 层级切分，仅对超限的 section 继续下钻。

        - 未超限的 section 直接走 _extract_section → LLM
        - 超限的 section → _split_recursive(level+1) 或更深层策略
        - 该层级切不出多个 section（无标题）→ _split_deeper_or_semantic 处理
        """
        if not elements:
            return []

        estimated = self._estimate_tokens(elements)
        if estimated < self._safe_threshold:
            try:
                chunks = self._extract_section(elements, assets, category)
                if self._chunks_have_content(chunks):
                    return chunks
            except Exception:
                logger.exception("section LLM 调用失败: level=%d", level)

        # 在当前层级切分
        sections = self._split_at_heading_level(elements, level)
        if len(sections) <= 1:
            # 该层级没有可用的标题切割点 → 尝试更深层或语义切分
            return self._split_deeper_or_semantic(elements, assets, category, level)

        all_chunks: list[KnowledgeChunk] = []
        for section in sections:
            section_est = self._estimate_tokens(section)
            if section_est < self._safe_threshold:
                try:
                    chunks = self._extract_section(section, assets, category)
                    if self._chunks_have_content(chunks):
                        all_chunks.extend(chunks)
                        continue
                except Exception:
                    logger.exception("section LLM 失败, 下钻: level=%d", level)
                # LLM 失败 → 继续下钻
                all_chunks.extend(
                    self._split_deeper_or_semantic(section, assets, category, level + 1)
                )
            else:
                # 超限 → 下钻到更深层级
                all_chunks.extend(
                    self._split_recursive(section, assets, category, level + 1)
                )

        return all_chunks

    def _split_deeper_or_semantic(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
        level: int,
    ) -> list[KnowledgeChunk]:
        """当前层级无更多标题时：更深层标题 → embedding 语义切分 → token 硬切。

        最深层级仍 LLM 失败时走 _fallback_chunks 纯文本兜底。
        """
        # 先尝试更深层标题（level+1 ~ level+3）
        for deeper_level in range(level + 1, min(level + 4, 7)):
            deeper_sections = self._split_at_heading_level(elements, deeper_level)
            if len(deeper_sections) > 1:
                all_chunks: list[KnowledgeChunk] = []
                for section in deeper_sections:
                    all_chunks.extend(
                        self._split_recursive(section, assets, category, deeper_level)
                    )
                return all_chunks

        # 尝试 embedding 语义切分
        try:
            subsections = self._split_by_semantic(elements)
            if len(subsections) > 1:
                all_chunks: list[KnowledgeChunk] = []
                for sub in subsections:
                    sub_est = self._estimate_tokens(sub)
                    if sub_est < self._safe_threshold:
                        try:
                            chunks = self._extract_section(sub, assets, category)
                            if self._chunks_have_content(chunks):
                                all_chunks.extend(chunks)
                                continue
                        except Exception:
                            pass
                    # 仍超限或 LLM 失败 → token 硬切
                    all_chunks.extend(self._split_section(sub, assets, category))
                return all_chunks
        except Exception:
            logger.exception("embedding 语义切分失败，降级为 token 硬切")

        # 最终兜底：token 硬切
        return self._split_section(elements, assets, category)

    def _split_by_semantic(
        self, elements: list[ParsedElement]
    ) -> list[list[ParsedElement]]:
        """相邻元素 embedding 相似度断点切分。

        计算相邻元素的 embedding 余弦相似度，在相似度最低的 30% 位置切分。
        embedding 不可用时返回原列表的单元素包装。
        """
        if len(elements) < 2:
            return [list(elements)]

        texts = [el.text for el in elements]
        if not all(texts) or len(texts) < 2:
            return [list(elements)]

        try:
            from llm.volcengine_client import embedding_client as emb_client

            vectors = emb_client.embed_text(texts)
            if len(vectors) != len(texts):
                return [list(elements)]

            # 计算相邻相似度
            def _cosine(a: list[float], b: list[float]) -> float:
                dot = sum(x * y for x, y in zip(a, b))
                norm_a = sum(x * x for x in a) ** 0.5
                norm_b = sum(x * x for x in b) ** 0.5
                if norm_a == 0 or norm_b == 0:
                    return 0.0
                return dot / (norm_a * norm_b)

            similarities: list[float] = []
            for i in range(len(vectors) - 1):
                similarities.append(_cosine(vectors[i], vectors[i + 1]))

            if not similarities:
                return [list(elements)]

            # 在相似度最低的 30% 位置切分
            sorted_sims = sorted(similarities)
            threshold_idx = max(0, int(len(sorted_sims) * 0.3))
            threshold = sorted_sims[threshold_idx]
            split_indices = [
                i + 1
                for i, sim in enumerate(similarities)
                if sim <= threshold
            ]

            if not split_indices:
                return [list(elements)]

            # 按切分点构造子 sections
            sections: list[list[ParsedElement]] = []
            start = 0
            for idx in split_indices:
                if idx > start and idx < len(elements):
                    sections.append(elements[start:idx])
                    start = idx
            if start < len(elements):
                sections.append(elements[start:])
            return sections if len(sections) > 1 else [list(elements)]
        except Exception:
            logger.exception("embedding 相似度计算失败")
            return [list(elements)]

    def _split_section(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
    ) -> list[KnowledgeChunk]:
        """Token 硬切兜底：段落边界切分 + 20% 重叠 + 逐段 LLM 抽取。

        每段先尝试 LLM，失败后用 _fallback_chunks 纯文本兜底。
        """
        if not elements:
            return []

        result_chunks: list[KnowledgeChunk] = []
        current: list[ParsedElement] = []
        current_tokens = 0
        overlap_count = max(1, int(len(elements) * 0.2))

        for i, el in enumerate(elements):
            el_tokens = self._estimate_tokens([el])
            if current_tokens + el_tokens > self._max_tokens and current:
                # 当前窗口已满，抽取
                try:
                    chunks = self._extract_section(current, assets, category)
                    if self._chunks_have_content(chunks):
                        result_chunks.extend(chunks)
                    else:
                        result_chunks.extend(
                            self._fallback_chunks(current, assets, category)
                        )
                except Exception:
                    result_chunks.extend(
                        self._fallback_chunks(current, assets, category)
                    )

                # 重叠：保留尾部 20% 元素作为上下文衔接
                overlap_start = max(0, len(current) - overlap_count)
                current = current[overlap_start:] + [el]
                current_tokens = (
                    self._estimate_tokens(current[:overlap_count]) + el_tokens
                )
            else:
                current.append(el)
                current_tokens += el_tokens

        if current:
            try:
                chunks = self._extract_section(current, assets, category)
                if self._chunks_have_content(chunks):
                    result_chunks.extend(chunks)
                else:
                    result_chunks.extend(
                        self._fallback_chunks(current, assets, category)
                    )
            except Exception:
                result_chunks.extend(
                    self._fallback_chunks(current, assets, category)
                )

        return result_chunks

    @staticmethod
    def _estimate_tokens(elements: list[ParsedElement]) -> int:
        """粗略 token 估算：中文约 1.8 字符/token，计入 structured_data。"""
        parts: list[str] = []
        for el in elements:
            if el.text:
                parts.append(el.text)
            if el.structured_data:
                parts.append(json.dumps(el.structured_data, ensure_ascii=False))
        text = " ".join(parts)
        return max(1, int(len(text) / 1.8))

    # ── LLM 抽取 ─────────────────────────────────────────────────

    def _extract_section(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
    ) -> list[KnowledgeChunk]:
        """对单个 section 调用 LLM 抽取知识块。

        异常直接抛出，由上层处理降级路径。
        """
        title_path = self._get_title_path(elements)
        elements_json = self._elements_to_json(elements, assets)
        messages = build_extraction_messages(title_path, elements_json)

        data = llm_client.chat_json(messages, schema=EXTRACT_SCHEMA)
        return self._build_chunks(data, elements, assets, category)

    @staticmethod
    def _get_title_path(elements: list[ParsedElement]) -> list[str]:
        """从元素的 section_path 中提取标题路径。"""
        for el in elements:
            if el.source_location and el.source_location.section_path:
                return el.source_location.section_path
        return []

    @staticmethod
    def _elements_to_json(
        elements: list[ParsedElement],
        assets: list[Asset] | None = None,
    ) -> str:
        """将元素列表序列化为 LLM 输入 JSON，注入资源视觉描述。

        标题元素注入 heading_level；代码元素注入 language 字段。
        """
        # 构造资源描述查找表
        asset_descriptions: dict[str, dict[str, str]] = {}
        if assets:
            for asset in assets:
                if asset.extracted_text:
                    asset_descriptions[asset.asset_id] = {
                        "asset_id": asset.asset_id,
                        "asset_type": asset.asset_type.value,
                        "description": asset.extracted_text,
                    }

        items = []
        for el in elements:
            item: dict[str, Any] = {
                "element_id": el.element_id,
                "type": el.element_type.value,
                "text": el.text,
                "section_path": el.source_location.section_path,
            }
            # 标题元素注入层级信息，供 LLM 判断知识块边界
            if el.element_type.value == "title":
                heading_level = el.metadata.get("heading_level")
                if heading_level is not None:
                    item["heading_level"] = heading_level
            # 代码元素注入语言信息，供 LLM 按语言路由处理
            if el.element_type.value == "code" and el.structured_data:
                language = el.structured_data.get("language")
                if language:
                    item["language"] = language
            if el.structured_data:
                item["structured_data"] = el.structured_data
            if el.asset_ids:
                item["asset_ids"] = el.asset_ids
                # 注入具有视觉描述的 Asset 信息
                descriptions = [
                    asset_descriptions[aid]
                    for aid in el.asset_ids
                    if aid in asset_descriptions
                ]
                if descriptions:
                    item["asset_descriptions"] = descriptions
            items.append(item)
        return json.dumps(items, ensure_ascii=False, indent=2)

    def _build_chunks(
        self,
        data: dict,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
    ) -> list[KnowledgeChunk]:
        """将 LLM 输出转换为 KnowledgeChunk 对象列表。

        不保留 relation 字段（该枚举已删除）；source_refs 为空时不强行全量兜底。
        """
        chunks: list[KnowledgeChunk] = []
        elements_by_id = {el.element_id: el for el in elements}
        assets_by_id = {a.asset_id: a for a in assets}

        for raw in data.get("chunks", []):
            content = raw.get("content", "")
            if not content:
                continue

            # ── 构造溯源引用 ──
            source_refs: list[SourceRef] = []
            raw_source_refs = raw.get("source_refs")
            if raw_source_refs is None:
                # 兼容旧格式 source_element_ids
                raw_source_refs = [
                    {"element_id": eid}
                    for eid in raw.get("source_element_ids", [])
                ]
            for raw_ref in raw_source_refs:
                if isinstance(raw_ref, str):
                    eid = raw_ref
                else:
                    eid = raw_ref.get("element_id")
                el = elements_by_id.get(eid)
                if el:
                    source_refs.append(
                        SourceRef(
                            doc_id=el.doc_id,
                            element_id=el.element_id,
                            source_location=el.source_location,
                        )
                    )
            # 不再强行全量兜底——LLM 未提供溯源则留空

            # ── 构造资源引用（无 relation 字段） ──
            asset_refs: list[AssetRef] = []
            raw_asset_refs = raw.get("asset_refs")
            if raw_asset_refs is None:
                # 兼容旧格式 asset_ids
                raw_asset_refs = [
                    {"asset_id": aid}
                    for aid in raw.get("asset_ids", [])
                ]
            for raw_ref in raw_asset_refs:
                if isinstance(raw_ref, str):
                    aid = raw_ref
                    linked_text = None
                    caption = None
                    render = Render(mode="inline", position="after_linked_text")
                else:
                    aid = raw_ref.get("asset_id")
                    linked_text = raw_ref.get("linked_text")
                    caption = raw_ref.get("caption")
                    render_data = raw_ref.get("render") or {}
                    render = Render(
                        mode=render_data.get("mode", "inline"),
                        position=render_data.get("position", "after_linked_text"),
                    )
                asset = assets_by_id.get(aid)
                if asset:
                    if not caption:
                        caption = (
                            asset.metadata.get("caption")
                            or asset.metadata.get("alt")
                            or f"{asset.asset_type.value}: {asset.original_uri}"
                        )
                    asset_refs.append(
                        AssetRef(
                            asset_id=asset.asset_id,
                            linked_text=linked_text,
                            caption=caption,
                            render=render,
                        )
                    )

            doc_id = elements[0].doc_id if elements else ""

            chunk = KnowledgeChunk(
                doc_id=doc_id,
                title=raw.get("title") or self._derive_title(content),
                content=content,
                content_hash=compute_hash(content),
                knowledge_type=_safe_knowledge_type(raw.get("knowledge_type")),
                category=category,
                asset_refs=asset_refs,
                source_refs=source_refs,
                metadata={
                    "title_path": self._get_title_path(elements),
                    "language": "zh-CN",
                },
            )
            chunks.append(chunk)

        return chunks

    @staticmethod
    def _derive_title(content: str) -> str:
        """从内容首句派生简短标题。"""
        first = content.split("。")[0].split("；")[0].strip()
        if len(first) > 40:
            first = first[:40] + "..."
        return first

    def _fallback_chunks(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        category: str,
    ) -> list[KnowledgeChunk]:
        """LLM 不可用或返回空结果时，保留可检索的解析文本。"""
        text_parts = [el.text.strip() for el in elements if el.text and el.text.strip()]
        content = "\n".join(text_parts).strip()
        if not content:
            return []

        source_refs = [
            SourceRef(
                doc_id=el.doc_id,
                element_id=el.element_id,
                source_location=el.source_location,
            )
            for el in elements
        ]
        asset_by_id = {asset.asset_id: asset for asset in assets}
        asset_refs: list[AssetRef] = []
        seen_assets: set[str] = set()
        for el in elements:
            for asset_id in el.asset_ids:
                if asset_id in seen_assets or asset_id not in asset_by_id:
                    continue
                asset = asset_by_id[asset_id]
                asset_refs.append(
                    AssetRef(
                        asset_id=asset.asset_id,
                        caption=asset.metadata.get("alt") or asset.original_uri,
                    )
                )
                seen_assets.add(asset_id)

        doc_id = elements[0].doc_id
        return [
            KnowledgeChunk(
                doc_id=doc_id,
                title=self._derive_title(content),
                content=content,
                content_hash=compute_hash(content),
                knowledge_type=KnowledgeType.declarative,
                category=category,
                asset_refs=asset_refs,
                source_refs=source_refs,
                metadata={
                    "title_path": self._get_title_path(elements),
                    "language": "zh-CN",
                    "fallback": "llm_empty_or_failed",
                },
            )
        ]
