"""PDF 解析器 — 基于 MinerU API + PyMuPDF 混合方案。

MinerU（精准解析 API）负责文档的布局分析、阅读顺序恢复、表格/公式识别和文本提取。
PyMuPDF 补充 MinerU 无法处理的超链接和嵌入图片二进制数据。
两者通过 bbox 坐标匹配精确关联。

未配置 MINERU_API_TOKEN 或 API 调用失败时自动降级到 PdfParser。
"""

import hashlib
import json
import logging
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import fitz
import requests

from app.core.config import get_settings
from app.core.models import (
    Asset,
    AssetData,
    AssetType,
    Document,
    compute_hash,
)
from parsers.base import DocumentParser, ParseResult
from parsers.markdown_parser import MarkdownParser

logger = logging.getLogger(__name__)


class PdfByMinerUParser(DocumentParser):
    """基于 MinerU API 的 PDF 解析器。

    使用 MinerU 精准解析 API 获取文档的结构化内容（含 bbox 坐标），
    通过 PyMuPDF 补充链接 URL 和嵌入图片二进制，坐标匹配精确关联。
    最终委托 MarkdownParser 产出统一的 elements + assets。
    """

    SUPPORTED_TYPES = {"pdf"}

    # MinerU API 端点
    _BATCH_URL = "/api/v4/file-urls/batch"        # 申请上传 + 自动创建解析任务
    _BATCH_RESULT_URL = "/api/v4/extract-results/batch"  # 查询批量任务结果
    _TASK_POLL_INTERVAL = 3       # 轮询间隔（秒）
    _TASK_MAX_WAIT = 300          # 最长等待（秒）
    _BBOX_NORM = 1000.0           # MinerU bbox 归一化范围

    def __init__(self) -> None:
        cfg = get_settings()
        self._token: str = getattr(cfg, "mineru_api_token", "") or ""
        self._api_base: str = getattr(cfg, "mineru_api_base", "") or "https://mineru.net"
        self._use_vlm: bool = getattr(cfg, "mineru_use_vlm", False)
        self._fallback: DocumentParser | None = None  # 延迟加载

    def _get_fallback(self) -> DocumentParser:
        """延迟加载 PdfParser 作为降级方案。"""
        if self._fallback is None:
            from parsers.pdf_parser import PdfParser
            self._fallback = PdfParser()
        return self._fallback

    def supports(self, source_type: str) -> bool:
        return source_type.lower() == "pdf"

    # ── 主解析入口 ──────────────────────────────────────────────────

    def parse(self, doc: Document, content: bytes | str) -> ParseResult:
        """使用 MinerU API 解析 PDF，PyMuPDF 补充链接和图片。"""
        if isinstance(content, str):
            content = content.encode("utf-8")

        if not self._token:
            logger.warning("未配置 MINERU_API_TOKEN，降级到 PdfParser")
            return self._get_fallback().parse(doc, content)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pdf_path = tmp / "input.pdf"
            pdf_path.write_bytes(content)

            try:
                # 1. MinerU API
                mineru_md, mineru_blocks = self._run_mineru(pdf_path)
            except Exception as exc:
                logger.warning("MinerU API 失败 (%s)，降级到 PdfParser", exc)
                return self._get_fallback().parse(doc, content)

            # 2. PyMuPDF 提取链接 + bbox 匹配 + 注入 Markdown
            pdf = fitz.open(pdf_path)
            try:
                md_with_links = self._inject_links(pdf, mineru_md, mineru_blocks)
            finally:
                pdf.close()

            # 3. MarkdownParser 解析
            md_parser = MarkdownParser()
            result = md_parser.parse(doc, md_with_links)

            # 4. PyMuPDF 提取嵌入图片 + bbox 匹配 + 替换 Asset
            pdf2 = fitz.open(pdf_path)
            try:
                self._fix_image_assets(result, pdf2, mineru_blocks)
            finally:
                pdf2.close()

            # 5. 回填 element_id + 设置 source_hash
            self._backfill_element_ids(result)
            doc.source_hash = compute_hash(content)

            return result

    # ── MinerU API ───────────────────────────────────────────────────

    def _run_mineru(self, pdf_path: Path) -> tuple[str, list[dict[str, Any]]]:
        """提交 PDF 到 MinerU（上传后自动解析），轮询完成，返回 (md_text, blocks)。"""
        batch_id, upload_url = self._apply_upload(pdf_path)
        self._put_file(upload_url, pdf_path)
        zip_path = self._wait_batch_and_download(batch_id, pdf_path.parent)
        return self._parse_mineru_output(zip_path)

    def _apply_upload(self, pdf_path: Path) -> tuple[str, str]:
        """申请上传 URL + 创建批量解析任务，返回 (batch_id, upload_url)。"""
        url = f"{self._api_base}{self._BATCH_URL}"
        body: dict[str, Any] = {
            "files": [{"name": pdf_path.name}],
            "language": "ch",
            "enable_formula": True,
            "enable_table": True,
        }
        if self._use_vlm:
            body["model_version"] = "vlm"

        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"MinerU 上传申请失败: {data.get('msg', resp.text)}")
        batch_id = data["data"]["batch_id"]
        file_urls = data["data"].get("file_urls", [])
        if not file_urls:
            raise RuntimeError("MinerU 上传申请返回空 URL")
        logger.info("MinerU batch_id=%s", batch_id)
        return batch_id, file_urls[0]

    @staticmethod
    def _put_file(upload_url: str, pdf_path: Path) -> None:
        """PUT 文件到 OSS 预签名 URL，上传后系统自动提交解析任务。"""
        with open(pdf_path, "rb") as f:
            resp = requests.put(upload_url, data=f, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f"MinerU 文件上传失败: HTTP {resp.status_code}")
        logger.info("MinerU 文件上传成功，系统自动开始解析")

    def _wait_batch_and_download(self, batch_id: str, out_dir: Path) -> Path:
        """轮询批量任务结果，完成后下载第一个文件的 ZIP。"""
        url = f"{self._api_base}{self._BATCH_RESULT_URL}/{batch_id}"
        start = time.monotonic()

        while True:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=30,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"MinerU 查询失败: {data.get('msg', resp.text)}")

            results = data.get("data", {}).get("extract_result", [])
            if not results:
                raise RuntimeError("MinerU 批量结果为空")

            file_result = results[0]
            state = file_result.get("state", "")

            if state == "done":
                zip_url = file_result.get("full_zip_url", "")
                if not zip_url:
                    raise RuntimeError("MinerU 完成但缺少 full_zip_url")
                return self._download_zip(zip_url, out_dir)

            if state == "failed":
                err = file_result.get("err_msg", "unknown")
                raise RuntimeError(f"MinerU 解析失败: {err}")

            if time.monotonic() - start > self._TASK_MAX_WAIT:
                raise TimeoutError(f"MinerU 任务超时 ({self._TASK_MAX_WAIT}s)")

            logger.debug("MinerU 处理中: state=%s", state)
            time.sleep(self._TASK_POLL_INTERVAL)

    @staticmethod
    def _download_zip(zip_url: str, out_dir: Path) -> Path:
        """下载结果 ZIP 并解压，返回解压目录。"""
        resp = requests.get(zip_url, timeout=120)
        resp.raise_for_status()

        zip_path = out_dir / "mineru_output.zip"
        zip_path.write_bytes(resp.content)

        extract_dir = out_dir / "mineru_output"
        extract_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        logger.info("MinerU 结果已解压到 %s", extract_dir)
        return extract_dir

    @staticmethod
    def _parse_mineru_output(extract_dir: Path) -> tuple[str, list[dict[str, Any]]]:
        """从 MinerU 输出目录读取 full.md 和 content_list.json。"""
        # 查找 full.md
        md_files = list(extract_dir.glob("**/full.md"))
        if not md_files:
            raise RuntimeError("MinerU 输出中找不到 full.md")
        md_text = md_files[0].read_text(encoding="utf-8")

        # 查找 content_list.json
        cl_files = list(extract_dir.glob("**/*_content_list.json"))
        if not cl_files:
            cl_files = list(extract_dir.glob("**/content_list.json"))
        blocks: list[dict[str, Any]] = []
        if cl_files:
            blocks = json.loads(cl_files[0].read_text(encoding="utf-8"))
            if not isinstance(blocks, list):
                blocks = []

        return md_text, blocks

    # ── 链接：PyMuPDF 提取 + bbox 匹配 + 注入 Markdown ─────────────

    def _inject_links(
        self,
        pdf: fitz.Document,
        md_text: str,
        mineru_blocks: list[dict[str, Any]],
    ) -> str:
        """提取 PDF 超链接，通过 bbox 匹配关联到 MinerU 文本块，注入 [锚文字](URI)。"""
        # 所有可读内容块（含 header/footer/aside_text/page_footnote）都参与链接匹配
        readable_blocks: list[dict[str, Any]] = [
            b for b in mineru_blocks
            if b.get("type") in ("text", "page_number", "header", "footer",
                                 "aside_text", "page_footnote")
            and (b.get("text", "").strip() or b.get("img_path", ""))
        ]

        # 按页分组
        blocks_by_page: dict[int, list[dict[str, Any]]] = {}
        for b in readable_blocks:
            page_idx = b.get("page_idx", 0)
            blocks_by_page.setdefault(page_idx, []).append(b)

        links_injected = 0
        for page_num in range(pdf.page_count):
            page = pdf[page_num]
            pw, ph = page.rect.width, page.rect.height
            page_blocks = blocks_by_page.get(page_num, [])

            for link in page.get_links():
                uri = link.get("uri", "")
                if not uri or not uri.startswith(("http://", "https://")):
                    continue

                link_rect = link.get("from")
                if link_rect is None:
                    continue

                # link rect → 0-1000
                lr = fitz.Rect(link_rect)
                link_bbox = self._pdf_to_mineru(lr, pw, ph)

                # 找 bbox 交集最大的 text 块作为锚文字来源
                best = self._best_match(link_bbox, page_blocks)
                if best is None:
                    continue

                # 用 link rect 精确取锚文字，回退到 text 块全文
                anchor = page.get_textbox(lr).strip()
                if not anchor:
                    anchor = best.get("text", "").strip()
                if not anchor:
                    continue

                # 避免在已是 Markdown 链接语法的文字上重复注入
                if f"[{anchor}]" in md_text:
                    continue

                # 替换锚文字为 MD 链接；若锚文字不在 full.md 中（如被 MinerU 过滤的 header），追到文末
                if anchor in md_text:
                    md_text = md_text.replace(anchor, f"[{anchor}]({uri})", 1)
                else:
                    md_text += f"\n[{anchor}]({uri})"
                links_injected += 1

        logger.info("MinerU 链接注入: %d 个", links_injected)
        return md_text

    @staticmethod
    def _pdf_to_mineru(rect: fitz.Rect, page_width: float, page_height: float) -> list[float]:
        """PDF 坐标 → MinerU 0-1000 归一化坐标。"""
        s = PdfByMinerUParser._BBOX_NORM
        return [
            rect.x0 / page_width * s,
            rect.y0 / page_height * s,
            rect.x1 / page_width * s,
            rect.y1 / page_height * s,
        ]

    @staticmethod
    def _best_match(
        target_bbox: list[float],
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """在 blocks 中按 bbox 交集面积找最佳匹配。"""
        best, best_area = None, 0.0
        tr = fitz.Rect(target_bbox)
        for b in blocks:
            br = fitz.Rect(b.get("bbox", [0, 0, 0, 0]))
            if tr.intersects(br):
                area = (tr & br).get_area()
                if area > best_area:
                    best_area = area
                    best = b
        return best

    # ── 图片：PyMuPDF 提取 + bbox 匹配 + 替换 MarkdownParser 产出的 Asset ──

    def _fix_image_assets(
        self,
        result: ParseResult,
        pdf: fitz.Document,
        mineru_blocks: list[dict[str, Any]],
    ) -> None:
        """用 PyMuPDF 嵌入图片替换 MinerU image 块对应的 MarkdownParser Asset。

        MinerU OCR 模式下嵌入图片已被转为文本，不重复提取。
        仅当 MinerU 明确标记 image 块时才用 PyMuPDF 替换为嵌入二进制。
        """
        image_blocks = [b for b in mineru_blocks if b.get("type") == "image"]
        if not image_blocks:
            return

        # 收集 PyMuPDF 图片信息
        pymupdf_images: list[dict[str, Any]] = []
        for page_num in range(pdf.page_count):
            page = pdf[page_num]
            try:
                for info in page.get_image_info():
                    pymupdf_images.append({
                        "xref": info.get("number"),
                        "bbox": info.get("bbox"),
                        "page": page_num,
                    })
            except Exception:
                continue

        fixed = 0
        for img_block in image_blocks:
            page_idx = img_block.get("page_idx", 0)
            mineru_bbox = img_block.get("bbox", [0, 0, 0, 0])
            page = pdf[page_idx]
            pw, ph = page.rect.width, page.rect.height
            pdf_bbox = self._mineru_to_pdf(mineru_bbox, pw, ph)

            for pm_img in pymupdf_images:
                if pm_img["page"] != page_idx or pm_img["bbox"] is None:
                    continue
                if not fitz.Rect(pdf_bbox).intersects(fitz.Rect(pm_img["bbox"])):
                    continue

                try:
                    base_image = pdf.extract_image(pm_img["xref"])
                    image_bytes = base_image.get("image")
                except Exception:
                    continue
                if not image_bytes:
                    continue

                img_path = img_block.get("img_path", "")
                target_asset = self._find_asset_by_path(result, img_path)
                if target_asset is not None:
                    content_hash = f"sha256:{hashlib.sha256(image_bytes).hexdigest()}"
                    object.__setattr__(target_asset, "_data", image_bytes)
                    target_asset.content_hash = content_hash
                    target_asset.asset_type = AssetType.image
                    target_asset.original_uri = ""
                    target_asset.metadata["source"] = "pdf_image"
                    target_asset.metadata["width"] = base_image.get("width")
                    target_asset.metadata["height"] = base_image.get("height")
                    fixed += 1
                break

        logger.info("MinerU 图片修复: %d/%d 个", fixed, len(image_blocks))

    @staticmethod
    def _mineru_to_pdf(
        mineru_bbox: list[float],
        page_width: float,
        page_height: float,
    ) -> list[float]:
        """MinerU 0-1000 坐标 → PDF 坐标。"""
        s = PdfByMinerUParser._BBOX_NORM
        return [
            mineru_bbox[0] / s * page_width,
            mineru_bbox[1] / s * page_height,
            mineru_bbox[2] / s * page_width,
            mineru_bbox[3] / s * page_height,
        ]

    @staticmethod
    def _find_asset_by_path(result: ParseResult, img_path: str) -> Asset | None:
        """在 ParseResult 中查找 original_uri 尾缀匹配 img_path 的 Asset。"""
        if not img_path:
            return None
        for asset in result.assets:
            if asset.original_uri and asset.original_uri.endswith(img_path):
                return asset
            # 也可能只存了文件名
            if asset.original_uri and Path(img_path).name in asset.original_uri:
                return asset
        return None

    # ── element_id 回填 ─────────────────────────────────────────────

    @staticmethod
    def _backfill_element_ids(result: ParseResult) -> None:
        """通过 element.asset_data 回填 Asset.element_id。"""
        for el in result.elements:
            for ad in el.asset_data:
                for asset in result.assets:
                    if asset.asset_id == ad.asset_id and not asset.element_id:
                        asset.element_id = el.element_id
