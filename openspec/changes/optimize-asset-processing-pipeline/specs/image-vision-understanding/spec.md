## MODIFIED Requirements

### Requirement: 图片内容描述生成

系统 SHALL 在图片资源完成格式校验和 hash 去重后、上传 MinIO 之前，调用火山引擎多模态模型（Ark SDK `chat.completions.create`）对图片内容进行中文描述，结果写入 `Asset.extracted_text`。`mime_type` 由 `sniff_image_mime(data)` 通过文件魔数确定，不再依赖解析阶段的扩展名推断。

#### Scenario: 成功生成图片描述

- **WHEN** 图片字节通过格式校验，且未命中去重
- **THEN** 系统通过 `sniff_image_mime(data)` 魔数推断确定 MIME 类型，写入 `asset.metadata["mime_type"]`
- **AND** 系统将图片以 base64 data URI 格式（`data:{mime};base64,{data}`）作为 `image_url` content part 发送给多模态模型
- **AND** 请求使用图片描述专用 system prompt，要求模型描述图片中的界面元素、文字内容、流程步骤等信息
- **AND** 模型返回的文本写入 `Asset.extracted_text`

#### Scenario: 去重命中复用已有描述

- **WHEN** 图片的 sha256 hash 与已有 `status=ready` 的 Asset 匹配
- **THEN** 系统复用已有 Asset 的 `storage_uri`、`extracted_text`、`metadata["mime_type"]` 等字段，不重复调用视觉 API
- **AND** 此为现有去重机制的自然扩展，`find_ready_duplicate()` 已将此逻辑实现

#### Scenario: 视觉模型调用失败不阻塞入库

- **WHEN** 多模态模型调用失败（API 错误、超时、请求体过大等）
- **THEN** 系统记录 WARNING 日志，将 `Asset.extracted_text` 保持为 `None`
- **AND** 图片仍然上传 MinIO，Asset 状态正常更新为 `ready`
- **AND** 不阻塞同一文档其他图片或文本元素的处理

#### Scenario: 非图片资源不调用视觉提取

- **WHEN** Asset 的 `asset_type` 不为 `image`
- **THEN** 系统跳过视觉提取步骤，直接进入上传 MinIO 环节

#### Scenario: 视觉提取禁用时跳过

- **WHEN** 配置项 `IMAGE_VISION_ENABLED` 为 `false`
- **THEN** 系统跳过视觉提取步骤，图片仅做格式校验、去重和上传

#### Scenario: 魔数校验失败时标记失败

- **WHEN** `sniff_image_mime(data)` 无法识别图片格式
- **THEN** Asset 状态标记为 `status=failed`，`error_message` 为 `"invalid_image_type"`
- **AND** 不调用视觉 API
- **AND** 不上传 MinIO
