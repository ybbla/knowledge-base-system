## Why

当前系统对图片和视频资源只做了工程层面的处理（格式校验、hash 去重、MinIO 上传），没有调用多模态模型理解资源内容。语义抽取阶段，LLM 只能看到 `[图片: screenshot.png]` 这样的占位文本，无法真正融合图片和视频中的语义信息到知识块中——图片中的界面操作、流程图、表格数据等关键信息完全丢失。这导致含图文档（如操作手册、培训材料）的检索质量严重受损。

## What Changes

- 新增图片视觉理解能力：调用火山引擎多模态模型（Ark SDK），在入库流程中对图片资源进行内容描述，结果写入 `Asset.extracted_text`
- 新增视频语义理解能力：调用多模态模型对可获取的视频进行内容总结
- 改造语义抽取窗口：将 `Asset.extracted_text` 注入 LLM 输入，使图片/视频语义能自然融入知识块正文
- 视觉调用采用 base64 直传策略，不依赖 MinIO 公网可达；方法签名预留 URL 分支便于后续切换
- 不预设资源大小阈值——边界判断交由 API 返回决定，调用失败时优雅降级

## Capabilities

### New Capabilities
- `image-vision-understanding`: 图片视觉理解——通过多模态模型生成图片内容描述，存储为 Asset.extracted_text，供语义抽取阶段融合使用
- `video-vision-understanding`: 视频语义理解——对可获取的视频调用多模态模型生成内容总结，写入 Asset.extracted_text

### Modified Capabilities
- `semantic-extraction`: LLM 窗口输入新增 `asset_descriptions` 字段，包含关联资源的 `extracted_text` 描述，使 LLM 能够将图片和视频的语义自然融合到知识块正文中

## Impact

- **受影响的代码**: `llm/volcengine_client.py`（新增 `describe_image`/`describe_video` 方法）、`llm/prompts.py`（新增视觉描述 prompt）、`llm/semantic_extractor.py`（`_elements_to_json()` 注入资源描述）、`assets/image_processor.py`（`process_image()` 新增视觉提取步骤）
- **API**: 无新增 API 端点，入库和检索接口保持兼容（`extracted_text` 字段已存在于 Asset 模型）
- **依赖**: 无新增依赖（Ark SDK 已集成，LLMClient 已迁移）
- **回滚计划**: 视觉提取失败不阻塞入库流程——图片/视频仍然上传 MinIO，`extracted_text` 保持 `None` 时 LLM 行为回退到当前状态。可随时通过配置开关禁用视觉调用
