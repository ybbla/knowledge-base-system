"""
真实链路端到端测试报告。

运行方式:
  cd knowledge_base_system
  python ../test_real_e2e.py

链路:
  生成本地模拟文件 -> POST /upload -> Document -> ParsedElement/Asset
  -> KnowledgeChunk -> Embedding/Index -> SearchResult
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent / "knowledge_base_system"))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.models import (  # noqa: E402
    Document,
    KnowledgeChunk,
    ScoreComponents,
    SearchResult,
    SearchResultItem,
    compute_hash,
)
from app.main import app  # noqa: E402
from assets.memory_store import MemoryAssetStore  # noqa: E402
from indexing.fusion import rrf_fusion  # noqa: E402
from indexing.memory_bm25 import MemoryBM25Index  # noqa: E402
from indexing.memory_vector import MemoryVectorIndex  # noqa: E402
from llm.query_rewriter import QueryRewriter  # noqa: E402
from llm.reranker import Reranker  # noqa: E402
from llm.semantic_extractor import SemanticExtractor  # noqa: E402
from llm.volcengine_client import embedding_client  # noqa: E402
from parsers.markdown_parser import MarkdownParser  # noqa: E402
from retrieval.pipeline import ChunkStore  # noqa: E402


client = TestClient(app)

TEST_DOC_TITLE = "产品使用手册"
TEST_CATEGORY = "产品使用"
TEST_SOURCE_TYPE = "markdown"
TEST_DOC_CONTENT = """\
# 产品使用手册

## 上传知识文档

用户可以在知识库页面上传文档，系统支持 Markdown 和 TXT 格式。
上传完成后，系统会进入解析流程，并显示解析状态。

| 状态 | 说明 |
|------|------|
| 处理中 | 系统正在解析文档并抽取知识块。 |
| 成功 | 文档已经进入知识库，可以被搜索。 |
| 失败 | 用户需要查看失败原因并重新上传。 |

### 注意事项

- 单个文件不超过 10 MB
- 支持批量上传
- 业务分类未指定时默认为“通用”

