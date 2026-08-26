# 软件详细设计文档（SDD）— 企业级知识库管理平台 kb-platform

| 项 | 内容 |
|----|------|
| 文档版本 | v1.0 |
| 状态 | 已评审（设计对话确认） |
| 日期 | 2026-02-26 |
| 上游文档 | docs/srd/SRD.md、docs/sad/SAD.md |

---

## 1. 代码结构与模块划分（实现后实况）

```
kb-platform/
├── backend/
│   └── app/
│       ├── main.py               # 应用工厂：路由挂载 + ApiError/422 全局处理器
│       ├── db.py                 # 引擎与会话工厂
│       ├── core/                 # config(env)、security(JWT/bcrypt)、deps(resolve_user/require_perms)、
│       │                         # errors(ApiError)、responses(统一响应包)、redis_client(共享客户端)
│       ├── models/               # SQLAlchemy ORM，按域分组：
│       │   ├── base.py           #   DeclarativeBase + TimestampMixin
│       │   ├── org.py            #   users/departments/roles/user_roles/role_permissions
│       │   ├── knowledge.py      #   knowledge_units/chunks/unit_permissions/import_tasks
│       │   ├── qa.py             #   qa_sessions/qa_access_logs
│       │   └── settlement.py     #   faqs/knowledge_gaps
│       ├── schemas/              # auth_org.py、knowledge.py（Pydantic v2）
│       ├── api/                  # auth / org / knowledge(含 check-permissions) /
│       │                         # ai(会话+SSE代理) / dashboard / settlement / health
│       ├── internal/             # 服务间端点：search/keyword、qa-logs、faq/{id}（X-Internal-Token）
│       ├── services/
│       │   ├── permission_engine.py    # 四维判定纯函数（零 IO，矩阵可测）
│       │   ├── permission_service.py   # DB 取数 + Redis watermark 快照（FR-C04）
│       │   ├── import_pipeline.py      # 解析→切片→正本→向量化编排（部分成功语义）
│       │   ├── parsers.py              # txt/md/pdf/docx 单模块实现
│       │   ├── chunker.py              # Markdown 标题感知滑窗切片
│       │   └── settlement_service.py   # FAQ 频次挖掘 / 缺口聚合 / 发布注缓存
│       └── tools/                # seed.py（幂等演示数据）· reindex.py（索引全量重建 CLI）
├── ai-service/
│   └── app/
│       ├── main.py               # 入口：health/models、internal/embed|kb/index|kb/unit|faq/upsert|
│       │                         # rag/stream(SSE)；路由内联定义，chain_ctx 惰性构建
│       ├── core/config.py        # 模型地址/协议/密钥 + Milvus/Redis + 检索参数（全 env）
│       ├── gateway/
│       │   ├── model_gateway.py  # LLM 主备粘性切换 / embed 双协议 / rerank 双协议 / health
│       │   └── milvus_store.py   # kb_chunks+faq_vectors 集合管理与读写
│       ├── retrieval/
│       │   ├── hybrid.py         # Hit + RRF 融合纯函数
│       │   └── faq_cache.py      # normalize/L1 hash/L2 语义两级缓存
│       └── chain/auth_rag.py     # 主管线：FAQ→双路召回→权限回调→重排→<think>过滤→SSE
├── web/src/{api,stores,router,views×9,directives}   # Vue3 八视图
└── deploy/{compose×2, nginx.conf, mysql/init, seed/corpus×14, ragas/, acceptance/probe.py}
```

> 与初稿差异说明：models 按域合并为 5 文件；parsers 为单模块；定时作业未接 cron
> （挖掘由 `POST /api/settlement/mine` 手动触发）；新增 tools/ 与 internal/faq 路由。

| 模块 | 职责 | 依赖 |
|------|------|------|
| backend.core | 配置/JWT/RBAC 依赖工厂/统一异常 | redis_client |
| backend.api.* | REST 端点与参数校验 | services |
| permission_engine/service | 四维判定纯函数 + 批量取数与快照缓存 | models, Redis |
| import_pipeline | 文件→chunks→向量化的状态机（pending/parsing/embedding/done/failed） | parsers, ai-service /internal/embed、/internal/kb/index |
| model_gateway | 三类模型的协议适配、重试、主备切换、连通性自检 | httpx（MockTransport 可注入） |
| hybrid / auth_rag | 双路召回 RRF 融合；鉴权问答主管线与 SSE 事件发射 | pymilvus, httpx, faq_cache |
| web.views | 九大页面区 | pinia stores |

