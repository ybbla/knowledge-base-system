---
name: async-ingestion-plan
description: 异步入库改造方案，解决弹条无意义问题
metadata: 
  node_type: memory
  type: project
  originSessionId: 4d8d7a33-49fe-4436-af59-80e277f108ec
---

## 问题

当前入库是同步的：POST /upload 在同一个 HTTP 请求中完成上传+解析+embedding+索引全部流程后才返回。导致：
- 前端 await 阻塞，弹窗迟迟不关闭
- 弹条出现时文档已是终态，轮询无意义

## 改造方向

将"接收上传"与"处理入库"分离：
1. POST /upload 写文件后立即返回 `{status:"processing", doc_id}`
2. 后台异步任务完成解析→embedding→索引

两种实现：
- **轻量**：FastAPI `BackgroundTasks`，零依赖，但进程重启丢任务
- **完善**：Celery/Redis 任务队列，隔离好、可重试，但增加组件

## 相关文件

- `knowledge_base_system/app/api/v1/documents.py` — upload 端点
- `knowledge_base_system/ingestion/pipeline.py` — 入库流水线
- `frontend/js/components/documents.js` — doUpload、showProcessingToast

## 前端配套

异步后弹条逻辑：上传即关弹窗 → 弹条轮询 doc_id 状态 → active/failed → 消失
