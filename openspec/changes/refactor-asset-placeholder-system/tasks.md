## 1. 数据模型层

- [x] 1.1 AssetType 枚举新增 web_link 值
- [x] 1.2 Asset 模型新增 display_text 字段，更新类级注释
- [x] 1.3 更新 AssetData.placeholder 注释（格式 {{type:n}}）

## 2. 工具函数

- [x] 2.1 parsers/utils.py 新增 classify_link_text() 函数
- [x] 2.2 定义 _LINK_TEXT_IMAGE_EXT / _LINK_TEXT_VIDEO_EXT / _LINK_TEXT_DOC_EXT 常量

## 3. docx 解析器

- [x] 3.1 _PLACEHOLDER_PREFIX 新增 "web_link": "web" 映射；格式改为 {{prefix:n}}
- [x] 3.2 _build_image_asset_map：original_uri=""，metadata 存 filename，视频按扩展名设 asset_type
- [x] 3.3 _process_paragraph 内联图片：占位符改为 {{image:N}}（去掉 [图片: name] 前缀）
- [x] 3.4 _process_paragraph 超链接：改用 classify_link_text(link_text)，链接文字被占位符替换，display_text 存锚文本
- [x] 3.5 _process_paragraph 字段指令：去掉文件名保留，仅占位符
- [x] 3.6 _process_table：同步上述段落改动
- [x] 3.7 删除 _extract_videos 方法和 _classify_link_url 方法
- [x] 3.8 更新方法级注释

## 4. markdown 解析器

- [x] 4.1 placeholder_for() 格式改为 {{prefix:n}}，label_map url→web
- [x] 4.2 链接文字被占位符替换，display_text 存锚文本
- [x] 4.3 链接分类改用 classify_link_text()

## 5. pdf 解析器

- [x] 5.1 嵌入图片 original_uri=""，metadata 存 filename
- [x] 5.2 图片占位符改为 {{image:N}}
- [x] 5.3 超链接分类改用 classify_link_text(anchor_text)
- [x] 5.4 链接文字被占位符替换

## 6. html 解析器

- [x] 6.1 图片占位符改为 {{image:N}}，视频占位符改为 {{video:N}}
- [x] 6.2 超链接分类改用 classify_link_text()

## 7. pptx 解析器

- [x] 7.1 图片占位符改为 {{image:N}}
- [x] 7.2 嵌入图片 original_uri=""，metadata 存 filename

## 8. xlsx 解析器

- [x] 8.1 图片占位符改为 {{image:N}}
- [x] 8.2 嵌入图片 original_uri=""

## 9. 资源处理层

- [x] 9.1 asset_processor.py：process_image/process_video 删除 original_uri 降级读数据路径
- [x] 9.2 _process_image_data/_process_video_data：文件名从 metadata["filename"] 获取，链接类型从 original_uri 取
- [x] 9.3 minio_store.py put()：文件名从 metadata["filename"] 获取，链接类型从 original_uri 取
- [x] 9.4 pipeline.py _prepare_assets：web_link 分支 → asset_store.put()

## 10. 语义抽取层

- [x] 10.1 semantic_extractor._elements_to_json：嵌入类型 Asset URL 取 storage_uri，链接类型取 original_uri

## 11. 测试更新

- [ ] 11.1 test_models.py：占位符格式 [image1] → {{image:1}}
- [ ] 11.2 test_docx_parser.py：占位符格式 [图片: xxx] → {{image:N}}
- [ ] 11.3 test_pdf_parser.py：占位符格式更新
- [ ] 11.4 test_semantic_extractor_asset_descriptions.py：占位符格式更新
- [ ] 11.5 test_semantic_extractor_full_doc.py：占位符格式更新
- [ ] 11.6 test_parser_utils.py：新增 classify_link_text 测试用例

## 12. 集成验证

- [ ] 12.1 清空数据库，上传 直播间订单店长操作手册.docx，验证视频链接占位符和 Asset
- [ ] 12.2 上传 加盟商要货取消白名单培训.docx，验证嵌入图片占位符
- [ ] 12.3 上传 北京.docx，验证混合资源（嵌入图+视频链接+普通链接）
- [ ] 12.4 运行全量 pytest 确保无回归