## 2. 领域类图

```mermaid
classDiagram
    class User { +id: int; +username: str; +password_hash: str; +display_name: str; +department_id: int; +status: int }
    class Department { +id: int; +parent_id: int; +name: str; +leader_id: int }
    class Role { +id: int; +role_name: str; +role_code: str }
    class Permission { +permission_code: str; +permission_type: str }
    User "1" --> "0..*" UserRole
    Role "1" --> "0..*" UserRole
    Role "1" --> "0..*" RolePermission
    Permission "1" --> "0..*" RolePermission

    class KnowledgeUnit { +id: int; +unit_code: str; +title: str; +category: str; +status: int; +creator_id: int }
    class KnowledgeChunk { +id: int; +unit_id: int; +seq_no: int; +content: str }
    class UnitPermission { +unit_id: int; +target_type: str; +target_id: int }
    KnowledgeUnit "1" --> "1..*" KnowledgeChunk
    KnowledgeUnit "1" --> "0..*" UnitPermission

    class QaSession { +id: int; +user_id: int; +title: str }
    class QaAccessLog { +session_id: int; +question: str; +answer: str; +recalled_ids: list; +authorized_ids: list; +unauthorized_ids: list; +prompt_tokens: int; +completion_tokens: int; +response_time_ms: int }
    QaSession "1" --> "0..*" QaAccessLog

    class Faq { +question: str; +answer: str; +source_type: str; +status: str; +hit_count: int }
    class KnowledgeGap { +question_pattern: str; +ask_count: int; +status: str }

    class PermissionEngine { +snapshot(user_id) UserPermContext; +check(user_id, unit_ids) CheckResult }
    PermissionEngine ..> UnitPermission : 读取
    PermissionEngine ..> Redis : 快照缓存

    class ModelGateway { +chat_stream(messages) AsyncIterator; +embed(texts) list~vector~; +rerank(query, docs) list~score~; +health() Report }
    class HybridRetriever { +retrieve(query, top_k) CandidateSet }
    class FaqCacheService { +lookup(question) Hit|None; +publish(faq) void }
    class AuthRagChain { +run(session, question) SSEStream }
    AuthRagChain --> ModelGateway
    AuthRagChain --> HybridRetriever
    AuthRagChain --> FaqCacheService
    AuthRagChain ..> PermissionEngine : HTTP 回调
    class ImportPipeline { +submit(files) TaskId; +process(task_id) void }
    ImportPipeline --> ModelGateway : 经 ai-service /embed
    class SettlementJob { +mine_faqs() void; +refresh_gaps() void }
    SettlementJob ..> Faq : 生成候选
    SettlementJob ..> KnowledgeGap : 聚合生成
```

## 3. 数据库设计

### 3.1 ER 图

```mermaid
erDiagram
    users ||--o{ user_roles : ""
    roles ||--o{ user_roles : ""
    roles ||--o{ role_permissions : ""
    departments ||--o{ users : ""
    knowledge_units ||--o{ knowledge_chunks : ""
    knowledge_units ||--o{ unit_permissions : ""
    qa_sessions ||--o{ qa_access_logs : ""
    knowledge_units ||--o{ import_tasks : ""

    users { bigint id PK; varchar username UK; varchar password_hash; varchar display_name; bigint department_id FK; tinyint status; datetime created_at }
    departments { bigint id PK; bigint parent_id; varchar name; bigint leader_id; int sort_order }
    roles { bigint id PK; varchar role_name; varchar role_code UK }
    role_permissions { bigint id PK; bigint role_id FK; varchar permission_code; varchar permission_type }
    knowledge_units { bigint id PK; varchar unit_code UK; varchar title; text content; varchar summary; varchar category; varchar source_file_name; tinyint status; bigint creator_id FK }
    knowledge_chunks { bigint id PK; bigint unit_id FK; int seq_no; text content; char content_hash }
    unit_permissions { bigint id PK; bigint unit_id FK; varchar target_type; bigint target_id }
    qa_sessions { bigint id PK; bigint user_id FK; varchar title; datetime created_at }
    qa_access_logs { bigint id PK; bigint session_id FK; bigint user_id FK; text question; text answer; json recalled_unit_ids; json authorized_unit_ids; json unauthorized_unit_ids; int prompt_tokens; int completion_tokens; int response_time_ms; datetime created_at }
    faqs { bigint id PK; varchar question UK; text answer; varchar category; bigint related_unit_id FK; varchar source_type; varchar status; int hit_count; bigint reviewer_id }
    knowledge_gaps { bigint id PK; varchar question_pattern; json sample_questions; int ask_count; datetime last_asked_at; varchar status; bigint resolved_unit_id }
    import_tasks { bigint id PK; varchar file_name; varchar file_type; bigint size_bytes; varchar task_status; varchar error_message; bigint unit_id FK; datetime created_at }
```

