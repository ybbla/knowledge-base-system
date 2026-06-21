-- 知识块表清理与字段新增
-- 废弃字段移除：index_status, indexed_at, index_error, ingest_job_id
-- 新增字段：created_at, updated_at（用于排序和界面展示）

-- 为已有行填充默认时间值（使用固定时间戳，避免大量 NULL）
ALTER TABLE knowledge_chunks
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- 使用 chunk_id 中的时间信息无法可靠提取，统一设为当前时间
UPDATE knowledge_chunks
SET created_at = NOW(),
    updated_at = NOW()
WHERE created_at IS NULL;

-- 移除废弃列（PostgreSQL 不支持 IF EXISTS 用于 DROP COLUMN，需手动确认）
-- 若列存在则执行以下语句：
-- ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS index_status;
-- ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS indexed_at;
-- ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS index_error;
-- ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS ingest_job_id;

-- 注意：doc_version 列予以保留，用于后续可能的版本管理需求。
