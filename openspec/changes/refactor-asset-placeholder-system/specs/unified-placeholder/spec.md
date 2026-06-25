## ADDED Requirements

### Requirement: 统一占位符格式为 {{type:n}}
所有解析器 SHALL 使用 `{{type:n}}` 格式的占位符，其中 type 为资源类型前缀，n 为递增序号。

#### Scenario: 嵌入图片占位符
- **WHEN** 解析器遇到嵌入图片
- **THEN** 系统 SHALL 生成 `{{image:1}}` `{{image:2}}` 格式的占位符
- **AND** 占位符追加到段落文本中

#### Scenario: 嵌入视频占位符
- **WHEN** 解析器遇到嵌入视频
- **THEN** 系统 SHALL 生成 `{{video:1}}` `{{video:2}}` 格式的占位符

#### Scenario: 链接类型占位符
- **WHEN** 解析器遇到超链接且 classify_link_text 返回 image_link/video_link/document_link/web_link
- **THEN** 系统 SHALL 生成对应 `{{image:N}}` `{{video:N}}` `{{doc:N}}` `{{web:N}}` 占位符

#### Scenario: 各类型独立计数
- **WHEN** 同一文档包含嵌入图片、视频链接和文档链接
- **THEN** 各类型 SHALL 独立从 1 开始计数
- **AND** `{{image:1}}` `{{video:1}}` `{{doc:1}}` 可同时存在

### Requirement: 链接文字被占位符替换
解析器在段落文本中 SHALL 用占位符替换链接文字，不保留原文。

#### Scenario: 超链接文字被替换
- **WHEN** 段落原文为 "点击天空.png查看详情" 且 "天空.png" 是超链接文字
- **THEN** 解析后的段落文本 SHALL 为 "点击{{image:1}}查看详情"

#### Scenario: 字段指令文字被替换
- **WHEN** docx 字段指令的显示文字为 "xxx.mov"
- **THEN** 解析后的段落文本 SHALL 仅包含 `{{video:1}}`，不保留 "xxx.mov"

### Requirement: AssetData.placeholder 存储占位符
每个 Asset 关联的 AssetData.placeholder SHALL 存储对应的占位符字符串。

#### Scenario: asset_data 映射
- **WHEN** 解析器创建 image_link Asset 并生成 `{{image:3}}` 占位符
- **THEN** 关联的 AssetData.placeholder SHALL 为 "{{image:3}}"
- **AND** AssetData.asset_id SHALL 指向对应 Asset