### 3.2 设计要点
- `knowledge_chunks.content_hash` 用于 reindex 增量比对；`qa_access_logs.recalled/authorized/unauthorized` 三个 JSON 是审计与沉淀挖掘的数据底座；
- `faqs.question` 建唯一索引防重复发布；`knowledge_gaps.question_pattern` 为聚类代表问题；
- MySQL 8 ngram FULLTEXT：`knowledge_chunks(content)` WITH PARSER ngram，支撑关键词召回腿；
- 工程细节列（`users.is_super` 超管旁路、`import_tasks.batch_no` 批次、`qa_access_logs.faq_hit/degraded` 降级标记）以 `deploy/mysql/init/01_schema.sql` 为准。

## 4. 核心时序图

### 4.1 AI 鉴权问答（P0 主链路）

```mermaid
sequenceDiagram
    actor U as 用户
    participant FE as web(Vue)
    participant BE as backend
    participant AIS as ai-service
    participant RD as Redis
    participant MV as Milvus
    participant PE as PermissionEngine(BE内)
    participant GPU as GPU三件套

    U->>FE: 输入问题
    FE->>BE: POST /api/ai/chat/stream (JWT)
    BE->>BE: JWT校验→取用户上下文
    BE->>AIS: POST /internal/rag/stream<br/>(X-Internal-Token, user_ctx, question)
    AIS->>RD: L1 FAQ精确hash命中?
    AIS->>GPU: embed(question)
    AIS->>MV: L2 FAQ语义匹配(≥0.92)? / kb_chunks dense top50
    AIS->>BE: GET internal keyword-search top20
    AIS->>AIS: RRF融合 → 候选unit集
    AIS->>PE: POST /api/knowledge/check-permissions(user_id, unit_ids)
    PE-->>AIS: authorized[] / unauthorized[]
    AIS->>GPU: rerank(question, 授权chunks)
    AIS->>GPU: chat/completions stream (Qwen3-8B)
    loop SSE
        AIS-->>BE: delta / sources / unauthorized / done
        BE-->>FE: 同名事件透传
    end
    AIS->>BE: POST /internal/qa-logs (异步落库)
    FE->>U: 流式Markdown+引用卡片+缺失提示卡
```

### 4.2 批量导入管线

```mermaid
sequenceDiagram
    actor K as 知识管理员
    participant FE as 导入中心页
    participant BE as backend
    participant AIS as ai-service
    participant MY as MySQL
    participant MV as Milvus

    K->>FE: 拖拽多文件上传
    FE->>BE: POST /api/knowledge/import (multipart×N)
    BE->>MY: 建 import_task(每文件一条记录, status=pending)
    BE-->>FE: 返回 task_ids（立即返回）
    loop 逐文件处理
        BE->>BE: 解析(pdf/docx/md/txt)→切片(500/50)
        BE->>MY: 写 knowledge_units + knowledge_chunks(事务)
        BE->>AIS: POST /internal/embed(texts[])
        AIS-->>BE: vectors[1024]
        BE->>MV: upsert kb_chunks
        BE->>MY: 更新该文件记录 status/done_at
    end
    loop FE轮询
        FE->>BE: GET /api/knowledge/import/tasks?ids=
        BE-->>FE: 逐文件进度/成功/失败原因
    end
```

### 4.3 FAQ 挖掘与缺口识别（定时作业）

```mermaid
sequenceDiagram
    participant SCH as 挖掘作业(backend, 手动/定时)
    participant MY as MySQL
    participant AIS as ai-service
    participant RD as Redis
    participant ADM as 知识管理员

    SCH->>MY: 取近N天低置信/未命中间题(qa_access_logs)
    SCH->>AIS: 批量 embed 问题
    SCH->>SCH: 余相似度聚类(阈值0.85), 统计簇频次
    alt 簇频次≥3 且无既有FAQ
        SCH->>MY: 插入 faqs(status=pending_review, source_type=auto_mined)
    else 最高相似<0.35 或零召回
        SCH->>MY: 聚合插入/更新 knowledge_gaps(ask_count+1)
    end
    ADM->>MY: 审核通过(可编辑答案)
    ADM->>RD: 发布: 写L1 hash缓存 + faq_vectors 向量入Milvus
    Note over ADM,RD: 后续相同/相似问题直接缓存直答
```

