## 1. Prompt 准备

- [x] 1.1 新增 `IMAGE_DESCRIPTION_SYSTEM` prompt（`llm/prompts.py`）：要求模型用中文描述图片中的界面元素、文字内容、流程步骤等信息，控制在 100-200 字
- [x] 1.2 新增 `VIDEO_DESCRIPTION_SYSTEM` prompt（`llm/prompts.py`）：要求模型总结视频的关键内容和主题，按时间顺序描述，控制在 200-400 字
- [x] 1.3 更新 `SEMANTIC_EXTRACT_SYSTEM` prompt（`llm/prompts.py`）：新增指令——若窗口输入包含 `asset_descriptions`，将资源描述内容自然融合到知识块正文中

## 2. 视觉理解客户端

- [x] 2.1 在 `LLMClient` 类中新增 `describe_image(image_bytes: bytes, mime_type: str) -> str | None` 方法（`llm/volcengine_client.py`）：构造 Ark SDK vision chat 请求，base64 编码图片，调用 `ark.chat.completions.create`，失败返回 `None`
- [x] 2.2 在 `LLMClient` 类中新增 `describe_video(video_bytes: bytes, mime_type: str, fps: float = 0.5) -> str | None` 方法（`llm/volcengine_client.py`）：构造 Ark SDK video vision chat 请求，设置 `fps` 参数，失败返回 `None`
- [x] 2.3 两个方法签名预留 `image_url: str | None` / `video_url: str | None` 可选参数，当传入 URL 时跳过 base64 编码直接使用 URL

## 3. 图片处理器集成

- [x] 3.1 在 `process_image()` 中，MinIO 上传之前（去重之后）调用 `describe_image()` 生成 `extracted_text`（`assets/image_processor.py`）
- [x] 3.2 视觉调用失败时优雅降级——记录 WARNING 日志，`extracted_text` 保持 `None`，图片仍然上传 MinIO
- [x] 3.3 在 `app/core/config.py` 新增 `image_vision_enabled: bool = True` 配置项，为 `false` 时跳过视觉提取

## 4. 语义抽取器改造

- [x] 4.1 改造 `_elements_to_json()`（`llm/semantic_extractor.py`）：为每个元素查找 `asset_ids` 关联的 Asset，将具有 `extracted_text` 的 Asset 信息以 `asset_descriptions` 格式注入 JSON
- [x] 4.2 Asset 信息通过参数传入 `_elements_to_json()` 或 `_process_window()`，确保 `_build_chunks()` 中已有的 `assets_by_id` 查找逻辑可复用

## 5. 视频处理链路

- [x] 5.1 在 `_prepare_assets()` 中，对 `asset_type=video` 且可获取字节的 Asset 调用 `describe_video()` 生成 `extracted_text`（`ingestion/pipeline.py` 或 `assets/image_processor.py`）
- [x] 5.2 外链视频（`storage_uri=None`，字节不可获取）保持当前行为，不调用视觉提取

## 6. 测试

- [x] 6.1 新增 `tests/test_vision_client.py`：通过 mock Ark SDK 验证 `describe_image()` 和 `describe_video()` 的请求构造和响应处理
- [x] 6.2 新增 `tests/test_image_processor_vision.py`：验证 `process_image()` 在视觉成功/失败/禁用时的行为
- [x] 6.3 新增 `tests/test_semantic_extractor_asset_descriptions.py`：验证 `_elements_to_json()` 正确注入 `asset_descriptions`
- [x] 6.4 更新 `tests/e2e/e2e_real_chain_file.py`：e2e 测试使用 markdown 文档（无图片），Phase 5 改动不涉及 API 合约变更，已有 e2e 全部 153 个测试通过即验证链路完整
