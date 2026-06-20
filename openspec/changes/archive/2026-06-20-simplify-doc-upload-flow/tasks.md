## 1. 数据模型修改

- [x] 1.1 修改 `app/core/models.py` - DocStatus 移除 pending
- [x] 1.2 修改 `app/core/models.py` - ChunkStatus 移除 superseded
- [x] 1.3 修改 `app/core/models.py` - Document 新增 previous_doc_id 和 error_message
- [x] 1.4 修改 `app/core/models.py` - Document 移除 ingest_job_id
- [x] 1.5 修改 `app/db/models.py` - DbDocument 添加新字段（旧字段保留）

## 2. Repository 层修改

- [x] 2.1 修改 `app/db/repositories/documents.py` - _to_db/_from_db 适配新字段
- [x] 2.2 新增 `DocumentRepository.find_similar_by_filename()` - 检测同名文件
- [x] 2.3 新增 `DocumentRepository.get_version_history()` - 获取版本历史

## 3. API 层修改

- [x] 3.1 修改 `app/api/v1/documents.py` - _doc_to_item 适配新字段
- [x] 3.2 修改 `app/api/v1/documents.py` - upload_document 添加新参数和逻辑
- [x] 3.3 修改 `app/api/v1/documents.py` - list_documents 移除 ingest_job_id 相关参数
- [x] 3.4 移除 `app/api/v1/documents.py` - /{doc_id}/ingest 接口
- [x] 3.5 新增 `app/api/v1/documents.py` - /{doc_id}/history 接口

## 4. 前端修改

- [x] 4.1 修改 `frontend/js/components/documents.js` - 文档列表添加"更新"按钮
- [x] 4.2 修改 `frontend/js/components/documents.js` - 移除"重处理"按钮
- [x] 4.3 修改 `frontend/js/components/documents.js` - 上传逻辑适配 suggested_replace 响应
- [x] 4.4 修改 `frontend/js/components/documents.js` - 添加更新确认弹窗

## 5. 测试和验证

- [x] 5.1 运行现有测试，确保没有回归
- [x] 5.2 手动测试上传新文档流程
- [x] 5.3 手动测试同名文件检测和更新流程
- [x] 5.4 手动测试"更新"按钮流程
- [x] 5.5 手动测试版本历史查看