## 5. API 设计约定

- 统一响应包 `{code:0, message:"ok", data:{...}}`；错误码分段：40xx 参数、41xx 认证/权限、50xx 服务内部；
- 分页统一 `page/page_size`，响应附 `total`；
- SSE 事件流格式：`event: delta|sources|unauthorized|done|error` + `data: {json}`；
- OpenAPI 文档由 FastAPI 自动产出（`/docs`），开发手册不重复罗列全部字段；
- 内部接口统一前缀 `/internal/*`，仅接受 X-Internal-Token。

关键端点清单（对齐规范 §2.9.8）：`POST /api/auth/login`、`GET /api/auth/me`；`GET /api/org/departments`；`GET|POST /api/org/users`、`PUT /api/org/users/{id}`；`GET /api/org/roles`、`POST /api/org/roles/{id}/permissions`；`POST /api/knowledge/import`、`GET /api/knowledge/import/tasks`；`GET|DELETE /api/knowledge/units`、`GET|PUT /api/knowledge/units/{id}`、`PUT /api/knowledge/units/{id}/permissions`；`POST /api/knowledge/check-permissions`；`POST|GET /api/ai/sessions`、`GET /api/ai/sessions/{id}/messages`、`POST /api/ai/chat/stream`(SSE)；`GET /api/dashboard/metrics|rankings/questions|rankings/units|stats/tokens`；`GET /api/settlement/faqs/recommendations|faqs/published`、`POST /api/settlement/faqs/{id}/review`、`POST /api/settlement/mine`、`GET /api/settlement/knowledge-gaps`；内部：`GET /internal/search/keyword`、`POST /internal/embed`、`POST /internal/kb/index`、`DELETE /internal/kb/unit/{unit_id}`、`POST /internal/rag/stream`、`POST /internal/qa-logs`、`GET|POST /internal/faq/*`；运维：`GET /health/models`。

## 6. 权限引擎算法

```text
snapshot(user):
    dept_ids = {user.department_id} ∪ ancestors(department_tree)   # 仅本部门，不含祖先——v1 明确为"本部门"
    role_ids = roles(user)
    cache_key = perm:snapshot:{user_id}:{updated_watermark}        # 任一授权表变更→watermark+1→快照自然失效

check(user_id, unit_ids):
    ctx = snapshot(user_id)
    for u in unit_ids:
        perms = unit_permissions(u)                     # 默认空 = 无权
        allow = global in perms
             or (∃p∈perms: p.type==department and p.target in ctx.dept_ids)
             or (∃p∈perms: p.type==role       and p.target in ctx.role_ids)
             or (∃p∈perms: p.type==user       and p.target == user_id)
        # 创建人与超管直通（写入时另行放行）
    return CheckResult(authorized=[...], unauthorized=[...])
```

判定矩阵测试用例（pytest 数据驱动）覆盖：全局开/关 × 部门命中/不命中 × 角色命中/不命中 × 个人命中/不命中 × 多实体叠加 × 默认无配置 × 超管旁路。

## 7. 检索与生成参数（全部可配，默认值）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| CHUNK_SIZE / OVERLAP | 500 / 50 | Markdown 按标题边界优先切 |
| DENSE_TOP_K / KEYWORD_TOP_K | 50 / 20 | 双路召回 |
| RRF_K | 60 | 融合常数 |
| RERANK_TOP_N | 6 | 进 Prompt 的片段数 |
| RERANK_RELEVANCE_MIN | 0.05 | 相关性门控：重排最高分低于此值短路拒答（仅拦完全无关） |
| FAQ_EXACT_SIM / GAP_SIM | 0.92 / 0.35 | 缓存直答阈值 / 缺口判定 |
| KEYWORD_TIMEOUT_MS | 200 | 关键词召回腿超时熔断；超时弃用该路并置 degraded=true |
| PERM_SNAPSHOT_TTL | 300 | 权限快照 Redis TTL（秒）；授权变更经 watermark 失效 |
| MINE_MIN_FREQ | 3 | 挖掘成候选 FAQ 的最低频次 |
| EMBED_DIM | 1024 | bge-m3 dense |
| LLM_FAIL_SWITCH | 2 | 连续失败切换备用端点次数 |
| MAX_MODEL_LEN | 8192 | vLLM 上下文上限；Prompt 总预算（系统词+6片段+历史摘要+问题）≤6500 tokens，输出预留 ≥1000 |

