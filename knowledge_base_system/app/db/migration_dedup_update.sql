-- 文档去重与增量更新 — 数据库迁移
-- 目标：KBS PostgreSQL 数据库
-- 回滚：DROP INDEX IF EXISTS idx_documents_source_hash_active; DROP INDEX IF EXISTS idx_documents_source_uri;

-- 1. source_hash 部分唯一索引（仅对 status='active' 的行生效，作为去重最后防线）
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_source_hash_active
    ON documents (source_hash) WHERE status = 'active';

-- 2. source_uri 普通索引（便于按来源地址查找）
CREATE INDEX IF NOT EXISTS idx_documents_source_uri
    ON documents (source_uri);