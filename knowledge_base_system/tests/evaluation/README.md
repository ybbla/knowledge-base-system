# 📊 知识库检索评测体系

一个自动化、可筛选、可追溯的检索质量评测系统。

## ✨ 功能特性

- 🚀 **自动生成评测数据**：文档入库时后台自动生成评测查询和标注
- 🔍 **多维度筛选**：支持 8 种筛选条件，灵活选择评测范围
- 📈 **结果持久化**：每次评测结果自动保存，支持历史对比
- 📊 **分维度统计**：按难度、分类等维度展示指标
- 🎯 **回归验证**：只跑上次失败的用例，快速验证修复效果
- 💯 **100% 向后兼容**：完全兼容原有评测数据格式

---

## 🚀 快速开始

### 运行全量评测

```bash
cd knowledge_base_system

# 方式一：独立脚本运行（推荐）
python tests/evaluation/test_evaluation.py

# 方式二：pytest 运行
python -m pytest tests/evaluation/test_evaluation.py -v
```

### 快速抽样验证

```bash
# 随机抽取 10 条快速验证（开发阶段常用）
python tests/evaluation/test_evaluation.py --sample 10
```

### 只评测某个文档

```bash
python tests/evaluation/test_evaluation.py --doc-id doc_abc123
```

---

## 📖 命令行参数

### 🔍 筛选参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--doc-id <id>` | 按文档 ID 筛选 | `--doc-id doc_abc123` |
| `--category <name>` | 按业务分类筛选 | `--category 检索` |
| `--difficulty <level>` | 按难度筛选 | `--difficulty hard` |
| `--source <type>` | 按来源筛选 | `--source auto` / `--source manual` |
| `--since <days>` | 只评测最近 N 天数据 | `--since 7` |
| `--query <keyword>` | 按查询关键词筛选 | `--query 并发` |
| `--sample <N>` | 随机抽样 N 条 | `--sample 20` |
| `--failed` | 只跑上次失败的用例 | `--failed` |

### 📤 输出参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--dataset <path>` | 指定评测数据集文件 | `--dataset custom.json` |
| `--output <path>` | 指定结果输出路径 | `--output my_result.json` |
| `--no-save` | 不保存评测结果 | `--no-save` |
| `--no-compare` | 不与上次结果对比 | `--no-compare` |
| `--verbose, -v` | 显示每条查询详情 | `-v` |

---

## 💡 使用示例

### 开发验证常用

```bash
# 1. 快速抽样 10 条验证代码改动
python tests/evaluation/test_evaluation.py --sample 10

# 2. 只跑上次失败的（验证修复效果）
python tests/evaluation/test_evaluation.py --failed

# 3. 只评测最近一周新增的数据
python tests/evaluation/test_evaluation.py --since 7
```

### 聚焦特定领域

```bash
# 只评测检索相关的困难用例
python tests/evaluation/test_evaluation.py --category 检索 --difficulty hard

# 只看包含"并发"关键词的查询
python tests/evaluation/test_evaluation.py --query 并发

# 组合使用：最近一周、检索分类、中等难度
python tests/evaluation/test_evaluation.py --since 7 --category 检索 --difficulty medium
```

### 质量门禁

```bash
# 全量评测，保存结果用于对比
python tests/evaluation/test_evaluation.py
```

---

## ⚙️ 配置选项

在 `.env` 文件中配置：

```env
# 是否启用入库自动生成评测数据
AUTO_EVAL_ENABLED=true

# 每个文档生成的查询数量（默认 4）
AUTO_EVAL_QUERIES_PER_DOC=4
```

也可以在代码中通过 `settings` 访问：

```python
from app.core.config import settings

print(settings.auto_eval_enabled)              # True
print(settings.auto_eval_queries_per_doc)       # 4
```

---

## 📁 目录结构

```
tests/evaluation/
├── README.md                      # 本文档
├── dataset.py                     # 评测数据模型 + 加载器
├── filter.py                      # 多维度筛选器
├── gen_dataset.py                 # 评测数据自动生成
├── metrics.py                     # 指标计算函数
├── storage.py                     # 数据存储封装
├── test_evaluation.py             # 评测主脚本
│
├── eval_dataset.json              # ✨ 全局评测数据集（人工标注 + 自动生成合并）
│
├── datasets/                      # ✨ 分文档评测数据目录（自动生成）
│   ├── doc_abc123_20240115.json  # 某文档生成的评测数据
│   ├── doc_def456_20240116.json
│   └── ...
│
└── results/                       # ✨ 评测结果目录
    ├── latest.json                # 最新评测结果快捷方式
    ├── eval_result_20240115_143025.json
    ├── eval_result_20240116_091530.json
    └── ...
```

