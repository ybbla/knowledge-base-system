## Context

当前系统对图片和视频资源仅做工程层处理（格式校验、hash 去重、MinIO 上传），`Asset.extracted_text` 始终为 `None`。语义抽取阶段 LLM 收不到任何图片/视频内容信息，导致含图文档（操作手册截图、流程图、界面说明等）的知识块缺失关键语义。

LLMClient 已迁至 Ark SDK（`volcenginesdkarkruntime`），`ark.chat.completions.create` 与 OpenAI SDK 同构，且 Ark SDK 原生支持 `ChatCompletionContentPartImageParam` 和 `ChatCompletionContentPartVideoParam`——视觉调用无需额外依赖。

MinIO 为 Docker 部署（`localhost:9000`），火山引擎 API 服务器无法访问内网地址。因此图片数据以 base64 data URI 格式直接嵌入请求体传输。

## Goals / Non-Goals

**Goals:**
- 在入库流程中对图片调用多模态模型生成 `extracted_text`，结果写入 Asset
- 改造语义抽取窗口，将 `extracted_text` 注入 LLM 输入
- 为视频提供同等的视觉理解接口（`describe_video`），方法就位，当前文档集中视频场景极少时自动不触发
- 视觉提取失败不阻塞入库，优雅降级
- 不预设资源大小阈值，边界判断交由 API 返回

**Non-Goals:**
- 不在本轮引入 Pillow 图片压缩（需要时后续补充）
- 不做 MinIO 公网暴露
- 不处理外链视频下载和安全校验（保持当前 pending 行为）
- 不做知识块二次更新机制（视觉提取在语义抽取前完成，一次到位）
- 不新增 API 端点

## Decisions

### 1. 视觉提取放在 `process_image()` 中，MinIO 上传之前

**选择**：在 `process_image()` 内，格式校验和去重之后、MinIO 上传之前调用视觉模型。

**理由**：
- 图片字节已在内存（`data` 变量），无需从 MinIO 回读
- 去重优先——hash 命中直接复用 `extracted_text`，避免重复调用视觉 API
- 视觉失败不影响 MinIO 上传——图片仍然落存储，`extracted_text` 为 `None` 时 LLM 回退到当前行为
- 与语义抽取天然串行——入库 `_run()` 中 `_prepare_assets()` 在 `semantic_extraction()` 之前执行

**替代方案考虑过**：
- 异步提取（入库后触发）：增加块更新/重新索引复杂度，不符合 MVP 简洁原则
- 在语义抽取时传图：LLM 不是视觉模型，且语义抽取 prompt 设计已聚焦文本重组，不宜混入视觉调用

### 2. base64 直传，方法签名预留 URL 分支

**选择**：`describe_image(data, mime)` 和 `describe_video(data, mime, fps)` 以 base64 编码，通过 Ark SDK 的 `image_url.url` / `video_url.url` 传 `data:{mime};base64,{...}`。方法签名预留 `image_url: str | None` 可选参数。

**理由**：
- MinIO Docker 部署，`localhost:9000` 对火山引擎 API 服务器不可达
- base64 直传无需额外网络配置和运维成本
- 预留 URL 参数可在将来 MinIO 公网可达时无缝切换，不改方法签名

### 3. 不预设大小阈值

**选择**：不对图片/视频大小做客户端侧硬性限制。API 返回请求体过大错误时捕获并优雅降级。

**理由**：
- Ark API 网关的请求体上限需实测确认，预设数字（如 5MB、10MB）没有依据
- 文档内嵌图片通常经过 Office 压缩（50-500KB），极少触发限制
- 视频通过 `fps` 参数已大幅减少模型处理量，实际 API 上限可能足够

### 4. `describe_image` 和 `describe_video` 作为 `LLMClient` 的方法

**选择**：在现有 `LLMClient` 类上新增 `describe_image()` 和 `describe_video()` 方法，而非创建独立的 VisionClient 类。

**理由**：
- 两类调用共用同一 API 端点（`ark.chat.completions.create`）、同一认证（`ARK_API_KEY`）、同一重试逻辑
- `LLMClient` 已迁至 Ark SDK，`chat_json()` 和 `describe_image()` 天然同源
- 避免引入新的模块级单例，减少依赖注入变更

### 5. 语义抽取窗口注入 `asset_descriptions`

**选择**：在 `_elements_to_json()` 中为每个元素查找关联 Asset 的 `extracted_text`，作为 `asset_descriptions` 字段注入 JSON。`build_extraction_messages()` 的 system prompt 新增指令：要求 LLM 将资源描述内容自然融合到知识块正文。

**理由**：
- 元素 JSON 已有 `asset_ids`，扩展出 `asset_descriptions` 是最小改动
- 不在 LLM prompt 中放入图片字节——语义模型的职责是文本重组，视觉理解已由视觉模型完成
- 对现有 chunk 结构零影响——`extracted_text` 是 Asset 字段，`asset_refs` 不变

## Affected Files

| 文件 | 变更类型 | 说明 |
|------|:---:|------|
| `llm/volcengine_client.py` | 修改 | 新增 `describe_image()`、`describe_video()` 方法 |
| `llm/prompts.py` | 修改 | 新增 `IMAGE_DESCRIPTION_SYSTEM`、`VIDEO_DESCRIPTION_SYSTEM`；更新 `SEMANTIC_EXTRACT_SYSTEM` |
| `llm/semantic_extractor.py` | 修改 | `_elements_to_json()` 注入 `asset_descriptions` |
| `assets/image_processor.py` | 修改 | `process_image()` 新增视觉提取步骤；新增 `process_video()` 函数 |
| `ingestion/pipeline.py` | 修改 | `_prepare_assets()` 新增视频处理分支 |
| `app/core/config.py` | 修改 | 新增 `image_vision_enabled: bool = True` 配置开关 |
| `requirements.txt` | 不变 | 无新增依赖（Pillow 本轮不加） |

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 每张图 1-3 秒视觉 API 调用，大文档入库延迟显著增加 | 用户体验 | 入库本身已是异步（`threading.Thread`），用户不感知；hash 去重减少重复调用；可通过 `IMAGE_VISION_ENABLED=false` 禁用 |
| 视觉模型 API 成本 | 运营成本 | hash 去重已就位——同一图片在多个文档中仅调用一次；fps 参数控制视频成本 |
| 视觉模型的描述质量不稳定 | 知识块质量 | 现有 fallback 机制不变——LLM 提取失败时有 `_fallback_chunks()`；`extracted_text=None` 时回退到当前行为 |
| 大视频 base64 可能超 API 限制 | 部分视频无法处理 | 捕获异常优雅降级；当前文档集以 DOCX/XLSX 为主，视频场景极少 |

## Open Questions

- 火山引擎 Ark API 的请求体实际上限是多少？需要实测确认，以便后续决定是否需要客户端侧压缩策略
- 图片视觉描述的延迟（每张图 1-3 秒）在实际业务文档入库时是否可接受？需要上线后观察