## 8. 配置项全表（deploy/.env.example）

```ini
# --- 基础 ---
APP_ENV=dev                      # dev | prod
MYSQL_URL=mysql+pymysql://kb:${DB_PASSWORD}@mysql:3306/kb_platform?charset=utf8mb4
REDIS_URL=redis://redis:6379/0
JWT_SECRET=change-me
INTERNAL_TOKEN=change-me-too
# --- 模型（AutoDL 双端口：6006=LLM，6008=bge-m3+reranker 同进程）---
LLM_BASE_URL=http://your-autodl-host:6006/v1
LLM_API_KEY=sk-atguigu
LLM_MODEL=qwen3-8b
LLM_MAX_CONTEXT=8192
LLM_FAIL_SWITCH=2
LLM_FALLBACK_BASE_URL=https://api.openai-compat.example/v1
LLM_FALLBACK_API_KEY=sk-yyy
LLM_FALLBACK_MODEL=gpt-5.6-luna
EMBEDDING_BASE_URL=http://your-autodl-host:6008
EMBEDDING_PROTOCOL=autodl_bge     # autodl_bge | openai
EMBEDDING_MODEL=bge-m3
RERANK_URL=http://your-autodl-host:6008/v1/rerank
RERANK_HEALTH_URL=http://your-autodl-host:6008/health
RERANK_PROTOCOL=custom            # custom={"query","documents"}->{"scores"}（AutoDL 实际协议）| tei
MILVUS_URI=http://milvus-standalone:19530
MILVUS_KB_COLLECTION=kb_chunks        # 测试可用独立命名空间隔离
MILVUS_FAQ_COLLECTION=faq_vectors
REDIS_URL=redis://redis:6379/0        # ai-service L1 缓存读取端
SEED_CORPUS_DIR=/srv/corpus           # backend 容器内语料挂载点
# --- 业务参数见 SDD §7 ---
```

## 9. 错误处理矩阵

| 环节 | 故障 | 系统行为 | 用户感知 |
|------|------|---------|---------|
| 登录 | 密码错误 | 统一模糊提示 | "用户名或密码错误" |
| 导入 | 单文件解析失败 | 该文件标 failed 记原因，其余继续 | 失败行红色标注+原因+可重试 |
| 导入 | embedding 服务不可达 | 任务暂停在 embedding 阶段并轮询重试 | 进度条停在"向量化中"，恢复后续传 |
| 问答 | embedding 故障 | 降级纯关键词检索 | 回答顶部黄色"降级模式"横幅 |
| 问答 | reranker 故障 | 按 RRF 序取 top6 | 无感知 |
| 问答 | 主 LLM 连续失败≥2 | 切备用端点 | 无感知（done 事件标注 provider） |
| 问答 | 双 LLM 均失败 | SSE error 事件 | 友好错误提示+稍后重试按钮 |
| 权限 | 召回含无权单元 | 过滤+记录 | "您缺少 N 个相关知识的访问权限"提示卡 |
| Milvus | 集合损坏/为空 | 检测后提示重建 | 管理页一键重建索引按钮 |

## 10. 测试设计与实现状态

> 实测结果与证据链详见《测试评估报告》v1.1 与 `deploy/acceptance/probe_result.json`。

| 层 | 内容 |
|----|------|
| pytest 单元 | 权限引擎判定矩阵（数据驱动 ~15 用例）；RRF 融合排序；chunker 切片边界；FAQ 归一化 hash |
| pytest 集成 | httpx + Testcontainers 风格：登录→导入 txt→mock embed→问答断言 SSE 事件序与权限过滤 |
| RAGAS | 黄金集 30 条（IT/HR/财务三部门各 10 条，含 4 条越权预期拒答样例）；指标 faithfulness / answer_relevancy / context_precision / context_recall；结果 CSV 存 deploy/ragas/，按 §7 参数做 A/B 调优记录 |
| 手工验收 | SRD §7 AC-01~08 逐项截图归档 docs/acceptance/ |