---

## 🏗️ 工作原理

### 自动生成流程

```
用户上传文档
    ↓
文档解析 → 语义抽取 → 索引构建
    ↓
入库完成 ✅
    ↓
[后台异步触发]
    ↓
调用 LLM 生成 4 条查询 → 校验标注合法性 → 保存分文档数据 → 合并到全局数据集
    ↓
你随时可以运行评测验证效果 🎯
```

### 评测指标

| 指标 | 说明 |
|------|------|
| **Recall@5** | 预期的知识块是否出现在前 5 个结果中 |
| **MRR** | 第一个命中结果的排名倒数的均值（越高越好） |
| **Keyword Recall@5** | 前 5 个结果中是否包含全部预期关键词 |

---

## 🧪 添加人工标注

如果需要添加高质量的人工标注，直接编辑 `eval_dataset.json`：

```json
[
  {
    "query": "你的查询问题",
    "expected_chunk_ids": ["chunk_id1", "chunk_id2"],
    "expected_content_contains": ["关键词1", "关键词2"],
    "source": "manual",
    "difficulty": "hard",
    "category": "检索"
  }
]
```

> 💡 **注意**：`"source": "manual"` 标记为人工标注，自动生成数据时不会覆盖。

---

## 🔧 开发相关

### 运行筛选器单元测试

```bash
# TODO：添加筛选器测试
python -m pytest tests/evaluation/test_filter.py -v
```

### 验证存储层

```python
from tests.evaluation.storage import (
    save_per_doc_dataset,
    merge_to_global_dataset,
    load_all_datasets,
    save_eval_result,
    load_latest_eval_result,
)
```

### 使用筛选器 API

```python
from tests.evaluation.filter import apply_filters
from tests.evaluation.storage import load_all_datasets

# 加载所有数据
dataset = load_all_datasets()

# 应用筛选条件
filtered, summary = apply_filters(
    dataset,
    category="检索",
    difficulty="hard",
    sample_count=10,
)

print(summary)  # 筛选后: 10/62 条 (分类=检索, 难度=hard, 抽样=10)
```

---

## 📝 输出示例

```
============================================================
📊 知识库检索评测
============================================================
筛选后: 4/62 条 (文档=doc_abc123)
🔍 检索索引已重建: 42 个 chunks

# 知识库检索评测报告

- 评测时间: 2024-01-15 14:30:45
- 查询总数: 4
- 已标注 chunk_id 查询数: 4
- 已标注关键词查询数: 4

| 指标 | 值 | 说明 |
|------|-----|------|
| Recall@5 | 0.7500 | 期望 chunk 出现在 top-5 的比例 |
| MRR | 0.6000 | 首个命中 chunk 排名倒数的均值 |
| Keyword Recall@5 | 1.0000 | top-5 中含全部关键词的比例 |

## 按难度统计

| 难度 | 总数 | Recall@5 | 平均 MRR |
|------|------|----------|----------|
| medium | 4 | 75.00% | 0.6000 |

## 查询详情

| # | Query | Expected IDs | Keywords | Top-3 | R@5 | MRR | KW | Time |
|---|-------|-------------|----------|-------|-----|-----|-----|------|
| 1 | 如何配置... | ['chunk...'] | ['配置', '参数'] | ['chunk...'] | 1 | 1.0 | 1 | 0.1s |
| ...

## 与上次评测对比

| 指标 | 上次 | 本次 | 变化 |
|------|------|------|------|
| recall@5 | 0.7000 | 0.7500 | ↑ 5.0% |
| mrr | 0.5500 | 0.6000 | ↑ 5.0% |
| keyword_recall@5 | 1.0000 | 1.0000 | = 0.0% |

✅ 结果已保存: tests/evaluation/results/eval_result_20240115_143045.json
📄 Markdown 报告: tests/results/evaluation/eval_report.md
```

---

## 🎯 最佳实践

1. **开发阶段**：使用 `--sample 10` 快速验证
2. **修复问题后**：使用 `--failed` 只跑失败用例验证
3. **PR 合并前**：运行全量评测确保无回归
4. **发布前**：检查 `--since 7` 最近一周新增数据的效果
5. **疑难问题**：用 `--difficulty hard` 聚焦边界场景

---

## 🔄 兼容说明

- 所有旧的 `eval_dataset.json` 数据完全兼容
- pytest 运行方式保持不变
- 新增参数均为可选，不影响原有命令
- 元数据字段缺失时自动使用合理默认值

---

## 📚 相关文档

- [项目根目录 README](../../README.md)
- [检索系统架构](../core/README.md) （如有）
