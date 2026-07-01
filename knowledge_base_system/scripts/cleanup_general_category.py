"""清理 category 为 "general" 和 "通用" 的文档及其所有关联数据。

删除范围：
  - Milvus: 关联知识块的向量和标量数据
  - PostgreSQL:
    - knowledge_chunks 表（关联的知识块）
    - parsed_elements 表（解析元素）
    - assets 表（资源文件元数据）
    - ingest_jobs 表（入库任务记录）
    - documents 表（文档主记录）

用法：
  cd knowledge_base_system
  python scripts/cleanup_general_category.py          # 预览模式
  python scripts/cleanup_general_category.py --yes    # 确认执行
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# 确保 knowledge_base_system 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.core.config import settings
from app.db.engine import create_session_factory
from app.db.models import (
    DbAsset,
    DbDocument,
    DbKnowledgeChunk,
    DbParsedElement,
)
from app.db.job_models import DbIngestJob
from app.db.repositories.documents import DocumentRepository
from app.db.repositories.chunks import PgChunkStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("cleanup_general")


TARGET_CATEGORIES = ("general", "通用")


def preview() -> dict[str, int]:
    """预览将要删除的数据量，不执行任何写操作。"""
    session_factory = create_session_factory()

    with session_factory() as session:
        # 1. 匹配的文档
        docs = (
            session.query(DbDocument)
            .filter(DbDocument.category.in_(TARGET_CATEGORIES))
            .all()
        )
        doc_ids = [d.doc_id for d in docs]

        if not doc_ids:
            logger.info("没有找到 category 为 %s 的文档", TARGET_CATEGORIES)
            return {}

        logger.info("找到 %d 个匹配文档:", len(docs))
        for d in docs:
            logger.info(
                "  doc_id=%s  title=%s  category=%s  status=%s",
                d.doc_id, d.title, d.category, d.status,
            )

        # 2. 关联的知识块
        chunk_count = (
            session.query(DbKnowledgeChunk)
            .filter(DbKnowledgeChunk.doc_id.in_(doc_ids))
            .count()
        )

        # 3. 关联的解析元素
        element_count = (
            session.query(DbParsedElement)
            .filter(DbParsedElement.doc_id.in_(doc_ids))
            .count()
        )

        # 4. 关联的资源
        asset_count = (
            session.query(DbAsset)
            .filter(DbAsset.doc_id.in_(doc_ids))
            .count()
        )

        # 5. 关联的入库任务
        job_count = (
            session.query(DbIngestJob)
            .filter(DbIngestJob.doc_id.in_(doc_ids))
            .count()
        )

    stats = {
        "documents": len(doc_ids),
        "knowledge_chunks": chunk_count,
        "parsed_elements": element_count,
        "assets": asset_count,
        "ingest_jobs": job_count,
    }
    logger.info("即将删除的数据统计:")
    logger.info("  documents:         %d", stats["documents"])
    logger.info("  knowledge_chunks:  %d", stats["knowledge_chunks"])
    logger.info("  parsed_elements:   %d", stats["parsed_elements"])
    logger.info("  assets:            %d", stats["assets"])
    logger.info("  ingest_jobs:       %d", stats["ingest_jobs"])

    return stats


def execute_cleanup() -> None:
    """执行清理：Milvus → PG 关联表 → 文档主表（按依赖顺序硬删除）。"""
    session_factory = create_session_factory()

    # ── [0] 收集目标文档 ID ──
    with session_factory() as session:
        docs = (
            session.query(DbDocument)
            .filter(DbDocument.category.in_(TARGET_CATEGORIES))
            .all()
        )
        doc_ids = [d.doc_id for d in docs]

    if not doc_ids:
        logger.info("没有找到匹配文档，退出。")
        return

    # ── [1] Milvus: 批量删除关联知识块的向量 ──
    try:
        from indexing.milvus_vector import MilvusCollectionManager

        milvus_manager = MilvusCollectionManager()
        milvus_manager.ensure_collection()

        # 先收集所有待删除的 chunk_id
        all_chunk_ids: list[str] = []
        with session_factory() as session:
            chunks = (
                session.query(DbKnowledgeChunk.chunk_id)
                .filter(DbKnowledgeChunk.doc_id.in_(doc_ids))
                .all()
            )
            all_chunk_ids = [c.chunk_id for c in chunks]

        if all_chunk_ids:
            logger.info("从 Milvus 删除 %d 个知识块...", len(all_chunk_ids))
            milvus_manager.delete_batch(all_chunk_ids)
            logger.info("Milvus 清理完成。")
        else:
            logger.info("Milvus 中无关联知识块，跳过。")
    except Exception as exc:
        logger.error("Milvus 清理失败: %s", exc)
        logger.warning("将继续清理 PostgreSQL 数据...")

    # ── [2] PG: 按外键依赖顺序硬删除 ──
    with session_factory() as session:
        # 2a. knowledge_chunks
        deleted = (
            session.query(DbKnowledgeChunk)
            .filter(DbKnowledgeChunk.doc_id.in_(doc_ids))
            .delete(synchronize_session=False)
        )
        logger.info("knowledge_chunks: 删除了 %d 条", deleted)

        # 2b. parsed_elements
        deleted = (
            session.query(DbParsedElement)
            .filter(DbParsedElement.doc_id.in_(doc_ids))
            .delete(synchronize_session=False)
        )
        logger.info("parsed_elements:  删除了 %d 条", deleted)

        # 2c. assets
        deleted = (
            session.query(DbAsset)
            .filter(DbAsset.doc_id.in_(doc_ids))
            .delete(synchronize_session=False)
        )
        logger.info("assets:           删除了 %d 条", deleted)

        # 2d. ingest_jobs
        deleted = (
            session.query(DbIngestJob)
            .filter(DbIngestJob.doc_id.in_(doc_ids))
            .delete(synchronize_session=False)
        )
        logger.info("ingest_jobs:      删除了 %d 条", deleted)

        # 2e. documents（最后删除主表记录）
        deleted = (
            session.query(DbDocument)
            .filter(DbDocument.doc_id.in_(doc_ids))
            .delete(synchronize_session=False)
        )
        session.commit()
        logger.info("documents:        删除了 %d 条", deleted)

    logger.info("全部清理完成！共处理 %d 个文档。", len(doc_ids))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="清理 category 为 general/通用 的文档及全部关联数据"
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="确认执行删除（不加此参数仅预览）",
    )
    args = parser.parse_args()

    # 打印连接信息
    logger.info("数据库: %s", settings.database_url)
    logger.info("Milvus: %s:%s / %s", settings.milvus_host, settings.milvus_port, settings.milvus_collection)

    if args.yes:
        logger.info("=" * 60)
        logger.info("⚠️  确认执行模式：将物理删除所有匹配数据！")
        logger.info("=" * 60)
        preview()
        logger.info("开始执行清理...")
        execute_cleanup()
    else:
        logger.info("=" * 60)
        logger.info("预览模式：仅展示将要删除的数据，不执行任何写操作。")
        logger.info("添加 --yes 参数确认执行。")
        logger.info("=" * 60)
        preview()


if __name__ == "__main__":
    main()
