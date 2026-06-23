## 已完成的改动

- [x] AssetRelation 删除 `source`/`attachment`；prompt relation 从 5 减为 3
- [x] `_elements_to_json` 注入 `heading_level`，`source_location` → `section_path`
- [x] 测试对齐（test_models.py、test_db_models.py）

---

## 1. 模型层改动

- [x] 1.1 删除 `AssetRelation` 枚举（`models.py`）
- [x] 1.2 `AssetRef` 移除 `relation` 字段
- [x] 1.3 清理所有代码中 `AssetRelation` 引用：`semantic_extractor.py`（`_build_chunks` 中整段 `relation_value` 解析逻辑删除）、`pipeline.py`、prompt 输出格式中的 `relation` 字段
- [x] 1.4 清理 `AssetRelation` import 和测试对齐

## 2. 清理幽灵参数

- [x] 2.1 `extract()` 签名：移除 `ingest_job_id` → `(self, elements, assets, category)`
- [x] 2.2 `_process_window()` → `_extract_section(self, elements, assets, category)`
- [x] 2.3 `_build_chunks()`：移除 `ingest_job_id` 参数；移除 `KnowledgeChunk()` 中的 `ingest_job_id` 和 `doc_version`；`source_refs` 空兜底改为 `[]`
- [x] 2.4 `_fallback_chunks()`：移除 `ingest_job_id`
- [x] 2.5 更新 `pipeline.py:180` 和 `test_ingestion_*.py` mock 签名

## 3. 实现递进降级

- [x] 3.1 新增 `_split_at_heading_level(self, elements, level)` — 在指定 heading_level 切分
- [x] 3.2 新增 `_split_recursive(self, section, level)` — 仅超限 section 按 level+1 下钻
- [x] 3.3 新增 `_split_by_semantic(self, section)` — 相邻元素 embedding 相似度断点切分
- [x] 3.4 重写 `_split_section` — token 硬切兜底，重叠 20%
- [x] 3.5 修正 `_estimate_tokens`：计入 `el.structured_data`，因子 `// 2` → `/ 1.8`

## 4. 实现全文优先入口

- [x] 4.1 重写 `extract()`：
  - 全文 < 阈值 → `_extract_section(全文)` → LLM
  - 超限 / LLM 失败 → `_split_recursive(elements, level=1)`
  - section 级失败 → 下一层切分或 `_fallback_chunks`
- [x] 4.2 安全阈值配置化：`context_window × 0.8`
- [x] 4.3 更新类 docstring 和关键方法注释为中文

## 5. 增强 Prompt

- [x] 5.1 新增"知识块切分原则"章节（标题边界、同主题合并、表格/图片归属、字数 200-800）
- [x] 5.2 新增 `list` 分层处理策略（步骤→自然语言、嵌套→保留层级、词汇→保留词条格式）
- [x] 5.3 新增 `code` 按 language 路由策略（脚本→概括+签名、配置→描述、SQL→自然语言、命令→保留+解释）
- [x] 5.4 `_elements_to_json` 代码元素注入 `language` 字段
- [x] 5.5 prompt 输出格式中移除 `asset_refs.relation` 字段

## 6. Pipeline 清理

- [x] 6.1 删除 `_attach_unreferenced_video_assets` 方法和调用点
- [x] 6.2 `_process_document_link` 中 `self.ingest(child_doc)` → daemon thread

## 7. 更新测试

- [x] 7.1 `test_extract_full_document` — 全文一次 LLM
- [x] 7.2 `test_split_at_heading_level` — 按 h1/h2/h3 切分
- [x] 7.3 `test_split_recursive_only_oversized` — 仅超限下钻
- [x] 7.4 `test_split_recursive_h1_h2_h3` — 多层级递进
- [x] 7.5 `test_extract_llm_call_failure` — 调不通 → 降级
- [x] 7.6 `test_extract_llm_empty_result` — 返回空 → 降级
- [x] 7.7 `test_section_llm_failure_further_split` — section 级失败继续下钻
- [x] 7.8 `test_semantic_split_exceeds_token_still_hard_split` — embedding 切后仍超限
- [x] 7.9 `test_no_headings_semantic_split` — 无标题走 embedding
- [x] 7.10 `test_build_chunks_empty_source_refs` — 验证空兜底
- [x] 7.11 `test_asset_ref_no_relation_field` — AssetRef 无 relation
- [x] 7.12 更新 mock 签名 + 旧测试中对 `relation` 字段的引用

## 8. 最终验证

- [ ] 8.1 `pytest tests/ -v`
- [ ] 8.2 `pytest tests/test_ingestion_*.py -v`
- [ ] 8.3 手动验证：小文档全文路径 + 超大文档递进降级
