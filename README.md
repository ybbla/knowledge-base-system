# 知识库系统 · Knowledge Base System

多格式文档入库、解析、语义抽取、混合检索平台。支持 PDF / Word / PPT / Excel / HTML / Markdown 等常见办公文档格式的智能解析与语义检索。

---

## 目录

- [架构概览](#架构概览)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 接口](#api-接口)
- [核心模块](#核心模块)
- [前端页面](#前端页面)
- [测试体系](#测试体系)
- [评测系统](#评测系统)
- [CHANGELOG](#changelog)

---

## 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│                        前端 SPA                              │
│   Vanilla JS · Router · 仪表盘/文档/搜索/入库/知识块           │
└──────────────────────────┬───────────────────────────────────┘
                           │ HTTP REST (JSON)
┌──────────────────────────▼───────────────────────────────────┐
│                     FastAPI 后端                              │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ 文档管理  │  │ 知识块管理 │  │ 混合检索  │  │ 入库任务管理 │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘ │
│       │             │             │               │         │
│  ┌────▼─────────────▼─────────────▼───────────────▼──────┐  │
│  │                    核心服务层                           │  │
│  │  ┌──────────┐  ┌──────────┐  ┌────────────────────┐  │  │
│  │  │ 解析器    │  │ 入库管道  │  │ 检索管道            │  │  │
│  │  │ (多格式)  │  │ (语义抽取) │  │ (向量+BM25+RRF)    │  │  │
│  │  └──────────┘  └──────────┘  └────────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────┬───────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
┌───────▼───────┐  ┌───────▼───────┐  ┌───────▼───────┐
│   火山引擎     │  │  Milvus/内存  │  │ PostgreSQL/内存│
│ LLM/Embedding │  │   向量索引     │  │   数据存储      │
└───────────────┘  └───────────────┘  └───────────────┘
```

**核心流程：**

```
文档上传 → 格式解析 → 语义抽取(LLM) → 知识块划分
                                         │
                                    ┌────▼────┐
                                    │ 双路索引 │
                                    └─┬───┬──┘
                              向量索引   BM25全文
                              (Faiss/   (jieba+
                              Milvus)   rank-bm25)
                                    │    │
                                    └┬──┬┘
                                    RRF 融合
                                      │
                                  LLM Rerank
                                      │
                                   最终结果
```

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **Web 框架** | FastAPI 0.115+ | 异步 REST API，自动 OpenAPI 文档 |
| **语言** | Python 3.10+ | 类型注解 `X \| None`、`list[X]` 语法 |
| **数据模型** | Pydantic v2 | 请求/响应校验，Settings 配置管理 |
| **LLM** | 火山引擎 doubao-seed-2-0-pro | 语义抽取、查询重写、Rerank |
| **Embedding** | 火山引擎 doubao-embedding-vision | 文本+视觉联合向量化 |
| **向量检索** | Faiss (内存) / Milvus 2.5 (持久) | 自动回退：Milvus 不可用时降级到 Faiss |
| **全文检索** | BM25 + jieba 分词 | rank-bm25 库，内存索引 |
| **数据库** | PostgreSQL + pgvector (可选) / 内存 | 自动回退：PG 不可用时降级到内存 |
| **对象存储** | MinIO (可选) / 本地文件系统 | 自动回退 |
| **前端** | Vanilla JS SPA | 自制路由、组件化，无框架依赖 |
| **样式** | 自定义 CSS | 思源黑体 + JetBrains Mono |
| **容器化** | Docker Compose | PostgreSQL + Milvus + MinIO + etcd + Attu |

---

## 项目结构

```
knowledge-base-system/
├── frontend/                          # 前端单页应用
│   ├── index.html                     # SPA 入口
│   ├── css/style.css                  # 全局样式 (57KB 定制设计)
│   └── js/
│       ├── api.js                     # API 客户端（封装所有后端接口）
│       ├── router.js                  # Hash 路由
│       ├── app.js                     # 应用入口，路由注册与初始化
│       └── components/
│           ├── common.js              # 公共 UI 组件（Toast/Modal/Badge/状态）
│           ├── dashboard.js           # 仪表盘页面
│           ├── documents.js           # 文档列表页面
│           ├── document-detail.js     # 文档详情页面
│           ├── search.js              # 搜索 + 调试检索页面
│           ├── ingestion.js           # 入库任务管理页面
│           └── chunks.js              # 知识块管理页面
│
├── knowledge_base_system/             # Python 后端
│   ├── app/                           # FastAPI 应用
│   │   ├── main.py                    # 应用入口，路由挂载，静态文件
│   │   ├── api/                       # API 路由
│   │   │   ├── documents.py           # 旧版文档接口 [已废弃]
│   │   │   ├── ingest.py              # 旧版入库接口 [已废弃]
│   │   │   ├── search.py              # 旧版检索接口 [已废弃]
│   │   │   ├── upload.py              # 旧版上传接口 [已废弃]
│   │   │   └── v1/                    # ✨ v1 API（当前主力）
│   │   │       ├── __init__.py        # 路由挂载与异常处理器注册
│   │   │       ├── schemas.py         # 统一响应模型 (APIResponse/Error/Pagination)
│   │   │       ├── errors.py          # 错误码与异常处理器
│   │   │       ├── services.py        # 依赖注入服务工厂
│   │   │       ├── health.py          # 健康检查 (/live /ready /dependencies)
│   │   │       ├── documents.py       # 文档 CRUD + 上传 + 入库触发
│   │   │       ├── chunks.py          # 知识块 CRUD + 批量操作 + 索引重建
│   │   │       ├── ingest.py          # 入库任务查询/重试/取消
│   │   │       └── search.py          # 混合检索 + 调试检索 + 过滤器
│   │   ├── core/                      # 核心基础设施
│   │   │   ├── config.py              # 配置管理 (pydantic-settings)
│   │   │   ├── deps.py                # 全局依赖：LLM/Embedding/索引/仓库
│   │   │   ├── models.py              # 核心数据模型
│   │   │   ├── errors.py              # 业务异常类
│   │   │   └── paths.py               # 路径工具
│   │   └── db/                        # 数据库层
│   │       ├── engine.py              # 数据库引擎（自动创建表+扩展）
│   │       ├── models.py              # SQLAlchemy ORM 模型
│   │       └── repositories/          # 仓库模式（Document/Element/Chunk）
│   │
│   ├── parsers/                       # 文档解析器
│   │   ├── base.py                    # 解析器基类 + ParsedElement 模型
│   │   ├── registry.py                # 解析器注册表（自动发现）
│   │   ├── docx_parser.py             # Word (.docx) 解析
│   │   ├── pdf_parser.py              # PDF 解析 (PyMuPDF)
│   │   ├── pptx_parser.py             # PowerPoint (.pptx) 解析
│   │   ├── xlsx_parser.py             # Excel (.xlsx) 解析
│   │   ├── html_parser.py             # HTML 解析 (BeautifulSoup)
│   │   └── markdown_parser.py         # Markdown 解析
│   │
│   ├── ingestion/                     # 入库管道
│   │   ├── pipeline.py                # 主入库流程（解析→抽取→索引→资产处理）
│   │   └── recursive_loader.py        # 递归目录加载器
│   │
│   ├── indexing/                      # 索引层
│   │   ├── base.py                    # 索引抽象基类
│   │   ├── memory_vector.py           # 内存向量索引 (Faiss)
│   │   ├── memory_bm25.py             # 内存 BM25 索引 (jieba + rank-bm25)
│   │   ├── milvus_vector.py           # Milvus 稠密向量索引
│   │   ├── milvus_sparse.py           # Milvus 稀疏向量索引 (BM25)
│   │   ├── milvus_hybrid.py           # Milvus 混合检索
│   │   └── fusion.py                  # RRF 融合算法
│   │
│   ├── retrieval/                     # 检索管道
│   │   └── pipeline.py                # 完整检索流程（重写→双路召回→融合→Rerank）
│   │
│   ├── llm/                           # LLM 客户端
│   │   ├── volcengine_client.py       # 火山引擎 SDK 封装（chat/embed/vision）
│   │   ├── prompts.py                 # 提示词模板（语义抽取/筛选/摘要）
│   │   ├── semantic_extractor.py      # 语义知识块抽取器
│   │   ├── query_rewriter.py          # 查询重写器
│   │   └── reranker.py                # 结果重排序器
│   │
│   ├── assets/                        # 资产处理
│   │   ├── base.py                    # 资产存储抽象
│   │   ├── memory_store.py            # 本地文件存储
│   │   ├── minio_store.py             # MinIO 对象存储
│   │   └── image_processor.py         # 图片视觉理解 (LLM Vision)
│   │
│   ├── tests/                         # 测试套件
│   │   ├── conftest.py                # 测试配置与 Fixtures
│   │   ├── test_models.py             # 数据模型单元测试 (38KB)
│   │   ├── test_db_models.py          # 数据库模型测试 (35KB)
│   │   ├── test_api_contracts.py      # API 契约测试
│   │   ├── test_v1_*.py               # v1 API 接口测试
│   │   ├── test_*_parser.py           # 各格式解析器测试
│   │   ├── test_ingestion_*.py        # 入库流程测试
│   │   ├── test_search_pipeline.py    # 检索管道测试
│   │   ├── evaluation/                # 评测系统
│   │   │   ├── dataset.py             # 数据集加载
│   │   │   ├── gen_dataset.py         # 自动生成评测数据集
│   │   │   ├── filter.py              # 多维度筛选器
│   │   │   ├── metrics.py             # 评测指标 (Recall/Precision/MRR/NDCG)
│   │   │   ├── storage.py             # 结果持久化
│   │   │   ├── tune_params.py         # 参数调优
│   │   │   ├── eval_dataset.json      # 评测数据集 (15KB)
│   │   │   ├── datasets/              # 多版本数据集
│   │   │   ├── results/               # 评测结果
│   │   │   └── test_*.py              # 评测系统测试
│   │   ├── integration/               # 集成测试
│   │   └── integration_mock/          # Mock 集成测试
│   │
│   ├── requirements.txt               # Python 依赖
│   └── .env                           # 环境变量配置
│
├── docs/                              # 文档
│   └── API接口汇总.md                  # 全部 36 个 API 接口说明
│
├── data/                              # 数据目录
│   ├── source_documents/              # 原始文档
│   ├── uploads/                       # 上传文件存储
│   └── simulated_inputs/              # 模拟输入
│
├── docker-compose.yml                 # Docker 服务编排
├── openspec/                          # 变更规范与设计文档
├── AGENTS.md                          # AI Agent 配置
└── CLAUDE.md                          # Claude 项目配置
```

---

## 快速开始

### 环境要求

- Python 3.10+
- Docker & Docker Compose（用于 PostgreSQL / Milvus / MinIO）
- 火山引擎 API Key（LLM 和 Embedding 服务）

### 1. 克隆项目

```bash
git clone <repo-url>
cd knowledge-base-system
```

### 2. 创建虚拟环境并安装依赖

```bash
python -m venv venv
source venv/bin/activate   # Linux/macOS
# 或 venv\Scripts\activate  (Windows)

pip install -r knowledge_base_system/requirements.txt
```

### 3. 配置环境变量

编辑 `knowledge_base_system/.env`，填入火山引擎 API Key：

```env
VOLCENGINE_API_KEY=your-api-key-here
```

### 4. 启动基础服务（可选）

```bash
# 启动 PostgreSQL + Milvus + MinIO（需要 Docker）
docker compose up -d
```

> **Docker 服务端口映射：**
>
> | 服务 | 端口 | 说明 |
> |------|------|------|
> | PostgreSQL | `5432` | 关系数据库 |
> | MinIO API | `9000` | 对象存储 |
> | MinIO Console | `9001` | MinIO Web 管理 |
> | Milvus | `19530` | 向量数据库 |
> | Attu | `8001` | Milvus Web 管理界面 |

> **注意**：后端默认自动尝试连接外部服务，不可用时自动回退到内存/本地存储。因此 Docker 服务是可选的，直接运行也能正常工作。

### 5. 启动应用

```bash
cd knowledge_base_system
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. 访问系统

- **前端界面**：http://localhost:8000
- **API 文档 (Swagger)**：http://localhost:8000/docs
- **API 文档 (ReDoc)**：http://localhost:8000/redoc
- **Milvus 管理 (Attu)**：http://localhost:8001（如果启动了 Attu）

---

## 配置说明

所有配置项通过环境变量或 `.env` 文件设置，支持运行时热刷新。

### 核心配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VOLCENGINE_API_KEY` | — | 火山引擎 API Key（**必填**） |
| `VOLCENGINE_LLM_MODEL` | `doubao-seed-2-0-pro` | LLM 模型 |
| `VOLCENGINE_EMBEDDING_MODEL` | `doubao-embedding-vision` | Embedding 模型 |

### 后端模式

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BACKEND` | `postgres` | 设为 `memory` 强制使用内存存储 |
| `DATABASE_URL` | `postgresql://kbuser:kbpass@localhost:5432/knowledge_base` | PostgreSQL 连接串 |

### Milvus 向量检索

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MILVUS_ENABLED` | `true` | 启用 Milvus（不可用时自动回退内存） |
| `MILVUS_HOST` | `localhost` | Milvus 主机 |
| `MILVUS_PORT` | `19530` | Milvus 端口 |

### MinIO 对象存储

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MINIO_ENABLED` | `true` | 启用 MinIO（不可用时自动回退本地） |
| `MINIO_ENDPOINT` | `localhost:9000` | MinIO 地址 |
| `MINIO_ACCESS_KEY` | `minioadmin` | 访问密钥 |
| `MINIO_SECRET_KEY` | `minioadmin` | 秘密密钥 |

### 检索参数

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VECTOR_TOP_K` | `50` | 向量召回候选数 |
| `BM25_TOP_K` | `50` | BM25 召回候选数 |
| `FUSION_TOP_K` | `20` | RRF 融合后保留数 |
| `FINAL_TOP_K` | `5` | 最终返回数 |
| `RRF_K` | `60` | RRF 平滑因子 |

### 入库限制

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EMBEDDING_BATCH_SIZE` | `32` | Embedding 批处理大小 |
| `INDEX_UPSERT_BATCH_SIZE` | `100` | 索引批量写入大小 |
| `MAX_ASSET_SIZE_MB` | `100` | 单资源最大体积 |
| `MAX_ASSETS_PER_DOC` | `100` | 单文档最多资源数 |

---

## API 接口

系统提供 **28 个活跃 v1 API** + 8 个兼容旧版接口，所有 `/api/v1` 接口返回统一的 `{ data, meta, error }` 结构。

### 接口速览

| 分组 | 方法 | 路径 | 功能 |
|------|------|------|------|
| **健康检查** | `GET` | `/api/v1/health/live` | 进程存活检查 |
| | `GET` | `/api/v1/health/ready` | 核心依赖就绪检查 |
| | `GET` | `/api/v1/health/dependencies` | 依赖状态详情 |
| **文档管理** | `GET` | `/api/v1/documents` | 文档分页列表 |
| | `POST` | `/api/v1/documents` | 创建文档 |
| | `POST` | `/api/v1/documents/upload` | 上传文件并创建文档 |
| | `GET` | `/api/v1/documents/{id}` | 文档详情 |
| | `GET` | `/api/v1/documents/{id}/elements` | 文档解析元素 |
| | `PATCH` | `/api/v1/documents/{id}` | 更新文档（乐观锁） |
| | `DELETE` | `/api/v1/documents/{id}` | 软删除文档 |
| | `POST` | `/api/v1/documents/{id}/restore` | 恢复文档 |
| | `POST` | `/api/v1/documents/{id}/ingest` | 触发入库 |
| **知识块** | `GET` | `/api/v1/chunks` | 知识块分页列表 |
| | `POST` | `/api/v1/chunks` | 创建知识块 |
| | `GET` | `/api/v1/chunks/{id}` | 知识块详情 |
| | `PATCH` | `/api/v1/chunks/{id}` | 更新知识块 |
| | `DELETE` | `/api/v1/chunks/{id}` | 软删除知识块 |
| | `POST` | `/api/v1/chunks/{id}/restore` | 恢复知识块 |
| | `POST` | `/api/v1/chunks/{id}/reindex` | 重建索引 |
| | `POST` | `/api/v1/chunks/batch/reindex` | 批量重建索引 |
| | `POST` | `/api/v1/chunks/batch` | 批量状态操作 |
| **检索** | `POST` | `/api/v1/search` | 标准混合检索 |
| | `POST` | `/api/v1/search/debug` | 调试检索 |
| | `GET` | `/api/v1/search/filters` | 可用筛选项 |
| **入库任务** | `GET` | `/api/v1/ingest/jobs` | 任务分页列表 |
| | `GET` | `/api/v1/ingest/jobs/{id}` | 任务详情 |
| | `POST` | `/api/v1/ingest/jobs/{id}/retry` | 重试失败任务 |
| | `POST` | `/api/v1/ingest/jobs/{id}/cancel` | 取消等待中任务 |

详细接口文档见 [docs/API接口汇总.md](docs/API接口汇总.md)。

### 统一错误响应

```json
{
  "data": null,
  "meta": {},
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "文档 xxx 不存在",
    "details": null
  }
}
```

错误码：`DOCUMENT_NOT_FOUND` | `DOCUMENT_DUPLICATE` | `DOCUMENT_VERSION_CONFLICT` | `CHUNK_NOT_FOUND` | `INGEST_JOB_NOT_FOUND` | `INGEST_JOB_CONFLICT` | `VALIDATION_ERROR` | `INTERNAL_ERROR` | `SERVICE_UNAVAILABLE`

---

## 核心模块

### 文档解析器 (parsers/)

支持 6 种文档格式的结构化解析，统一输出 `ParsedElement` 模型：

| 解析器 | 支持格式 | 核心能力 |
|--------|----------|----------|
| `pdf_parser.py` | PDF | 文本提取、表格检测、图片抽取、层级标题 |
| `docx_parser.py` | Word | 段落/表格/图片提取，样式识别 |
| `pptx_parser.py` | PowerPoint | 幻灯片文本、备注、图片、表格 |
| `xlsx_parser.py` | Excel | 工作表遍历、合并单元格、表格结构化 |
| `html_parser.py` | HTML | DOM 解析、标签过滤、语义区块划分 |
| `markdown_parser.py` | Markdown | 标题层级、代码块、表格、图片引用 |

所有解析器通过 `registry.py` 自动注册，按文件扩展名和内容类型匹配。

### 入库管道 (ingestion/pipeline.py)

```
                    文档
                     │
              ┌──────▼──────┐
              │  格式解析    │  → ParsedElement[]
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │  语义抽取    │  → LLM 知识块划分 + 摘要
              └──────┬──────┘
                     │
         ┌───────────┼───────────┐
         │           │           │
   ┌─────▼─────┐ ┌──▼───┐ ┌─────▼─────┐
   │ 向量索引    │ │ BM25 │ │ 资产处理   │
   │ (Embedding)│ │ 索引  │ │ (图片Vision)│
   └───────────┘ └──────┘ └───────────┘
```

支持两种入库模式：
- **`force`**：完整入库流程，重建全部知识块和索引
- **`incremental`**：增量更新，仅更新变化部分并替换旧索引

### 索引层 (indexing/)

双路索引架构，支持内存和 Milvus 两种后端：

| 组件 | 内存模式 | Milvus 模式 |
|------|----------|-------------|
| 向量索引 | `memory_vector.py` (Faiss) | `milvus_vector.py` |
| BM25 索引 | `memory_bm25.py` (jieba+rank-bm25) | `milvus_sparse.py` |
| 混合检索 | — | `milvus_hybrid.py` |
| 融合算法 | `fusion.py` (RRF) | `fusion.py` (RRF) |

后端自动切换：优先尝试 Milvus，连接失败时自动降级到内存索引。

### 检索管道 (retrieval/pipeline.py)

```
用户查询
   │
┌──▼──────────┐
│  查询重写    │  → LLM 优化查询表达
└──┬──────────┘
   │
┌──▼──────────┐
│  双路召回    │  → 向量 (top_k=50) + BM25 (top_k=50)
└──┬──────────┘
   │
┌──▼──────────┐
│  RRF 融合   │  → 取 Top 20
└──┬──────────┘
   │
┌──▼──────────┐
│  LLM Rerank │  → 最终排序 Top 5
└──┬──────────┘
   │
   最终结果（含评分明细、高亮片段）
```

调试模式 (`/api/v1/search/debug`) 额外返回每阶段候选列表和评分详情。

### LLM 客户端 (llm/)

- **volcengine_client.py** — 火山引擎 SDK 封装，支持 `chat_json()` 自动重试与 JSON 提取、Embedding 批量向量化、视觉理解
- **semantic_extractor.py** — 将解析元素智能划分为语义知识块，生成标题和摘要
- **prompts.py** — 集中管理所有 LLM 提示词模板
- **query_rewriter.py** — 将用户查询重写为更精确的检索表达
- **reranker.py** — 对融合结果进行深度语义重排序

---

## 前端页面

前端为纯 Vanilla JS 单页应用，无框架依赖。采用 Hash 路由、组件化架构。

| 页面 | 路由 | 组件 | 功能 |
|------|------|------|------|
| 仪表盘 | `/` | `dashboard.js` | 系统概览、服务状态、快捷入口 |
| 文档列表 | `/documents` | `documents.js` | 文档分页浏览、上传、筛选、批量操作 |
| 文档详情 | `/documents/:id` | `document-detail.js` | 文档信息、解析元素、知识块列表 |
| 搜索 | `/search` | `search.js` | 混合检索、筛选、结果高亮 |
| 调试检索 | `/search-debug` | `search.js` | 检索各阶段可视化调试 |
| 入库任务 | `/ingestion` | `ingestion.js` | 任务状态监控、重试、取消 |
| 知识块 | `/chunks` | `chunks.js` | 知识块浏览、创建、编辑、索引管理 |

**设计系统**：自定义 CSS 设计语言（57KB），包括色彩体系、间距系统、组件样式（卡片/表格/按钮/Badge/Toast/Modal/Spinner）、响应式布局。

---

## 测试体系

测试覆盖后端各模块，使用 pytest 框架。

### 运行测试

```bash
# 运行全部测试
cd knowledge_base_system
pytest tests/ -v

# 运行单模块测试
pytest tests/evaluation/test_evaluation.py -v

# 运行 v1 API 测试
pytest tests/test_v1_*.py -v

# 运行集成测试
pytest tests/integration/ -v
```

### 测试分类

| 类别 | 文件 | 说明 |
|------|------|------|
| **数据模型** | `test_models.py` (38KB) | 核心 Pydantic 模型全覆盖测试 |
| **数据库模型** | `test_db_models.py` (35KB) | SQLAlchemy ORM 模型 + 仓库测试 |
| **解析器** | `test_*_parser.py` | 各格式解析器独立测试 |
| **入库管道** | `test_ingestion_*.py` | 入库流程端到端测试 |
| **检索** | `test_search_pipeline.py` | 检索管道单元与集成测试 |
| **v1 API** | `test_v1_*.py` | v1 接口契约/功能/端到端测试 |
| **API 契约** | `test_api_contracts.py` | 旧版接口兼容性测试 |
| **集成测试** | `integration/` | 多模块协作测试 |
| **评测系统** | `evaluation/test_*.py` | 评测框架自测试 |

---

## 评测系统

内置于 `tests/evaluation/` 的完整检索质量评测框架。

### 核心能力

- **数据集管理** — 支持多版本数据集，版本化存储与加载
- **自动生成** — 基于文档自动生成评测查询（LLM 生成 + 规则增强）
- **多维度筛选** — 按类别、知识类型、文档来源、难度等维度筛选评测子集
- **多指标评估** — Recall@K、Precision@K、MRR、NDCG@K
- **参数调优** — 自动化搜索最优检索参数组合
- **结果持久化** — 评测结果版本化存储，支持历史对比

### 快速使用

```bash
cd knowledge_base_system

# 生成评测数据集
python -m tests.evaluation.gen_dataset

# 运行评测
python -m tests.evaluation.test_evaluation

# 参数调优
python -m tests.evaluation.tune_params
```

详细说明见 [tests/evaluation/README.md](knowledge_base_system/tests/evaluation/README.md)。

---

## CHANGELOG

### v0.3.0 (当前)

- ✅ 完成 API v1 完整迁移（28 个活跃接口）
- ✅ 评测数据集自动生成与多维度筛选系统
- ✅ 检索 Debug 模式（各阶段候选可视化）
- ✅ 多模态视觉理解（PDF/PPTX 图片 LLM Vision 描述）
- ✅ 增量入库与乐观锁并发控制
- ✅ 文档去重检测与软删除/恢复
- ✅ 知识块批量操作与索引管理
- ✅ 前端全页面 v1 接口切换

### v0.2.0

- ✅ 混合检索（向量 + BM25 + RRF + LLM Rerank）
- ✅ 多格式文档解析（PDF/DOCX/PPTX/XLSX/HTML/Markdown）
- ✅ Milvus 向量检索 + MinIO 对象存储
- ✅ PostgreSQL 持久化支持

### v0.1.0

- ✅ FastAPI 基础框架
- ✅ 火山引擎 LLM/Embedding 集成
- ✅ 内存向量索引 + BM25 全文检索
- ✅ 文档上传与解析入库基础流程

---

## 许可证

内部项目，未开源。

---

## 相关文档

- [API 接口汇总](docs/API接口汇总.md) — 全部 36 个 API 详细说明
- [项目结构与调用关系分析](项目结构与调用关系分析.md)
- [数据模型字段审计报告](数据模型字段审计报告.md)
- [API 接口审计报告](API接口审计报告.md)
- [全栈生产测试计划](全栈生产测试计划.md)
- [接口改进计划](接口改进计划.md)
- [知识库开发文档](KNOWLEDGE_BASE_DEVELOPMENT.md)
- [评测系统 README](knowledge_base_system/tests/evaluation/README.md)
