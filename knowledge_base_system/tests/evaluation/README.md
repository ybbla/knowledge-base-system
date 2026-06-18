# 📊 知识库检索评测体系

评测数据自动生成、多维度筛选、检索质量评测、参数调优的完整体系。

## ✨ 功能特性

- 🚀 **LLM 自动生成评测数据**：文档入库后后台异步触发，自动生成多样化查询和标注
- ✅ **标注合法性校验**：自动校验 chunk_id 存在性和关键词匹配，过滤 LLM 编造的内容
- 🔍 **多维度筛选**：支持 8 种筛选维度的任意组合，灵活选择评测范围
- 📈 **评测执行与报告**：独立脚本 + pytest 双模式，自动生成 Markdown 报告和历史对比
- 📁 **自动生成与人工标注物理隔离**：自动生成写入 `datasets/`，人工标注在 `eval_dataset.json`，清晰分离
- ⚙️ **参数调优**：网格搜索 VECTOR_TOP_K / BM25_TOP_K / RRF_K 等参数，自动找出最优组合
- 🛡️ **人工标注保护**：`source: "manual"` 的条目在合并时不会被自动生成数据覆盖
- 💯 **100% 向后兼容**：旧格式数据集缺失字段自动使用合理默认值

---

## 🚀 快速开始

### 1. 生成评测数据

```bash
cd knowledge_base_system

# 从全部知识块自动生成（每个 chunk 3 条，上限 50 条）
python tests/evaluation/gen_dataset.py

# 从指定分类生成
python tests/evaluation/gen_dataset.py --category 技术文档

# 预览模式：不调用 LLM，仅查看输入内容
python tests/evaluation/gen_dataset.py --dry-run
```

### 2. 运行评测

```bash
# 全量评测（独立脚本，推荐）
python tests/evaluation/test_evaluation.py

# pytest 模式
python -m pytest tests/evaluation/test_evaluation.py -v

# 快速抽样 10 条验证
python tests/evaluation/test_evaluation.py --sample 10

# 只跑上次失败的（回归验证）
python tests/evaluation/test_evaluation.py --failed
```

### 3. 参数调优

```bash
python tests/evaluation/tune_params.py
```

---

## 📖 命令行参数

### test_evaluation.py 筛选参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--doc-id <id>` | 按文档 ID 筛选 | `--doc-id doc_abc123` |
| `--category <name>` | 按业务分类筛选 | `--category 检索` |
| `--difficulty <level>` | 按难度筛选：easy / medium / hard | `--difficulty hard` |
| `--source <type>` | 按来源筛选：auto / manual | `--source manual` |
| `--since <days>` | 只评测最近 N 天新增数据 | `--since 7` |
| `--query <keyword>` | 按查询关键词模糊匹配 | `--query 并发` |
| `--sample <N>` | 随机抽样 N 条 | `--sample 20` |
| `--failed` | 只跑上次失败的用例 | `--failed` |

### test_evaluation.py 输出参数

| 参数 | 说明 |
|------|------|
| `--dataset <path>` | 指定评测数据集文件 |
| `--output <path>` | 指定结果输出路径 |
| `--no-save` | 不保存评测结果 |
| `--no-compare` | 不与上次结果对比 |
| `--verbose, -v` | 显示每条查询详情 |

### gen_dataset.py 参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--category <name>` | 按分类过滤知识块 | `--category 技术文档` |
| `--count <N>` | 目标查询数（0=自动：每 chunk 3 条，上限 50） | `--count 30` |
| `--output <path>` | 输出文件路径（默认写入 `datasets/manual_gen_{timestamp}.json`） | `--output eval_new.json` |
| `--dry-run` | 预览模式：仅打印 LLM 输入 | `--dry-run` |

---

## 💡 使用示例

### 开发验证常用

```bash
# 快速抽样 10 条验证代码改动
python tests/evaluation/test_evaluation.py --sample 10

# 只跑上次失败的（验证修复效果）
python tests/evaluation/test_evaluation.py --failed

# 只评测最近一周新增的数据
python tests/evaluation/test_evaluation.py --since 7
```

