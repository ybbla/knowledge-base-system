# Video Vision Understanding Delta

## MODIFIED Requirements

### Requirement: 视频内容总结生成

系统 SHALL 在入库流程中对 `video_link` 类型的 Asset 执行 HTTP 下载，调用火山引擎多模态模型进行内容总结，并将视频字节上传 MinIO。结果写入 `Asset.extracted_text`。

#### Scenario: 成功下载并生成视频总结

- **WHEN** `video_link` Asset 进入处理流程
- **THEN** 系统先执行 HTTP 下载获取视频字节
- **AND** 将视频以 base64 data URI 格式作为 `video_url` content part 发送给多模态模型
- **AND** 请求使用视频描述专用 system prompt，设置 `fps=0.5` 参数
- **AND** 模型返回的文本写入 `Asset.extracted_text`
- **AND** 上传视频字节到 MinIO，更新 `storage_uri`

#### Scenario: 视频模型调用失败不阻塞入库

- **WHEN** 多模态模型调用失败（API 错误、超时、请求体过大等）
- **THEN** 系统记录 WARNING 日志，将 `Asset.extracted_text` 保持为 `None`
- **AND** 视频仍然上传 MinIO
- **AND** 不阻塞同一文档其他资源或文本元素的处理

#### Scenario: 视频下载失败不阻塞入库

- **WHEN** 视频 HTTP 下载失败
- **THEN** Asset 标记为 `status=failed`，`error_message` 记录失败原因
- **AND** 不阻塞同一文档其他资源或文本元素的处理

#### Scenario: 非视频资源不调用视觉提取

- **WHEN** Asset 的 `asset_type` 不为 `video_link`
- **THEN** 系统跳过视频视觉提取步骤

### Requirement: 平台链接视频不作为视觉提取目标

- **GIVEN** 视频以链接形式嵌入在文字中（如微信云盘、YouTube、B站等平台链接）
- **WHEN** 系统无法获取视频字节（下载失败或不可下载）
- **THEN** 系统不调用视觉提取，保留视频 Asset 记录
- **AND** `Asset.original_uri` 保留原始链接，检索结果中可访问
