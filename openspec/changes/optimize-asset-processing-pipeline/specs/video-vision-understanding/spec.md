## MODIFIED Requirements

### Requirement: 视频内容总结生成

系统 SHALL 在入库流程中，对可获取字节的视频资源调用火山引擎多模态模型（Ark SDK `chat.completions.create`）进行内容总结，结果写入 `Asset.extracted_text`。`mime_type` 由 `sniff_video_mime(data)` 通过文件魔数确定，不再依赖解析阶段的扩展名推断。

#### Scenario: 成功生成视频总结

- **WHEN** 视频字节可获取（内嵌视频或可下载的本地视频文件）
- **THEN** 系统通过 `sniff_video_mime(data)` 魔数推断确定 MIME 类型，写入 `asset.metadata["mime_type"]`
- **AND** 若魔数无法识别视频格式，使用 `"video/mp4"` 作为 fallback
- **AND** 系统将视频以 base64 data URI 格式作为 `video_url` content part 发送给多模态模型
- **AND** 请求使用视频描述专用 system prompt，要求模型总结视频的关键内容和主题
- **AND** 设置 `fps=0.5` 参数控制采样帧率
- **AND** 模型返回的文本写入 `Asset.extracted_text`

#### Scenario: 视频模型调用失败不阻塞入库

- **WHEN** 多模态模型调用失败（API 错误、超时、请求体过大等）
- **THEN** 系统记录 WARNING 日志，将 `Asset.extracted_text` 保持为 `None`
- **AND** 视频 Asset 状态不受影响
- **AND** 不阻塞同一文档其他资源或文本元素的处理

#### Scenario: 平台链接视频不作为视觉提取目标

- **GIVEN** 视频以链接形式嵌入在文字中（如微信云盘、YouTube、B站等平台链接）
- **WHEN** 系统无法获取视频字节
- **THEN** 系统不调用视觉提取，保留视频 Asset 记录
- **AND** `Asset.extracted_text` 通过 LLM 从视频周围的文字上下文中自然推断主题
- **AND** `Asset.original_uri` 保留原始链接，检索结果中可访问

#### Scenario: 非视频资源不调用视觉提取

- **WHEN** Asset 的 `asset_type` 不为 `video`
- **THEN** 系统跳过视频视觉提取步骤
