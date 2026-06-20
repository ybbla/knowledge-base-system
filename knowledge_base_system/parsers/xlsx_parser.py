import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.utils.exceptions import InvalidFileException

from app.core.models import (
    Asset,
    AssetStatus,
    AssetType,
    Document,
    ElementType,
    ParsedElement,
    SourceLocation,
    compute_hash,
)
from app.core.paths import resolve_file_uri
from parsers.base import DocumentParser, ParseResult


@dataclass
class _CellInfo:
    row: int
    col: int
    coordinate: str
    text: str = ""
    asset_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Region:
    min_row: int
    max_row: int
    min_col: int
    max_col: int

    @property
    def row_count(self) -> int:
        return self.max_row - self.min_row + 1

    @property
    def col_count(self) -> int:
        return self.max_col - self.min_col + 1

    @property
    def range_ref(self) -> str:
        start = f"{get_column_letter(self.min_col)}{self.min_row}"
        end = f"{get_column_letter(self.max_col)}{self.max_row}"
        return start if start == end else f"{start}:{end}"


class XlsxParser(DocumentParser):
    """将 XLSX 工作簿解析为统一的 ParsedElement 和 Asset。"""

    SUPPORTED_TYPES = {"xlsx"}
    VIDEO_URL_RE = re.compile(
        r"https?://[^\s\])<\"']*(?:youtube\.com|youtu\.be|vimeo\.com|\.mp4|\.webm|\.mov|\.m4v)[^\s\])<\"']*",
        re.IGNORECASE,
    )
    HTTP_URL_RE = re.compile(r"https?://[^\s\])<\"']+", re.IGNORECASE)

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in self.SUPPORTED_TYPES

    def parse(self, doc: Document) -> ParseResult:
        raw = self._read_content(doc)
        if not raw:
            raise ValueError("XLSX 解析失败：文档内容为空")

        try:
            value_wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=False)
            formula_wb = load_workbook(io.BytesIO(raw), data_only=False, read_only=False)
        except (InvalidFileException, OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
            raise ValueError(f"XLSX 解析失败：{exc}") from exc

        state = _XlsxParseState(doc.doc_id, doc.version)
        assets: list[Asset] = []
        assets_by_uri: dict[str, Asset] = {}

        for sheet_index, value_ws in enumerate(value_wb.worksheets, start=1):
            if value_ws.sheet_state != "visible":
                continue

            formula_ws = formula_wb[value_ws.title]
            state.add_sheet_title(value_ws.title, sheet_index)
            cells = self._collect_cells(
                value_ws,
                formula_ws,
                doc,
                sheet_index,
                assets,
                assets_by_uri,
            )
            for region in self._find_regions(cells):
                if region.row_count >= 2 and region.col_count >= 2:
                    state.add_table(value_ws.title, sheet_index, region, cells, assets_by_uri)
                else:
                    state.add_paragraphs(value_ws.title, sheet_index, region, cells, assets_by_uri)

        doc.source_hash = compute_hash(raw)
        return ParseResult(doc=doc, elements=state.elements, assets=assets)

    def _read_content(self, doc: Document) -> bytes:
        raw = doc.metadata.get("raw_content", b"")
        if raw:
            return raw.encode("utf-8") if isinstance(raw, str) else raw

        if doc.source_uri.startswith("file://"):
            filepath = resolve_file_uri(doc.source_uri)
            if filepath.exists():
                return filepath.read_bytes()

        return b""

    def _collect_cells(
        self,
        value_ws,
        formula_ws,
        doc: Document,
        sheet_index: int,
        assets: list[Asset],
        assets_by_uri: dict[str, Asset],
    ) -> dict[tuple[int, int], _CellInfo]:
        merged_map = self._build_merged_map(formula_ws)
        cells: dict[tuple[int, int], _CellInfo] = {}

        for row in range(1, value_ws.max_row + 1):
            for col in range(1, value_ws.max_column + 1):
                source_row, source_col = merged_map.get((row, col), (row, col))
                value_cell = value_ws.cell(source_row, source_col)
                formula_cell = formula_ws.cell(source_row, source_col)
                display_cell = formula_ws.cell(row, col)
                coordinate = display_cell.coordinate

                formula = self._formula_text(formula_cell.value)
                value_text = self._stringify(value_cell.value)
                hyperlink = self._hyperlink_target(display_cell) or self._hyperlink_target(formula_cell)
                text = value_text
                metadata: dict[str, Any] = {
                    "cell": coordinate,
                    "sheet_name": formula_ws.title,
                    "sheet_index": sheet_index,
                }

                if formula:
                    metadata["formula"] = formula
                    metadata["formula_value_missing"] = not bool(value_text)
                    if not text:
                        text = formula
                if (row, col) in merged_map and (row, col) != (source_row, source_col):
                    metadata["merged_from"] = formula_cell.coordinate
                if hyperlink:
                    metadata["hyperlink"] = hyperlink
                    if not text and hyperlink.startswith(("http://", "https://")):
                        text = hyperlink

                asset_ids = self._assets_from_cell(
                    doc,
                    formula_ws.title,
                    coordinate,
                    text,
                    hyperlink,
                    assets,
                    assets_by_uri,
                )
                if not text and not asset_ids and not formula and not hyperlink:
                    continue

                metadata["text"] = text
                cells[(row, col)] = _CellInfo(
                    row=row,
                    col=col,
                    coordinate=coordinate,
                    text=text,
                    asset_ids=asset_ids,
                    metadata=metadata,
                )

        return cells

    @staticmethod
    def _build_merged_map(ws) -> dict[tuple[int, int], tuple[int, int]]:
        merged_map: dict[tuple[int, int], tuple[int, int]] = {}
        for merged_range in ws.merged_cells.ranges:
            min_col, min_row, max_col, max_row = range_boundaries(str(merged_range))
            for row in range(min_row, max_row + 1):
                for col in range(min_col, max_col + 1):
                    merged_map[(row, col)] = (min_row, min_col)
        return merged_map

    @staticmethod
    def _formula_text(value: Any) -> str | None:
        if isinstance(value, str) and value.startswith("="):
            return value
        return None

    @staticmethod
    def _hyperlink_target(cell) -> str | None:
        if cell.hyperlink is None:
            return None
        return cell.hyperlink.target or cell.hyperlink.location

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        if isinstance(value, date):
            return value.isoformat()
        return str(value).strip()

    def _assets_from_cell(
        self,
        doc: Document,
        sheet_name: str,
        coordinate: str,
        text: str,
        hyperlink: str | None,
        assets: list[Asset],
        assets_by_uri: dict[str, Asset],
    ) -> list[str]:
        urls: list[str] = []
        if text:
            urls.extend(match.group(0) for match in self.HTTP_URL_RE.finditer(text))
        if hyperlink and hyperlink.startswith(("http://", "https://")):
            urls.append(hyperlink)

        asset_ids: list[str] = []
        for url in dict.fromkeys(urls):
            asset = assets_by_uri.get(url)
            if asset is None:
                asset_type = AssetType.video if self._is_video_url(url) else AssetType.attachment
                asset = Asset(
                    doc_id=doc.doc_id,
                    asset_type=asset_type,
                    original_uri=url,
                    storage_uri=None,
                    mime_type=self._guess_mime(url, asset_type),
                    status=AssetStatus.ready,
                    extracted_text=None,
                    metadata={
                        "source": "xlsx_cell",
                        "sheet_name": sheet_name,
                        "cell": coordinate,
                    },
                )
                assets.append(asset)
                assets_by_uri[url] = asset
            asset_ids.append(asset.asset_id)
        return asset_ids

    def _is_video_url(self, url: str) -> bool:
        return bool(self.VIDEO_URL_RE.search(url))

    @staticmethod
    def _guess_mime(url: str, asset_type: AssetType) -> str:
        ext = url.lower().split("?", 1)[0].rsplit(".", 1)[-1]
        mime_map = {
            "mp4": "video/mp4",
            "webm": "video/webm",
            "mov": "video/quicktime",
            "m4v": "video/mp4",
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        if ext in mime_map:
            return mime_map[ext]
        return "video/*" if asset_type == AssetType.video else "application/octet-stream"

    @staticmethod
    def _find_regions(cells: dict[tuple[int, int], _CellInfo]) -> list[_Region]:
        if not cells:
            return []

        row_groups = _group_contiguous(sorted({row for row, _ in cells}))
        col_groups = _group_contiguous(sorted({col for _, col in cells}))
        regions: list[_Region] = []

        for row_start, row_end in row_groups:
            for col_start, col_end in col_groups:
                has_cells = any(
                    row_start <= row <= row_end and col_start <= col <= col_end
                    for row, col in cells
                )
                if has_cells:
                    regions.append(_Region(row_start, row_end, col_start, col_end))

        return sorted(regions, key=lambda region: (region.min_row, region.min_col))


class _XlsxParseState:
    """维护 XLSX 解析过程中生成元素的顺序和标题路径。"""

    def __init__(self, doc_id: str, doc_version: int):
        self.doc_id = doc_id
        self.doc_version = doc_version
        self.elements: list[ParsedElement] = []
        self._seq = 0
        self._section_path: list[str] = []

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def add_sheet_title(self, sheet_name: str, sheet_index: int) -> None:
        self._section_path = [sheet_name]
        self.elements.append(
            ParsedElement(
                doc_id=self.doc_id,
                doc_version=self.doc_version,
                sequence_order=self._next_seq(),
                element_type=ElementType.title,
                text=sheet_name,
                source_location=SourceLocation(section_path=list(self._section_path)),
                metadata={"heading_level": 1, "sheet_name": sheet_name, "sheet_index": sheet_index},
            )
        )

    def add_table(
        self,
        sheet_name: str,
        sheet_index: int,
        region: _Region,
        cells: dict[tuple[int, int], _CellInfo],
        assets_by_uri: dict[str, Asset],
    ) -> None:
        headers = [
            self._cell(cells, region.min_row, col).text
            for col in range(region.min_col, region.max_col + 1)
        ]
        header_cells = []
        rows = []
        asset_ids: list[str] = []
        for col in range(region.min_col, region.max_col + 1):
            cell = self._cell(cells, region.min_row, col)
            asset_ids.extend(cell.asset_ids)
            header_cells.append(
                {
                    "text": cell.text,
                    "asset_ids": list(cell.asset_ids),
                    "metadata": cell.metadata,
                }
            )
        for row in range(region.min_row + 1, region.max_row + 1):
            row_cells = []
            for col in range(region.min_col, region.max_col + 1):
                cell = self._cell(cells, row, col)
                asset_ids.extend(cell.asset_ids)
                row_cells.append(
                    {
                        "text": cell.text,
                        "asset_ids": list(cell.asset_ids),
                        "metadata": cell.metadata,
                    }
                )
            rows.append({"cells": row_cells})

        structured = {
            "table": {
                "caption": "",
                "headers": headers,
                "header_cells": header_cells,
                "rows": rows,
                "metadata": {
                    "sheet_name": sheet_name,
                    "sheet_index": sheet_index,
                    "range": region.range_ref,
                },
            }
        }
        text = self._table_text(headers, rows)
        unique_asset_ids = list(dict.fromkeys(asset_ids))
        element = ParsedElement(
            doc_id=self.doc_id,
            doc_version=self.doc_version,
            sequence_order=self._next_seq(),
            element_type=ElementType.table,
            text=text,
            structured_data=structured,
            asset_ids=unique_asset_ids,
            source_location=SourceLocation(
                section_path=list(self._section_path),
                table_path=[
                    {
                        "sheet_name": sheet_name,
                        "sheet_index": sheet_index,
                        "range": region.range_ref,
                    }
                ],
            ),
            metadata={
                "sheet_name": sheet_name,
                "sheet_index": sheet_index,
                "range": region.range_ref,
            },
        )
        self._link_assets(element, assets_by_uri)
        self.elements.append(element)

    def add_paragraphs(
        self,
        sheet_name: str,
        sheet_index: int,
        region: _Region,
        cells: dict[tuple[int, int], _CellInfo],
        assets_by_uri: dict[str, Asset],
    ) -> None:
        for row in range(region.min_row, region.max_row + 1):
            for col in range(region.min_col, region.max_col + 1):
                cell = cells.get((row, col))
                if cell is None:
                    continue
                element = ParsedElement(
                    doc_id=self.doc_id,
                    doc_version=self.doc_version,
                    sequence_order=self._next_seq(),
                    element_type=ElementType.paragraph,
                    text=cell.text,
                    asset_ids=list(cell.asset_ids),
                    source_location=SourceLocation(
                        section_path=list(self._section_path),
                        table_path=[
                            {
                                "sheet_name": sheet_name,
                                "sheet_index": sheet_index,
                                "cell": cell.coordinate,
                            }
                        ],
                    ),
                    metadata={
                        **cell.metadata,
                        "sheet_name": sheet_name,
                        "sheet_index": sheet_index,
                    },
                )
                self._link_assets(element, assets_by_uri)
                self.elements.append(element)

    @staticmethod
    def _cell(cells: dict[tuple[int, int], _CellInfo], row: int, col: int) -> _CellInfo:
        coordinate = f"{get_column_letter(col)}{row}"
        return cells.get((row, col)) or _CellInfo(row=row, col=col, coordinate=coordinate)

    @staticmethod
    def _table_text(headers: list[str], rows: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        if headers:
            parts.append(" | ".join(headers))
        for row in rows:
            parts.append(" | ".join(cell["text"] for cell in row["cells"]))
        return "\n".join(part for part in parts if part.strip())

    @staticmethod
    def _link_assets(element: ParsedElement, assets_by_uri: dict[str, Asset]) -> None:
        linked = set(element.asset_ids)
        for asset in assets_by_uri.values():
            if asset.asset_id in linked and not asset.source_element_id:
                asset.source_element_id = element.element_id


def _group_contiguous(values: list[int]) -> list[tuple[int, int]]:
    if not values:
        return []

    groups: list[tuple[int, int]] = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        groups.append((start, previous))
        start = previous = value
    groups.append((start, previous))
    return groups
