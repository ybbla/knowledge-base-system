"""Markdown 文档解析器。

提供轻量级 Markdown 解析能力，将原始文档转换为标准化的结构化元素、
资源和嵌入文档列表。MVP 阶段只处理标题、段落、管道表格、图片语法、
视频 URL 和嵌入文档链接。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Asset, ParsedDocument, ParsedElement, RawDocument, SourceLocation

# --- 正则模式：用于从 Markdown 文本中提取资源引用 ---

# 匹配 Markdown 图片语法：![alt](url)
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
# 匹配原始 URL（http/https），作为未使用 Markdown 语法的资源引用
URL_RE = re.compile(r"https?://[^\s)]+")
# 匹配 Markdown 链接语法：[label](url)，用于识别嵌入文档链接
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

# --- 媒体类型常量：通过文件扩展名判断资源类型 ---

# 视频文件扩展名
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m3u8")
# 可嵌入文档的扩展名（这些文件可作为子文档递归解析）
DOC_EXTENSIONS = (".md", ".txt", ".html", ".docx", ".pdf", ".xlsx", ".pptx")


@dataclass
class ParseOptions:
    """文档解析选项。

    参数:
        max_depth: 嵌入文档递归解析的最大深度。MVP 阶段用它防止链接文档
            无限展开，正式版本还应增加资源大小、URL 白名单、总元素数量等限制。
    """

    max_depth: int = 2


class MarkdownParser:
    """MVP 阶段使用的轻量 Markdown 解析器。

    该解析器只处理最小闭环需要的 Markdown 子集：标题、段落、管道表格、
    图片语法、视频 URL 和嵌入文档链接。它的职责是生成标准化结构元素，
    不负责最终语义切块。
    """

    def __init__(self) -> None:
        """初始化解析器内部的元素和资源自增序列。"""

        self._element_seq = 0
        self._asset_seq = 0

    def parse(
        self,
        document: RawDocument,
        embedded_content_by_uri: dict[str, str] | None = None,
        options: ParseOptions | None = None,
    ) -> ParsedDocument:
        """解析单个 Markdown 文档。

        参数:
            document: 待解析的原始文档。
            embedded_content_by_uri: 嵌入文档 URI 到文档内容的映射。MVP 阶段
                用它模拟下载远程嵌入文档。
            options: 解析选项，当前主要控制递归深度。

        返回:
            标准化后的 `ParsedDocument`，包含结构元素、资源和待递归处理的
            嵌入文档列表。
        """

        embedded_content_by_uri = embedded_content_by_uri or {}
        options = options or ParseOptions()
        elements: list[ParsedElement] = []
        assets: list[Asset] = []
        embedded_documents: list[RawDocument] = []
        section_path: list[str] = [document.title]
        lines = document.content.splitlines()
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # 跳过空行
            if not line:
                i += 1
                continue

            # 分支一：标题行 —— 更新标题路径并生成 title 元素
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if heading_match:
                level = len(heading_match.group(1))
                heading = heading_match.group(2).strip()
                section_path = section_path[:level]
                section_path.append(heading)
                elements.append(
                    self._element(
                        document,
                        "title",
                        heading,
                        section_path,
                        metadata={"level": level},
                    )
                )
                i += 1
                continue

            # 分支二：管道表格 —— 收集连续的表格行并整体解析
            if self._is_table_start(lines, i):
                table_lines: list[str] = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    table_lines.append(lines[i].strip())
                    i += 1
                table_element, table_assets, table_embedded = self._parse_table(
                    document,
                    table_lines,
                    section_path,
                    embedded_content_by_uri,
                    options,
                )
                elements.append(table_element)
                assets.extend(table_assets)
                embedded_documents.extend(table_embedded)
                continue

            # 分支三：段落 —— 收集连续非空行，直到遇到空行、标题或表格
            paragraph_lines = [line]
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if not next_line:
                    i += 1
                    break
                if re.match(r"^(#{1,6})\s+.+$", next_line) or self._is_table_start(lines, i):
                    break
                paragraph_lines.append(next_line)
                i += 1

            text = " ".join(paragraph_lines)
            # 从段落文本中提取图片、视频等资源和嵌入文档链接
            element_assets, element_embedded = self._extract_assets_and_embedded(
                document,
                text,
                section_path,
                embedded_content_by_uri,
                options,
            )
            assets.extend(element_assets)
            embedded_documents.extend(element_embedded)
            elements.append(
                self._element(
                    document,
                    "paragraph",
                    IMAGE_RE.sub(lambda m: m.group(1), text),
                    section_path,
                    assets=[asset.asset_id for asset in element_assets],
                )
            )

        return ParsedDocument(
            doc_id=document.doc_id,
            title=document.title,
            root_elements=elements,
            assets=assets,
            embedded_documents=embedded_documents,
            metadata={
                "source_uri": document.source_uri,
                "parent_doc_id": document.parent_doc_id,
                "depth": document.depth,
            },
        )

    def _parse_table(
        self,
        document: RawDocument,
        table_lines: list[str],
        section_path: list[str],
        embedded_content_by_uri: dict[str, str],
        options: ParseOptions,
    ) -> tuple[ParsedElement, list[Asset], list[RawDocument]]:
        """解析 Markdown 管道表格为标准表格元素。

        参数:
            document: 表格所属原始文档。
            table_lines: 连续的 Markdown 表格行。
            section_path: 当前标题路径。
            embedded_content_by_uri: 嵌入文档内容映射。
            options: 解析选项。

        返回:
            三元组：表格元素、表格内提取到的资源、表格内发现的嵌入文档。

        说明:
            表格不会在最终知识块中保留原始表格形态。这里先保留行列和表头
            语义，后续由 LLM/Mock LLM 转写为自然语言陈述。
        """

        rows = [self._split_table_row(line) for line in table_lines]
        headers = rows[0] if rows else []
        data_rows = rows[2:] if len(rows) > 1 and self._is_separator_row(rows[1]) else rows[1:]
        all_assets: list[Asset] = []
        all_embedded: list[RawDocument] = []
        child_elements: list[ParsedElement] = []

        for row_index, row in enumerate(data_rows, start=1):
            cell_texts: list[str] = []
            for col_index, cell in enumerate(row):
                cell_assets, cell_embedded = self._extract_assets_and_embedded(
                    document,
                    cell,
                    section_path,
                    embedded_content_by_uri,
                    options,
                )
                all_assets.extend(cell_assets)
                all_embedded.extend(cell_embedded)
                header = headers[col_index] if col_index < len(headers) else f"column_{col_index + 1}"
                clean_cell = IMAGE_RE.sub(lambda m: m.group(1), cell).strip()
                cell_texts.append(f"{header}: {clean_cell}")
            child_elements.append(
                self._element(
                    document,
                    "table_row",
                    "; ".join(cell_texts),
                    section_path,
                    assets=[asset.asset_id for asset in all_assets],
                    source_location=SourceLocation(section_path=list(section_path), row=row_index),
                )
            )

        table_text = "\n".join(child.text for child in child_elements)
        table = self._element(
            document,
            "table",
            table_text,
            section_path,
            children=child_elements,
            metadata={"headers": headers, "row_count": len(data_rows)},
        )
        return table, all_assets, all_embedded

    def _extract_assets_and_embedded(
        self,
        document: RawDocument,
        text: str,
        section_path: list[str],
        embedded_content_by_uri: dict[str, str],
        options: ParseOptions,
    ) -> tuple[list[Asset], list[RawDocument]]:
        """从一段文本中提取资源和嵌入文档。

        参数:
            document: 文本所属原始文档。
            text: 待扫描的段落或表格单元格文本。
            section_path: 当前标题路径，用于写入资源元数据。
            embedded_content_by_uri: 可被递归解析的嵌入文档内容映射。
            options: 解析选项，主要用于控制递归深度。

        返回:
            二元组：提取到的资源列表和可继续递归处理的嵌入文档列表。

        说明:
            MVP 阶段不真实下载图片或视频，只创建 `memory://` 资源引用；
            嵌入文档只有在 `embedded_content_by_uri` 中存在内容时才会进入队列。
        """

        assets: list[Asset] = []
        embedded_documents: list[RawDocument] = []
        embedded_uris: set[str] = set()

        # 第一遍：提取 Markdown 图片语法 (![alt](url))
        for alt, uri in IMAGE_RE.findall(text):
            asset = self._asset(
                "image",
                uri,
                extracted_text=f"Image resource: {alt or uri}",
                metadata={"alt": alt, "section_path": section_path},
            )
            assets.append(asset)

        # 第二遍：从裸 URL 中识别视频资源和可嵌入文档
        for uri in URL_RE.findall(text):
            normalized = uri.rstrip(".,;，。；")
            lower_uri = normalized.lower()
            if lower_uri.endswith(VIDEO_EXTENSIONS):
                assets.append(
                    self._asset(
                        "video",
                        normalized,
                        extracted_text=f"Video resource referenced near: {self._shorten(text)}",
                        metadata={"section_path": section_path},
                    )
                )
            elif lower_uri.endswith(DOC_EXTENSIONS) and document.depth < options.max_depth:
                content = embedded_content_by_uri.get(normalized)
                if content is not None and normalized not in embedded_uris:
                    embedded_uris.add(normalized)
                    embedded_documents.append(
                        RawDocument(
                            doc_id=self._stable_doc_id(normalized),
                            title=normalized.rsplit("/", 1)[-1],
                            source_type=lower_uri.rsplit(".", 1)[-1],
                            source_uri=normalized,
                            content=content,
                            parent_doc_id=document.doc_id,
                            depth=document.depth + 1,
                        )
                    )

        # 第三遍：从 Markdown 链接语法 ([label](url)) 中识别嵌入文档
        for label, uri in MARKDOWN_LINK_RE.findall(text):
            normalized = uri.rstrip(".,;，。；")
            lower_uri = normalized.lower()
            if lower_uri.endswith(DOC_EXTENSIONS) and document.depth < options.max_depth:
                content = embedded_content_by_uri.get(normalized)
                if content is not None and normalized not in embedded_uris:
                    embedded_uris.add(normalized)
                    embedded_documents.append(
                        RawDocument(
                            doc_id=self._stable_doc_id(normalized),
                            title=label or normalized.rsplit("/", 1)[-1],
                            source_type=lower_uri.rsplit(".", 1)[-1],
                            source_uri=normalized,
                            content=content,
                            parent_doc_id=document.doc_id,
                            depth=document.depth + 1,
                        )
                    )

        return assets, embedded_documents

    def _element(
        self,
        document: RawDocument,
        element_type: str,
        text: str,
        section_path: list[str],
        children: list[ParsedElement] | None = None,
        assets: list[str] | None = None,
        metadata: dict | None = None,
        source_location: SourceLocation | None = None,
    ) -> ParsedElement:
        """创建一个带有统一 ID 和来源位置的解析元素。

        参数:
            document: 元素所属原始文档。
            element_type: 元素类型，例如 `paragraph`、`table`、`table_row`。
            text: 元素的主要文本内容。
            section_path: 当前标题路径。
            children: 子元素列表，主要用于表格行。
            assets: 元素关联的资源 ID。
            metadata: 元素扩展元数据。
            source_location: 显式来源位置；未传入时会根据标题路径创建。

        返回:
            已分配 `element_id` 的 `ParsedElement`。
        """

        self._element_seq += 1
        return ParsedElement(
            element_id=f"el_{self._element_seq:04d}",
            doc_id=document.doc_id,
            element_type=element_type,
            text=text.strip(),
            children=children or [],
            assets=assets or [],
            source_location=source_location or SourceLocation(section_path=list(section_path)),
            metadata=metadata or {},
        )

    def _asset(self, asset_type: str, uri: str, extracted_text: str, metadata: dict) -> Asset:
        """创建一个 MVP 内存资源对象。

        参数:
            asset_type: 资源类型，例如 `image` 或 `video`。
            uri: 原始资源 URI。
            extracted_text: 资源的保守语义描述。
            metadata: 资源扩展元数据。

        返回:
            带有 `memory://` 存储 URI 的 `Asset`。
        """

        self._asset_seq += 1
        asset_id = f"asset_{self._asset_seq:04d}"
        return Asset(
            asset_id=asset_id,
            asset_type=asset_type,
            original_uri=uri,
            storage_uri=f"memory://{asset_id}",
            extracted_text=extracted_text,
            metadata=metadata,
        )

    @staticmethod
    def _is_table_start(lines: list[str], index: int) -> bool:
        """判断当前位置是否可能是 Markdown 管道表格的开始。

        参数:
            lines: 文档所有行。
            index: 当前行下标。

        返回:
            如果当前行和下一行都以管道符开头，则返回 `True`。
        """

        return (
            index + 1 < len(lines)
            and lines[index].strip().startswith("|")
            and lines[index + 1].strip().startswith("|")
        )

    @staticmethod
    def _split_table_row(line: str) -> list[str]:
        """把一行 Markdown 管道表格拆成单元格文本。

        参数:
            line: 原始表格行。

        返回:
            去掉首尾管道符和空白后的单元格列表。
        """

        return [cell.strip() for cell in line.strip().strip("|").split("|")]

    @staticmethod
    def _is_separator_row(row: list[str]) -> bool:
        """判断表格行是否是 Markdown 表头分隔行。

        参数:
            row: 已拆分的单元格列表。

        返回:
            当所有非空单元格都匹配 `---`、`:---`、`---:` 等分隔符形态时返回
            `True`。
        """

        return all(re.match(r"^:?-{3,}:?$", cell.strip()) for cell in row if cell.strip())

    @staticmethod
    def _shorten(text: str, limit: int = 80) -> str:
        """截断长文本，生成资源附近上下文摘要。

        参数:
            text: 原始文本。
            limit: 最大字符数。

        返回:
            未超过限制时返回原文，超过限制时返回截断文本并追加省略号。
        """

        return text if len(text) <= limit else text[:limit] + "..."

    @staticmethod
    def _stable_doc_id(uri: str) -> str:
        """根据 URI 生成稳定但简化的嵌入文档 ID。

        参数:
            uri: 嵌入文档的原始 URI。

        返回:
            只包含字母、数字和下划线的文档 ID。MVP 阶段用于演示递归解析，
            正式版本建议使用内容 hash 或数据库主键。
        """

        safe = re.sub(r"[^a-zA-Z0-9]+", "_", uri).strip("_").lower()
        return f"doc_{safe[-48:]}"
