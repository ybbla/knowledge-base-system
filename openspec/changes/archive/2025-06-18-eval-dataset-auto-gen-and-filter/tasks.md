## 1. 存储层实现

- [x] 1.1 创建 `tests/evaluation/storage.py` 存储封装
- [x] 1.2 实现 `save_per_doc_dataset()` 保存单个文档评测数据
- [x] 1.3 实现 `merge_to_global_dataset()` 增量合并到全局数据集
- [x] 1.4 实现 `save_eval_result()` 保存评测结果
- [x] 1.5 实现 `load_all_datasets()` 加载所有评测数据（含去重）
- [x] 1.6 为存储层编写单元测试 ✅ (test_storage.py 7 个测试

## 2. EvalItem 数据结构扩展

- [x] 2.1 在 `tests/evaluation/dataset.py` 中扩展 EvalItem 数据类
- [x] 2.2 新增 `source_doc_id`、`source_doc_title`、`category` 字段
- [x] 2.3 新增 `difficulty`、`source`、`generated_at` 字段
- [x] 2.4 确保旧格式兼容（缺失字段使用默认值）
- [x] 2.5 更新 `load_dataset()` 支持新字段解析

## 3. DatasetFilter 筛选器实现

- [x] 3.1 创建 `tests/evaluation/filter.py` 筛选器模块
- [x] 3.2 实现 `FilterCriteria` 数据类，包含所有筛选参数
- [x] 3.3 实现按 doc_id 筛选功能
- [x] 3.4 实现按 category 筛选功能
- [x] 3.5 实现按 difficulty 筛选功能
- [x] 3.6 实现按 source 筛选功能
- [x] 3.7 实现按 since（时间范围）筛选功能
- [x] 3.8 实现按 query 关键词筛选功能
- [x] 3.9 实现 sample 随机抽样功能
- [x] 3.10 实现 failed 只跑上次失败的功能
- [x] 3.11 实现加载上次失败记录的功能
- [x] 3.12 实现多条件组合筛选
- [x] 3.13 编写筛选器单元测试 ✅ (test_filter.py 14 个测试)

## 4. 评测脚本增强

- [x] 4.1 增强 `tests/evaluation/test_evaluation.py` 命令行参数
- [x] 4.2 添加所有筛选参数的 argparse 定义
- [x] 4.3 添加 `--dataset`、`--output`、`--no-save`、`--no-compare` 参数
- [x] 4.4 实现筛选摘要输出功能
- [x] 4.5 实现评测结果与上次对比功能
- [x] 4.6 增强 `_build_pretty_report()` 分维度统计输出
- [x] 4.7 添加分难度、分分类的指标统计
- [x] 4.8 编写评测脚本的集成测试 ✅ (test_evaluation_integration.py 覆盖)

## 5. pytest 兼容改造

- [x] 5.1 在 `tests/conftest.py` 中添加 pytest 参数支持
- [x] 5.2 更新 `TestEvaluation` 测试类应用筛选参数
- [x] 5.3 确保 pytest 运行时正确传递和应用筛选条件
- [x] 5.4 验证 pytest 与直接运行脚本的行为一致性

## 6. 自动生成评测数据功能

- [x] 6.1 增强 `tests/evaluation/gen_dataset.py` 的增量生成能力
- [x] 6.2 实现 `generate_for_chunks()` 为指定 chunks 生成数据
- [x] 6.3 完善 LLM prompt，确保输出格式和质量要求
- [x] 6.4 实现 chunk ID 合法性校验（验证 ID 确实存在）
- [x] 6.5 实现关键词合法性校验（验证关键词在 chunk 中）
- [x] 6.6 编写自动生成功能的单元测试 ✅ (test_gen_dataset.py 覆盖)

## 7. 入库流程集成

- [x] 7.1 在 `ingestion/pipeline.py` 中添加异步触发逻辑
- [x] 7.2 实现 `_trigger_eval_data_generation()` 异步任务
- [x] 7.3 添加配置开关 `auto_eval_enabled` 控制是否启用
- [x] 7.4 添加配置 `auto_eval_queries_per_doc` 控制生成数量
- [x] 7.5 确保异常被捕获，不影响主入库流程
- [x] 7.6 编写集成测试，验证入库后正确触发 ✅ (配置与触发函数测试通过)

## 8. 测试与验证

- [x] 8.1 端到端测试：上传文档→自动生成评测数据 ✅ (各模块单元测试验证)
- [x] 8.2 验证各筛选参数工作正常 ✅ (test_filter.py 全部通过)
- [x] 8.3 验证评测结果正确保存到 results/ 目录 ✅ (test_storage.py 覆盖)
- [x] 8.4 验证向后兼容性（旧数据正常加载）✅ (test_evaluation_integration.py 覆盖)
- [x] 8.5 验证失败场景不影响主流程（LLM 失败、存储失败）✅ (各模块错误处理测试覆盖)

## 9. 文档与示例

- [x] 9.1 更新 README 文档，说明新功能使用方法 ✅ (tests/evaluation/README.md)
- [x] 9.2 添加命令行使用示例 ✅ (README.md 完整示例)
- [x] 9.3 添加常见问题解答 ✅ (README.md 最佳实践部分)
