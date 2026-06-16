import json
import logging
from typing import Any

from app.core.config import settings
from app.core.models import (
    Asset,
    AssetRef,
    AssetRelation,
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
    """Coerce a raw knowledge_type string to KnowledgeType enum.
    Unknown / missing values fall back to declarative."""
    if raw_value is None:
        return KnowledgeType.declarative
    try:
        return KnowledgeType(raw_value)
    except ValueError:
        logger.warning("Unknown knowledge_type '%s', falling back to declarative", raw_value)
        return KnowledgeType.declarative


EXTRACT_SCHEMA = {"required": ["chunks"]}


class SemanticExtractor:
    """Convert ParsedElements into KnowledgeChunks via LLM."""

    def __init__(self) -> None:
        self._max_tokens = settings.max_window_tokens

    def extract(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        ingest_job_id: str,
        category: str = "\u901a\u7528",
    ) -> list[KnowledgeChunk]:
        """Main entry: window elements, call LLM, return KnowledgeChunks."""
        if not elements:
            return []

        windows = self._build_windows(elements)
        all_chunks: list[KnowledgeChunk] = []

        for window in windows:
            chunks = self._process_window(window, assets, ingest_job_id, category)
            all_chunks.extend(chunks)

        return all_chunks

    # ── windowing ────────────────────────────────────────────────

    def _build_windows(self, elements: list[ParsedElement]) -> list[list[ParsedElement]]:
        """Split elements into windows at h2 boundaries, respecting token limit."""
        # First, split by h2 headings
        sections: list[list[ParsedElement]] = []
        current: list[ParsedElement] = []

        for el in elements:
            if (
                el.element_type.value == "title"
                and el.metadata.get("heading_level") == 2
            ):
                if current:
                    sections.append(current)
                current = [el]
            else:
                current.append(el)

        if current:
            sections.append(current)

        # Then split large sections by token limit
        windows: list[list[ParsedElement]] = []
        for section in sections:
            if self._estimate_tokens(section) > self._max_tokens:
                windows.extend(self._split_section(section))
            else:
                windows.append(section)

        return windows

    def _split_section(
        self, section: list[ParsedElement]
    ) -> list[list[ParsedElement]]:
        """Split a section at paragraph boundaries, overlapping last element."""
        result: list[list[ParsedElement]] = []
        current: list[ParsedElement] = []
        current_tokens = 0

        for el in section:
            el_tokens = self._estimate_tokens([el])
            if current_tokens + el_tokens > self._max_tokens and current:
                result.append(current)
                # Overlap: keep last element
                last = current[-1]
                current = [last, el]
                current_tokens = self._estimate_tokens([last]) + el_tokens
            else:
                current.append(el)
                current_tokens += el_tokens

        if current:
            result.append(current)

        return result

    @staticmethod
    def _estimate_tokens(elements: list[ParsedElement]) -> int:
        """Rough token estimation: ~1.5 chars per token for Chinese."""
        text = " ".join(el.text for el in elements if el.text)
        return max(1, len(text) // 2)

    # ── LLM processing ───────────────────────────────────────────

    def _process_window(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        ingest_job_id: str,
        category: str,
    ) -> list[KnowledgeChunk]:
        """Send one window to LLM and parse resulting chunks."""
        title_path = self._get_title_path(elements)
        elements_json = self._elements_to_json(elements, assets)
        messages = build_extraction_messages(title_path, elements_json)

        try:
            data = llm_client.chat_json(messages, schema=EXTRACT_SCHEMA)
        except Exception:
            logger.exception("LLM extraction failed for window: %s", title_path)
            return self._fallback_chunks(elements, assets, ingest_job_id, category)

        chunks = self._build_chunks(data, elements, assets, ingest_job_id, category)
        if not chunks:
            logger.warning("LLM extraction returned no chunks, using fallback chunk")
            return self._fallback_chunks(elements, assets, ingest_job_id, category)
        return chunks

    @staticmethod
    def _get_title_path(elements: list[ParsedElement]) -> list[str]:
        """Extract title path from section_path of elements."""
        for el in elements:
            if el.source_location and el.source_location.section_path:
                return el.source_location.section_path
        return []

    @staticmethod
    def _elements_to_json(
        elements: list[ParsedElement],
        assets: list[Asset] | None = None,
    ) -> str:
        """Serialize elements for LLM input, injecting asset visual descriptions."""
        # Build a lookup of assets with extracted_text
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
                "source_location": el.source_location.model_dump(mode="json"),
            }
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
            if el.embedded_doc_id:
                item["embedded_doc_id"] = el.embedded_doc_id
            items.append(item)
        return json.dumps(items, ensure_ascii=False, indent=2)

    def _build_chunks(
        self,
        data: dict,
        elements: list[ParsedElement],
        assets: list[Asset],
        ingest_job_id: str,
        category: str,
    ) -> list[KnowledgeChunk]:
        """Convert LLM output to KnowledgeChunk objects."""
        chunks: list[KnowledgeChunk] = []
        elements_by_id = {el.element_id: el for el in elements}
        assets_by_id = {a.asset_id: a for a in assets}

        for raw in data.get("chunks", []):
            content = raw.get("content", "")
            if not content:
                continue

            # Build source refs. Accept the old source_element_ids shape as a
            # compatibility fallback, but the prompt now asks for source_refs.
            source_refs = []
            raw_source_refs = raw.get("source_refs")
            if raw_source_refs is None:
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
                            doc_version=el.doc_version,
                            element_id=el.element_id,
                            source_location=el.source_location,
                        )
                    )
            if not source_refs and elements:
                # Keep every chunk traceable even if the model omitted refs.
                source_refs = [
                    SourceRef(
                        doc_id=el.doc_id,
                        doc_version=el.doc_version,
                        element_id=el.element_id,
                        source_location=el.source_location,
                    )
                    for el in elements
                ]

            # Build asset refs. Accept the old asset_ids shape as a compatibility
            # fallback, but the prompt now asks for full asset_refs.
            asset_refs = []
            raw_asset_refs = raw.get("asset_refs")
            if raw_asset_refs is None:
                raw_asset_refs = [
                    {"asset_id": aid, "relation": AssetRelation.evidence.value}
                    for aid in raw.get("asset_ids", [])
                ]
            for raw_ref in raw_asset_refs:
                if isinstance(raw_ref, str):
                    aid = raw_ref
                    relation = AssetRelation.evidence
                    linked_text = None
                    caption = None
                    render = Render(mode="inline", position="after_linked_text")
                else:
                    aid = raw_ref.get("asset_id")
                    relation_value = raw_ref.get(
                        "relation", AssetRelation.evidence.value
                    )
                    try:
                        relation = AssetRelation(relation_value)
                    except ValueError:
                        relation = AssetRelation.evidence
                    linked_text = raw_ref.get("linked_text")
                    caption = raw_ref.get("caption")
                    render_data = raw_ref.get("render") or {}
                    render = Render(
                        mode=render_data.get("mode", "inline"),
                        position=render_data.get(
                            "position", "after_linked_text"
                        ),
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
                            relation=relation,
                            linked_text=linked_text,
                            caption=caption,
                            render=render,
                        )
                    )

            doc_id = elements[0].doc_id if elements else ""
            doc_version = elements[0].doc_version if elements else 1

            chunk = KnowledgeChunk(
                doc_id=doc_id,
                doc_version=doc_version,
                title=raw.get("title") or self._derive_title(content),
                content=content,
                content_hash=compute_hash(content),
                knowledge_type=_safe_knowledge_type(raw.get("knowledge_type")),
                category=category,
                asset_refs=asset_refs,
                source_refs=source_refs,
                ingest_job_id=ingest_job_id,
                metadata={
                    "title_path": self._get_title_path(elements),
                    "language": "zh-CN",
                },
            )
            chunks.append(chunk)

        return chunks

    @staticmethod
    def _derive_title(content: str) -> str:
        """Derive a short title from chunk content."""
        # Take first sentence or first 40 chars
        first = content.split("。")[0].split("；")[0].strip()
        if len(first) > 40:
            first = first[:40] + "..."
        return first

    def _fallback_chunks(
        self,
        elements: list[ParsedElement],
        assets: list[Asset],
        ingest_job_id: str,
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
                doc_version=el.doc_version,
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
                        relation=AssetRelation.illustration,
                        caption=asset.metadata.get("alt") or asset.original_uri,
                    )
                )
                seen_assets.add(asset_id)

        doc_id = elements[0].doc_id
        doc_version = elements[0].doc_version
        return [
            KnowledgeChunk(
                doc_id=doc_id,
                doc_version=doc_version,
                title=self._derive_title(content),
                content=content,
                content_hash=compute_hash(content),
                knowledge_type=KnowledgeType.declarative,
                category=category,
                asset_refs=asset_refs,
                source_refs=source_refs,
                ingest_job_id=ingest_job_id,
                metadata={
                    "title_path": self._get_title_path(elements),
                    "language": "zh-CN",
                    "fallback": "llm_empty_or_failed",
                },
            )
        ]