### 聚焦特定领域

```bash
# 只评测检索相关的困难用例
python tests/evaluation/test_evaluation.py --category 检索 --difficulty hard

# 组合使用：最近一周、中等难度、包含"并发"关键词
python tests/evaluation/test_evaluation.py --since 7 --difficulty medium --query 并发
```

---

## 🏗️ 核心模块

### 1. 数据模型 — `dataset.py`

```python
@dataclass
class EvalItem:
    query: str                                    # 用户查询
    expected_chunk_ids: list[str]                 # 期望命中的 chunk
    expected_content_contains: list[str]          # 期望包含的关键词

    # 筛选元数据（可选，缺失时为 None / 默认值）
    source_doc_id: str | None = None
    source_doc_title: str | None = None
    category: str | None = None
    difficulty: str = "medium"                    # easy / medium / hard
    source: str = "auto"                          # auto / manual
    generated_at: str | None = None

    # 运行时字段
    _last_passed: bool | None = None               # 仅供 --failed 筛选使用
```

- `EvalItem.from_dict(data)` — 从字典创建，缺失字段自动填充默认值
- `load_dataset(path)` — 从 JSON 文件加载并校验

### 2. 自动生成 — `gen_dataset.py`

```
chunk_store 读取知识块
    ↓
LLM 生成多样化查询 + chunk 标注 + 关键词
    ↓
_validate_annotations() 校验
  ├── chunk_id 是否存在于输入中（防止 LLM 编造）
  └── 关键词是否在对应 chunk 正文中
    ↓
save_per_doc_dataset() 写入 datasets/ 目录（不合并到全局）
```

**LLM Prompt 策略**：覆盖直接询问、口语化询问、模糊询问三种角度；每个查询标注 1-2 个 chunk_id + 3-5 个关键词；单次最多送入 40 个 chunk。

**入库集成**：`IngestionPipeline._trigger_eval_data_generation()` 在入库完成后异步调用 `generate_for_chunks()`：

```python
from tests.evaluation.gen_dataset import generate_for_chunks

items, errors = generate_for_chunks(
    chunks=[{"chunk_id": "chunk_1", "title": "...", "content": "..."}, ...],
    doc_id="doc_abc123",
    doc_title="知识库使用指南",
    query_count=4,
)
```

### 3. 多维度筛选 — `filter.py`

8 种筛选维度，支持任意组合：

| 维度 | 字段 | 说明 |
|------|------|------|
| 文档 | `doc_id` | 精确匹配 `source_doc_id` |
| 分类 | `category` | 精确匹配 |
| 难度 | `difficulty` | `easy` / `medium` / `hard` |
| 来源 | `source` | `auto`（自动生成）/ `manual`（人工标注） |
| 时间 | `since_days` | 只保留最近 N 天生成的条目 |
| 关键词 | `query_keyword` | 模糊匹配 query 文本（大小写不敏感） |
| 抽样 | `sample_count` | 随机抽取 N 条 |
| 失败回归 | `only_failed` | 读取 `results/latest.json`，筛选上次 Recall@5/MRR/KW Recall 任一为 0 的条目 |

```python
from tests.evaluation.filter import FilterCriteria, DatasetFilter, apply_filters

# 便捷函数
filtered, summary = apply_filters(dataset, category="检索", difficulty="hard", sample_count=10)

# DatasetFilter 类（逐步构建，更灵活）
ds_filter = DatasetFilter(FilterCriteria(doc_id="doc_001", since_days=7, only_failed=True))
ds_filter.load_last_failed(dataset)
result = ds_filter.apply(dataset)
```

### 4. 存储层 — `storage.py`

自动生成与人工标注**物理隔离**：

| 位置 | 写入者 | 内容 |
|------|--------|------|
| `datasets/doc_{id}_{date}.json` | 入库流程 / CLI 手动生成 | 自动生成的评测数据 |
| `eval_dataset.json` | 人手编辑 | 人工标注的评测数据 |
| `results/eval_result_{timestamp}.json` | 评测脚本 | 每次评测的结果快照 |
| `results/latest.json` | 评测脚本 | 最新评测结果快捷方式 |

