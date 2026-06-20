## Context

当前文档上传流程存在以下问题：
1. `pending` 状态实际上从未被使用（文档上传后立即进入 `processing`）
2. `ingest_job_id` 引入了不必要的任务追踪概念，增加了复杂度
3. 缺少便捷的文档更新方式
4. `parent_doc_id`、`root_doc_id` 用于嵌入文档，需要保留；`previous_doc_id` 用于版本历史，需要新增

**当前状态**：
- Document 模型字段：`doc_id`、`title`、`source_type`、`source_uri`、`source_hash`、`version`、`status`、`parent_doc_id`、`root_doc_id`、`ingest_job_id`、`created_at`、`updated_at`、`metadata`
- DocStatus：`active`、`deleted`、`failed`、`pending`、`processing`
- ChunkStatus：`active`、`superseded`、`deleted`

## Goals / Non-Goals

**Goals:**
- 简化状态模型，移除未使用的 `pending` 状态
- 移除不必要的 `ingest_job_id` 字段
- 新增 `previous_doc_id` 用于版本历史追踪
- 新增 `error_message` 用于展示失败原因
- 提供便捷的文档更新流程（自动检测同名 + 手动更新按钮）
- 移除 `ChunkStatus.superseded`，使用 `deleted` 替代
- 保持向后兼容（数据库旧字段先保留）

**Non-Goals:**
- 不实现复杂的版本对比和回滚功能
- 不修改嵌入文档的 `parent_doc_id`、`root_doc_id` 逻辑
- 不改变现有的软删除机制

## Decisions

### Decision 1: 状态模型简化
**选择**：移除 `DocStatus.pending`，初始状态设为 `processing`

**理由**：
- `pending` 状态在当前代码中从未被实际使用
- 文档上传后立即开始处理，不需要等待状态
- 简化状态流转图

**替代方案**：
- 保留 `pending` 但仅作为保留状态（增加维护成本）

### Decision 2: 移除 `ingest_job_id`
**选择**：从 Document 模型中移除 `ingest_job_id` 字段

**理由**：
- 任务追踪不是核心功能，用户主要关注文档状态而非任务 ID
- 减少概念复杂度
- 任务状态已通过 Document 的 status 字段体现

**替代方案**：
- 保留字段但弃用（向后兼容，增加维护成本）

### Decision 3: 新增 `previous_doc_id` 和 `error_message`
**选择**：新增 `previous_doc_id`（string | null）和 `error_message`（string | null）

**理由**：
- `previous_doc_id` 用于追踪版本历史
- `error_message` 用于友好展示入库失败原因
- 两个字段都是可选的，不影响现有数据

**替代方案**：
- 将版本历史存储在独立的表中（增加复杂度）

### Decision 4: 文档更新流程
**选择**：
- 上传时检测同名文件，返回提示
- 提供 `replace_doc_id` 和 `confirm_replace=true` 参数确认更新
- 更新时：软删除旧文档及知识块 → 创建新版本

**理由**：
- 用户体验清晰，避免误操作
- 软删除保留历史，可恢复
- 流程简单易理解

**替代方案**：
- 覆盖更新（简单但历史丢失）
- 复杂的增量更新（保留当前实现）

### Decision 5: 数据库向后兼容
**选择**：保留 `parent_doc_id`、`root_doc_id`、`ingest_job_id` 数据库字段，但在代码层面忽略它们

**理由**：
- 避免数据库迁移风险
- `parent_doc_id`、`root_doc_id` 仍在使用中
- 未来可安全清理

**替代方案**：
- 立即删除字段（需要数据库迁移，风险高）

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| 移除 `ingest_job_id` 可能影响现有集成 | 检查代码库中是否有依赖该字段的地方，做好沟通 |
| 同名文件检测可能误判（不同文件同名） | 检测到多个同名文件时不提示，让用户用"更新"按钮 |
| 软删除保留历史可能占用存储空间 | 未来可考虑定期清理长期 deleted 状态的文档 |
| 前端需要修改以适配新 API | 保持 API 变化尽量小，提供清晰的迁移路径 |

## Migration Plan

1. 先修改数据模型和 Repository，保持向后兼容
2. 修改 API 层，添加新字段和新接口
3. 修改前端，适配新 API 和新交互
4. 测试完整流程
5. 部署上线

**回滚策略**：
- 代码层面保留对旧字段的读取支持（不写）
- 如有问题，可快速回滚代码版本

## Open Questions

1. 是否需要在文档详情页展示版本历史？（可以后续迭代）
2. 是否需要定期清理 deleted 状态的文档？（可以后续迭代）