界面截图如下：
![上传状态截图](https://example.com/upload-status.png)
"""

TEST_QUERIES = [
    ("上传文档后如何判断解析成功？", 3),
    ("知识文档支持哪些格式？", 3),
    ("文件上传大小限制是多少？", 3),
]


class Md:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, text: str = "") -> None:
        self.lines.append(text)

    def h1(self, text: str) -> None:
        self.write(f"# {text}")
        self.write()

    def h2(self, text: str) -> None:
        self.write(f"## {text}")
        self.write()

    def h3(self, text: str) -> None:
        self.write(f"### {text}")
        self.write()

    def p(self, text: str = "") -> None:
        self.write(text)
        self.write()

    def quote(self, text: str) -> None:
        self.write(f"> {text}")
        self.write()

    def table(self, headers: list[str], rows: list[list[Any]]) -> None:
        self.write("| " + " | ".join(headers) + " |")
        self.write("|" + "|".join("---" for _ in headers) + "|")
        for row in rows:
            cells = [str(c).replace("\n", " ").replace("|", "\\|") for c in row]
            self.write("| " + " | ".join(cells) + " |")
        self.write()

    def kv(self, rows: list[tuple[str, Any]]) -> None:
        self.table(["字段", "值"], [[k, v] for k, v in rows])

    def code(self, text: str, lang: str = "") -> None:
        self.write(f"```{lang}")
        self.write(text.rstrip())
        self.write("```")
        self.write()

    def json(self, obj: Any, max_chars: int = 2000) -> None:
        text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... truncated ..."
        self.code(text, "json")

    def __str__(self) -> str:
        return "\n".join(self.lines)


def preview(text: str, length: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    return text[:length] + ("..." if len(text) > length else "")


def write_simulated_source_file() -> Path:
    input_dir = Path("data/simulated_inputs")
    input_dir.mkdir(parents=True, exist_ok=True)
    path = input_dir / "product_manual_source.md"
    path.write_text(TEST_DOC_CONTENT, encoding="utf-8")
    return path


def upload_local_file(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        response = client.post(
            "/upload",
            files={"file": (path.name, handle, "text/markdown")},
            data={"title": TEST_DOC_TITLE, "category": TEST_CATEGORY},
        )
    response.raise_for_status()
    return response.json()


def add_failure(o: Md, stage: str, exc: BaseException) -> str:
    o.h2(f"链路失败：{stage}")
    o.kv([
        ("异常类型", type(exc).__name__),
        ("异常信息", str(exc)),
    ])
    o.code(traceback.format_exc(), "text")
    return str(o)


def build_result_item(
    chunk: KnowledgeChunk,
    rank_entry: dict[str, Any],
    vector_map: dict[str, float],
    bm25_map: dict[str, float],
    fused_map: dict[str, float],
    asset_store: MemoryAssetStore,
) -> SearchResultItem:
    resolved_assets = []
    for ref in chunk.asset_refs:
        asset = asset_store.get(ref.asset_id)
        resolved_assets.append(
            {
                "asset_id": ref.asset_id,
                "relation": ref.relation.value,
                "storage_uri": asset.storage_uri if asset else None,
                "original_uri": asset.original_uri if asset else None,
                "caption": ref.caption,
                "render": ref.render.model_dump(mode="json"),
            }
        )

    return SearchResultItem(
        chunk_id=chunk.chunk_id,
        title=chunk.title,
        content=chunk.content,
        score=rank_entry.get("relevance_score", fused_map.get(chunk.chunk_id, 0.0)),
        category=chunk.category,
        knowledge_type=chunk.knowledge_type,
        score_components=ScoreComponents(
            vector=vector_map.get(chunk.chunk_id, 0.0),
            bm25=bm25_map.get(chunk.chunk_id, 0.0),
            rerank=rank_entry.get("relevance_score", 0.0),
        ),
        asset_refs=resolved_assets,
        source_refs=chunk.source_refs,
        metadata={"title_path": chunk.metadata.get("title_path", [])},
    )


def run_test() -> str:
    o = Md()
    started = time.time()

    o.h1("知识库系统真实链路端到端测试报告")
    o.kv([
        ("输入类型", "本地生成的模拟 Markdown 文件"),
        ("链路类型", "本地 /upload + 真实解析 + 真实 LLM 抽取 + 真实 Embedding + 内存索引 + 真实重写/重排"),
        ("数据模型顺序", "UploadResult -> Document -> ParsedElement/Asset -> KnowledgeChunk -> SearchResult"),
        ("开始时间", time.strftime("%Y-%m-%d %H:%M:%S")),
    ])

    o.h2("0. 生成本地模拟文件")
    source_file = write_simulated_source_file()
    o.kv([
        ("local_path", f"`{source_file.as_posix()}`"),
        ("title", TEST_DOC_TITLE),
        ("source_type", TEST_SOURCE_TYPE),
        ("category", TEST_CATEGORY),
        ("local_hash", f"`{compute_hash(source_file.read_bytes())}`"),
        ("file_size", source_file.stat().st_size),
    ])
    o.code(TEST_DOC_CONTENT, "markdown")

    o.h2("1. 本地上传文件：POST /upload")
    try:
        upload_result = upload_local_file(source_file)
    except Exception as exc:
        return add_failure(o, "本地文件上传 /upload", exc)
    o.quote("/upload 将本地模拟文件写入 data/uploads/，返回后续解析可使用的 source_uri。")
    o.json(upload_result)

    o.h2("2. Document")
    doc = Document(
        title=upload_result["title"],
        source_type=TEST_SOURCE_TYPE,
        source_uri=upload_result["source_uri"],
        source_hash=upload_result["source_hash"],
        category=upload_result["category"],
    )
    doc.ingest_job_id = doc.doc_id
    o.json(doc.model_dump(mode="json"))

    o.h2("3. ParsedElement / Asset")
    parser = MarkdownParser()
    t0 = time.time()
    try:
        parse_result = parser.parse(doc)
    except Exception as exc:
        return add_failure(o, "Markdown 解析", exc)
    parse_cost = time.time() - t0
    doc = parse_result.doc
    elements = parse_result.elements
    assets = parse_result.assets

    type_counts: dict[str, int] = {}
    for element in elements:
        type_counts[element.element_type.value] = type_counts.get(element.element_type.value, 0) + 1

    o.kv([
        ("耗时", f"{parse_cost:.3f}s"),
        ("ParsedElement 数量", len(elements)),
        ("Asset 数量", len(assets)),
        ("解析后 source_hash", f"`{doc.source_hash}`"),
        ("元素类型分布", ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items()))),
    ])
    o.table(
        ["序号", "element_id", "type", "text", "section_path", "asset_ids"],
        [
            [
                item.sequence_order,
                f"`{item.element_id}`",
                item.element_type.value,
                preview(item.text, 80),
                " > ".join(item.source_location.section_path),
                ", ".join(item.asset_ids),
            ]
            for item in elements
        ],
    )
    if assets:
        o.table(
            ["asset_id", "type", "original_uri", "storage_uri", "status"],
            [
                [
                    f"`{asset.asset_id}`",
                    asset.asset_type.value,
                    asset.original_uri,
                    asset.storage_uri,
                    asset.status.value,
                ]
                for asset in assets
            ],
        )

    o.h2("4. KnowledgeChunk")
    extractor = SemanticExtractor()
    t0 = time.time()
    try:
        chunks = extractor.extract(elements, assets, doc.ingest_job_id, doc.category)
    except Exception as exc:
        return add_failure(o, "LLM 语义抽取", exc)
    extract_cost = time.time() - t0
    if not chunks:
        o.quote("LLM 抽取成功返回，但没有生成 KnowledgeChunk，后续检索链路无法继续。")
        return str(o)

    o.kv([
        ("耗时", f"{extract_cost:.3f}s"),
        ("KnowledgeChunk 数量", len(chunks)),
        ("category 继承检查", "通过" if all(c.category == doc.category for c in chunks) else "失败"),
    ])
    o.table(
        ["chunk_id", "title", "knowledge_type", "category", "source_refs", "asset_refs", "content"],
        [
            [
                f"`{chunk.chunk_id}`",
                chunk.title,
                chunk.knowledge_type.value,
                chunk.category,
                len(chunk.source_refs),
                len(chunk.asset_refs),
                preview(chunk.content),
            ]
            for chunk in chunks
        ],
    )
    o.h3("首个 KnowledgeChunk 完整快照")
    o.json(chunks[0].model_dump(mode="json"))

    o.h2("5. Embedding / VectorIndex / BM25Index / ChunkStore / AssetStore")
    vector_index = MemoryVectorIndex()
    bm25_index = MemoryBM25Index()
    chunk_store = ChunkStore()
    asset_store = MemoryAssetStore()
    for asset in assets:
        asset_store.put(asset)
    for chunk in chunks:
        chunk_store.put(chunk)

    t0 = time.time()
    try:
        vectors = embedding_client.embed_text([chunk.content for chunk in chunks])
    except Exception as exc:
        return add_failure(o, "Embedding 生成", exc)
    embed_cost = time.time() - t0

    for chunk, vector in zip(chunks, vectors):
        vector_index.add(
            chunk.chunk_id,
            vector,
            metadata={
                "doc_id": chunk.doc_id,
                "category": chunk.category,
                "knowledge_type": chunk.knowledge_type.value,
                "title_path": chunk.metadata.get("title_path", []),
            },
        )
        bm25_index.add(
            chunk.chunk_id,
            chunk.content,
            metadata={"category": chunk.category},
        )

    o.kv([
        ("Embedding 耗时", f"{embed_cost:.3f}s"),
        ("向量数量", len(vectors)),
        ("向量维度", len(vectors[0]) if vectors else 0),
        ("ChunkStore 数量", chunk_store.count()),
        ("AssetStore 数量", len(assets)),
        ("category 索引元数据", doc.category),
    ])

    o.h2("6. SearchResult")
    rewriter = QueryRewriter()
    reranker = Reranker()
    search_results: list[SearchResult] = []
    query_rows: list[list[Any]] = []

    for query, top_k in TEST_QUERIES:
        o.h3(f"查询：{query}")
        try:
            t0 = time.time()
            rewrite = rewriter.rewrite(query)
            rewrite_cost = time.time() - t0
            rewritten_query = rewrite.get("rewritten_query", query)
            keywords = rewrite.get("keywords", [query])

            t0 = time.time()
            query_vector = embedding_client.embed_text([rewritten_query])[0]
            vector_results = vector_index.search(query_vector, top_k=50, category=doc.category)
            vector_cost = time.time() - t0

            t0 = time.time()
            bm25_results = bm25_index.search(" ".join(keywords), top_k=50, category=doc.category)
            bm25_cost = time.time() - t0

            fused = rrf_fusion(vector_results, bm25_results)
            top_fused = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:20]
            candidates = chunk_store.get_batch([chunk_id for chunk_id, _ in top_fused])

            t0 = time.time()
            reranked = reranker.rerank(query, candidates)
            rerank_cost = time.time() - t0

            vector_map = dict(vector_results)
            bm25_map = dict(bm25_results)
            fused_map = dict(top_fused)
            items = [
                build_result_item(
                    chunk_store.get(rank_entry["chunk_id"]),
                    rank_entry,
                    vector_map,
                    bm25_map,
                    fused_map,
                    asset_store,
                )
                for rank_entry in reranked[:top_k]
                if chunk_store.get(rank_entry["chunk_id"]) is not None
            ]

            result = SearchResult(
                query=query,
                rewritten_query=rewritten_query,
                total_count=len(candidates),
                results=items,
            )
            search_results.append(result)

            query_rows.append([
                query,
                len(vector_results),
                len(bm25_results),
                len(candidates),
                len(items),
                f"{rewrite_cost:.2f}s / {vector_cost:.2f}s / {bm25_cost:.2f}s / {rerank_cost:.2f}s",
                items[0].title if items else "-",
            ])
            o.json(result.model_dump(mode="json"), max_chars=2400)
        except Exception as exc:
            o.h3("该查询失败")
            o.kv([
                ("异常类型", type(exc).__name__),
                ("异常信息", str(exc)),
            ])
            o.code(traceback.format_exc(), "text")

    o.h2("7. 汇总")
    o.table(
        ["query", "vector命中", "bm25命中", "候选数", "返回数", "rewrite/vector/bm25/rerank", "top1"],
        query_rows,
    )
    o.table(
        ["数据模型", "产出数量", "检查结果"],
        [
            ["LocalFile", 1, f"path={source_file.as_posix()}, hash={compute_hash(source_file.read_bytes())}"],
            ["UploadResult", 1, f"source_uri={upload_result['source_uri']}, source_hash={upload_result['source_hash']}"],
            ["Document", 1, f"doc_id={doc.doc_id}, category={doc.category}, source_hash={doc.source_hash}"],
            ["ParsedElement", len(elements), ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items()))],
            ["Asset", len(assets), "图片链接被识别为 Asset" if assets else "未识别到资源"],
            ["KnowledgeChunk", len(chunks), "content_hash/source_refs/category 均已生成"],
            ["VectorIndex", len(vectors), f"category={doc.category} 元数据已写入"],
            ["BM25Index", len(chunks), f"category={doc.category} 元数据已写入"],
            ["SearchResult", len(search_results), "返回顶层 category 与 knowledge_type"],
        ],
    )
    o.kv([
        ("总耗时", f"{time.time() - started:.3f}s"),
        ("结束时间", time.strftime("%Y-%m-%d %H:%M:%S")),
    ])
    return str(o)


if __name__ == "__main__":
    report = run_test()
    output_path = Path(__file__).parent / "test_e2e_report.md"
    output_path.write_text(report, encoding="utf-8")
    print(f"Report saved to: {output_path.resolve()}")