`load_all_datasets()` 从 `eval_dataset.json` + `datasets/*.json` 两个来源合并加载，自动去重：
- 先加载 `eval_dataset.json`（人工标注，优先级高）
- 再从 `datasets/` 补充不重复的自动生成数据
- 按 query 文本去重，人工标注优先保留

核心 API：`save_per_doc_dataset()` / `merge_to_global_dataset()` / `save_eval_result()` / `load_all_datasets()` / `load_latest_eval_result()`

> `merge_to_global_dataset()` 保留为手动操作 API——仅在确认自动生成数据质量后，手动调用以将精选条目合并到 `eval_dataset.json`。

### 5. 评测指标 — `metrics.py`

| 函数 | 说明 |
|------|------|
| `recall_at_k(results, expected, k=5)` | 期望 chunk 出现在 top-k 中则返回 1.0 |
| `mrr(results, expected)` | 首个命中 chunk 排名倒数的均值 |
| `recall_by_keywords(contents, keywords, k=5)` | top-k 中是否包含全部关键词 |
| `safe_mean(values)` | 忽略 None 计算均值 |

### 6. 评测执行 — `test_evaluation.py`

- `run_evaluation(search_fn, dataset)` — 遍历数据集逐条查询，计算三项指标，返回结构化结果
- `_build_markdown_report(result)` — 生成 Markdown 报告（按难度/分类分维度统计）
- `_build_comparison_report(metrics)` — 与 `latest.json` 对比，输出指标变化
- `TestEvaluation` — pytest 集成类，支持通过 `conftest.py` 传入命令行参数
- `main()` — 独立运行入口，含完整的 argparse CLI

### 7. 参数调优 — `tune_params.py`

对 VECTOR_TOP_K、BM25_TOP_K、FUSION_TOP_K、RRF_K 进行网格搜索：

| 参数 | 候选值 |
|------|--------|
| `VECTOR_TOP_K` | 20, 50, 80 |
| `BM25_TOP_K` | 20, 50, 80 |
| `FUSION_TOP_K` | 10, 20, 40 |
| `RRF_K` | 30, 60, 90 |

同时在 Milvus 混合检索和应用层 RRF fallback 两种模式下运行。默认启用快速模式（`EVAL_FAST_RETRIEVAL=1`），跳过 LLM rewrite/rerank。结果输出到 `tests/results/evaluation/tune_params.json`。

---

## ⚙️ 配置选项

```env
# 是否启用入库自动生成评测数据（默认 true）
AUTO_EVAL_ENABLED=true

# 每个文档生成的查询数量（默认 4）
AUTO_EVAL_QUERIES_PER_DOC=4
```

```python
from app.core.config import settings
print(settings.auto_eval_enabled)        # True
print(settings.auto_eval_queries_per_doc) # 4
```

---

## 📁 目录结构

```
tests/evaluation/
├── README.md                      # 本文档
├── __init__.py                    # 包初始化
│
├── dataset.py                     # 数据模型 (EvalItem) + 加载器
├── gen_dataset.py                 # LLM 驱动评测数据自动生成 + 标注校验
├── filter.py                      # 8 维度筛选器 (FilterCriteria / DatasetFilter)
├── storage.py                     # 存储封装（自动生成 → datasets/，人工标注 → eval_dataset.json）
├── metrics.py                     # 评测指标计算 (recall@5 / mrr / keyword_recall)
├── test_evaluation.py             # 评测执行入口（pytest + 独立脚本）
├── tune_params.py                 # 检索参数网格搜索
│
├── test_filter.py                 # 筛选器单元测试
├── test_storage.py                # 存储层单元测试
├── test_gen_dataset.py            # 数据生成单元测试
├── test_evaluation_integration.py # 集成测试（CLI / 兼容性 / 入库流程）
│
├── eval_dataset.json              # 人工标注评测数据集（手动编辑）
├── datasets/                      # 自动生成评测数据目录（入库 / CLI 生成，加载时自动合并）
│   └── doc_{id}_{date}.json
└── results/                       # 评测结果目录
    ├── latest.json
    └── eval_result_{timestamp}.json
```

