# Image Vision Understanding

## Purpose

在入库流程中对图片资源调用多模态模型生成内容描述（`extracted_text`），使语义抽取阶段能融合图片语义到知识块正文中。视觉提取在 MinIO 上传之前执行，base64 直传，不依赖 MinIO 公网可达。

> 新建自 change `phase-5-multimodal-enhancement`，日期 2026-06-15。

## ADDED Requirements

### Requirement: 图片内容描述生成

系统 SHALL 在图片资源完成格式校验和 hash 去重后、上传 MinIO 之前，调用火山引擎多模态模型（Ark SDK `chat.completions.create`）对图片内容进行中文描述，结果写入 `Asset.extracted_text`。

#### Scenario: 成功生成图片描述

- **WHEN** 图片字节通过格式校验，且未命中去重
- **THEN** 系统将图片以 base64 data URI 格式（`data:{mime};base64,{data}`）作为 `image_url` content part 发送给多模态模型
- **AND** 请求使用图片描述专用 system prompt，要求模型描述图片中的界面元素、文字内容、流程步骤等信息
- **AND** 模型返回的文本写入 `Asset.extracted_text`

#### Scenario: 去重命中复用已有描述

- **WHEN** 图片的 sha256 hash 与已有 `status=ready` 的 Asset 匹配
- **THEN** 系统复用已有 Asset 的 `extracted_text`，不重复调用视觉 API
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

- **WHEN** 配置项 `IMAGE_VISION_ENABLED` 为 `false` 或未设置
- **THEN** 系统跳过视觉提取步骤，图片仅做格式校验、去重和上传

### Requirement: 图片视觉提取不预设大小阈值

系统 SHALL 不对图片大小预设硬性阈值，直接以 base64 编码发送给多模态模型。API 返回请求体过大错误时，系统记录错误并优雅降级。

#### Scenario: 任意大小图片尝试提取

- **WHEN** 图片完成格式校验和去重
- **THEN** 系统对所有大小的图片均尝试调用视觉模型，不做客户端侧的大小判断和跳过

#### Scenario: API 拒绝过大请求体

- **WHEN** 多模态模型 API 返回请求体过大错误（如 HTTP 413）
- **THEN** 系统捕获异常，`Asset.extracted_text` 保持 `None`，记录 WARNING 日志
- **AND** 图片仍然正常上传 MinIO

### Requirement: 视觉提取使用 Ark SDK

系统 SHALL 通过 Ark SDK 的 `chat.completions.create` 接口调用多模态模型，不引入额外的 HTTP 客户端或 SDK。

#### Scenario: 构造 vision chat 请求

- **WHEN** 系统调用 `describe_image(data, mime)` 方法
- **THEN** 请求 messages 包含 `system` 角色（图片描述 prompt）和 `user` 角色（包含 `image_url` content part）
- **AND** `image_url.url` 格式为 `data:{mime};base64,{base64_encode(data)}`
- **AND** 使用 LLMClient 已有的重试和 JSON 提取逻辑

#### Scenario: 方法签名预留 URL 分支

- **WHEN** `describe_image()` 方法被调用
- **THEN** 方法接受 `image_bytes` 和 `mime_type` 作为必需参数
- **AND** 方法签名预留 `image_url: str | None` 可选参数，以便将来切换为公网 MinIO presigned URL 方式传递图片
