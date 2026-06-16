# Video Vision Understanding

## Purpose

在入库流程中对可获取的视频资源调用多模态模型生成内容总结（`extracted_text`），使语义抽取阶段能融合视频语义到知识块正文中。采用 base64 直传策略，通过 `fps` 参数控制采样帧率以平衡效果和成本。

> 新建自 change `phase-5-multimodal-enhancement`，日期 2026-06-15。

## ADDED Requirements

### Requirement: 视频内容总结生成

系统 SHALL 在入库流程中，对可获取字节的视频资源调用火山引擎多模态模型（Ark SDK `chat.completions.create`）进行内容总结，结果写入 `Asset.extracted_text`。

#### Scenario: 成功生成视频总结

- **WHEN** 视频字节可获取（内嵌视频或可下载的本地视频文件）
- **THEN** 系统将视频以 base64 data URI 格式作为 `video_url` content part 发送给多模态模型
- **AND** 请求使用视频描述专用 system prompt，要求模型总结视频的关键内容和主题
- **AND** 设置 `fps=0.5` 参数控制采样帧率
- **AND** 模型返回的文本写入 `Asset.extracted_text`

#### Scenario: 视频模型调用失败不阻塞入库

- **WHEN** 多模态模型调用失败（API 错误、超时、请求体过大等）
- **THEN** 系统记录 WARNING 日志，将 `Asset.extracted_text` 保持为 `None`
- **AND** 视频 Asset 状态不受影响
- **AND** 不阻塞同一文档其他资源或文本元素的处理

#### Scenario: 外链视频不做视觉提取

- **WHEN** 视频来源于外部平台 URL（YouTube、Vimeo 等）且不可下载
- **THEN** 系统不调用视觉提取
- **AND** `Asset.storage_uri` 保持 `null`
- **AND** `Asset.extracted_text` 保持 `None`
- **AND** 保留原始链接以备后续异步处理

#### Scenario: 非视频资源不调用视觉提取

- **WHEN** Asset 的 `asset_type` 不为 `video`
- **THEN** 系统跳过视频视觉提取步骤

### Requirement: 视频视觉提取不预设大小阈值

系统 SHALL 不对视频大小预设硬性阈值，直接以 base64 编码发送给多模态模型。API 返回请求体过大错误时，系统记录错误并优雅降级。

#### Scenario: 任意大小视频尝试提取

- **WHEN** 视频字节可获取
- **THEN** 系统对所有大小的视频均尝试调用多模态模型，不做客户端侧的大小判断

#### Scenario: API 拒绝过大请求体

- **WHEN** 多模态模型 API 返回请求体过大错误
- **THEN** 系统捕获异常，`Asset.extracted_text` 保持 `None`，记录 WARNING 日志
- **AND** 包含视频文件大小信息以便排查

### Requirement: 视频视觉提取使用 Ark SDK

系统 SHALL 通过 Ark SDK 的 `chat.completions.create` 接口调用多模态模型处理视频。

#### Scenario: 构造 video vision chat 请求

- **WHEN** 系统调用 `describe_video(data, mime, fps)` 方法
- **THEN** 请求 messages 包含 `system` 角色（视频描述 prompt）和 `user` 角色（包含 `video_url` content part）
- **AND** `video_url.url` 格式为 `data:{mime};base64,{base64_encode(data)}`
- **AND** `video_url.fps` 默认值为 0.5

#### Scenario: 方法签名预留扩展

- **WHEN** `describe_video()` 方法被调用
- **THEN** 方法接受 `video_bytes`、`mime_type` 和可选的 `fps` 参数
- **AND** 方法签名预留 `video_url: str | None` 可选参数，以便将来切换为公网 MinIO presigned URL
