# Image Vision Understanding Delta

## MODIFIED Requirements

### Requirement: 非图片资源不调用视觉提取

- **WHEN** Asset 的 `asset_type` 不为 `image` 或 `image_link`
- **THEN** 系统跳过视觉提取步骤

### Requirement: 图片内容描述生成

系统 SHALL 在图片资源完成格式校验和 hash 去重后、上传 MinIO 之前，调用火山引擎多模态模型（Ark SDK `chat.completions.create`）对图片内容进行中文描述，结果写入 `Asset.extracted_text`。此要求同时适用于 `image` 和 `image_link` 类型的 Asset。

#### Scenario: 成功生成图片描述

- **WHEN** 图片字节通过格式校验，且未命中去重
- **THEN** 系统将图片以 base64 data URI 格式（`data:{mime};base64,{data}`）作为 `image_url` content part 发送给多模态模型
- **AND** 请求使用图片描述专用 system prompt，要求模型描述图片中的界面元素、文字内容、流程步骤等信息
- **AND** 模型返回的文本写入 `Asset.extracted_text`

#### Scenario: image_link 下载后生成描述

- **WHEN** `image_link` 类型的 Asset 完成 HTTP 下载和格式校验
- **THEN** 系统对下载的图片字节执行与 `image` 类型相同的视觉理解流程

#### Scenario: 去重命中复用已有描述

- **WHEN** 图片的 sha256 hash 与已有 `status=ready` 的 Asset 匹配
- **THEN** 系统复用已有 Asset 的 `extracted_text`，不重复调用视觉 API

#### Scenario: 视觉模型调用失败不阻塞入库

- **WHEN** 多模态模型调用失败（API 错误、超时、请求体过大等）
- **THEN** 系统记录 WARNING 日志，将 `Asset.extracted_text` 保持为 `None`
- **AND** 图片仍然上传 MinIO，Asset 状态正常更新为 `ready`
- **AND** 不阻塞同一文档其他图片或文本元素的处理

#### Scenario: 视觉提取禁用时跳过

- **WHEN** 配置项 `IMAGE_VISION_ENABLED` 为 `false`
- **THEN** 系统跳过视觉提取步骤，图片仅做格式校验、去重和上传