结果输出：
- Markdown 报告 → `tests/results/evaluation/eval_report.md`
- 参数调优结果 → `tests/results/evaluation/tune_params.json`

---

## 🧪 添加人工标注

直接编辑 `eval_dataset.json`：

```json
[
  {
    "query": "你的查询问题",
    "expected_chunk_ids": ["chunk_id1", "chunk_id2"],
    "expected_content_contains": ["关键词1", "关键词2"],
    "source_doc_id": "doc_abc123",
    "source_doc_title": "相关文档标题",
    "category": "检索",
    "difficulty": "hard",
    "source": "manual",
    "generated_at": "2024-01-15T12:00:00"
  }
]
```

> 💡 `"source": "manual"` 是关键——自动合并时已存在的条目不会被覆盖，人工修正永远保留。只需 `query` + 至少一个标注维度即可成为有效条目，所有元数据字段均为可选。

---

## 🧪 测试

```bash
# 运行全部评测体系测试
python -m pytest tests/evaluation/ -v

# 按模块运行
python -m pytest tests/evaluation/test_filter.py -v
python -m pytest tests/evaluation/test_storage.py -v
python -m pytest tests/evaluation/test_gen_dataset.py -v
python -m pytest tests/evaluation/test_evaluation_integration.py -v
```

| 测试文件 | 覆盖内容 |
|----------|----------|
| `test_filter.py` | FilterCriteria 默认值、8 种筛选条件各自和组合、失败标记加载、空数据集 |
| `test_storage.py` | 分文档保存结构、合并去重、人工标注保护、结果持久化及 latest.json 更新 |
| `test_gen_dataset.py` | chunk_id / 关键词校验、各种边界情况、LLM prompt 格式 |
| `test_evaluation_integration.py` | CLI --help 输出、新旧格式兼容、混合格式加载、评测结果读写、入库流程集成 |

---

## 📝 评测报告示例

```
============================================================
📊 知识库检索评测
============================================================
筛选后: 4/62 条 (文档=doc_abc123)
🔍 检索索引已重建: 42 个 chunks

# 知识库检索评测报告
- 查询总数: 4
- 已标注 chunk_id 查询数: 4
- 已标注关键词查询数: 4

## 核心指标
| 指标 | 值 | 说明 |
|------|-----|------|
| Recall@5 | 0.7500 | 期望 chunk 出现在 top-5 的比例 |
| MRR | 0.6000 | 首个命中 chunk 排名倒数的均值 |
| Keyword Recall@5 | 1.0000 | top-5 中含全部关键词的比例 |

## 与上次评测对比
| 指标 | 上次 | 本次 | 变化 |
|------|------|------|------|
| recall@5 | 0.7000 | 0.7500 | ↑ 5.0% |
| mrr | 0.5500 | 0.6000 | ↑ 5.0% |

✅ 结果已保存: tests/evaluation/results/eval_result_20240115_143045.json
```

---

## 🎯 最佳实践

1. **开发阶段**：`--sample 10` 快速验证
2. **修复问题后**：`--failed` 只跑失败用例
3. **参数调优**：修改检索配置后运行 `tune_params.py`
4. **PR 合并前**：全量评测确保无回归
5. **发布前**：`--since 7` 检查最近一周新增数据
6. **疑难问题**：`--difficulty hard` 聚焦边界场景

---

## 🔄 兼容说明

- 旧格式数据完全兼容：`EvalItem.from_dict()` 对缺失字段自动填充默认值
- pytest 运行方式和原有命令行参数保持不变
- 自动生成数据不写入 `eval_dataset.json`，人工标注数据不会被覆盖
- `load_all_datasets()` 从两个来源合并加载，人工标注优先

---

## 📚 相关文档

- [项目根目录 README](../../../README.md)
- [API v1 接口文档](../../../docs/API接口汇总.md)
