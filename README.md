# kb-platform · 企业级知识库管理平台

> 权限感知的 RAG 知识库：四维数据权限 × 混合召回 × FAQ 自动沉淀 × 数据看板

![arch](https://img.shields.io/badge/arch-FastAPI%20%2B%20Vue3%20%2B%20Milvus-blue) ![tests](https://img.shields.io/badge/tests-105%20passing-brightgreen)

## 架构总览

```mermaid
graph TB
    Browser["Vue3 SPA"] -->|HTTPS| NGINX["web (nginx)<br/>静态托管+/api反代"]
    subgraph CPU ["CPU 平面 docker-compose"]
        NGINX --> BE["backend :8000<br/>认证/RBAC/知识/权限引擎"]
        BE [("MySQL 8 事实源")]
        BE [("Redis 缓存")]
        BE -.->|"SSE 代理"| AIS["ai-service :8001<br/>ModelGateway/RAG链路"]
        AIS --> MV[("Milvus<br/>kb_chunks/faq_vectors")]
    end
    AIS -.->|"HTTP+Key"| GPU["AutoDL GPU<br/>vLLM Qwen3-8B / bge-m3 / bge-reranker"]
```

详见 [docs/sad/SAD.md](docs/sad/SAD.md)（含 7 条 ADR）· [docs/sdd/SDD.md](docs/sdd/SDD.md)

## 三行启动

```bash
cp deploy/.env.example .env      # 填入你的 AutoDL 模型地址（可留空，走降级模式）
cd deploy && docker compose up -d --build
docker compose exec backend python -m app.tools.seed   # 灌入演示数据
```

打开 http://localhost:8081

## 演示账号

| 账号 | 密码 | 角色 | 可见范围 |
|------|------|------|---------|
| admin | Abc12345! | 超管 | 全部 |
| hr001 | Abc12345! | 知识管理员 | HR 制度 + 公开制度 |
| it001 | Abc12345! | 提问者(IT部) | 公开制度；HR 制度提示权限缺失 |
| fin001 | Abc12345! | 提问者(财务部) | 公开制度 + 财务制度 |

## 核心亮点

- **权限感知 RAG**：全局/部门/角色/个人四维权限（OR），召回后、重排前强制过滤，无权内容零泄露并明确提示缺失
- **混合召回**：Milvus 稠密(bge-m3) ∥ MySQL ngram 关键词并发双路，RRF 融合，关键词腿 200ms 超时熔断不拖累主链路
- **FAQ 沉淀闭环**：高频问题自动挖掘→人工审核→Redis 精确 + Milvus 语义两级缓存直答
- **生产级工程**：MySQL 为事实源/Milvus 派生可重建；LLM 主备粘性切换；模型地址全 env 化；105 个测试

## 文档导航

| 文档 | 说明 |
|------|------|
| [docs/srd/SRD.md](docs/srd/SRD.md) | 需求（34 条 FR + 验收标准） |
| [docs/sad/SAD.md](docs/sad/SAD.md) | 架构（ADR 决策记录 + 存储隔离约束） |
| [docs/sdd/SDD.md](docs/sdd/SDD.md) | 详细设计（类图/时序图/ER 图） |
| [docs/开发手册.md](docs/开发手册.md) | S0~S8 迭代计划 |
| [docs/srd/需求对齐复核.md](docs/srd/需求对齐复核.md) | 规范↔实现追溯矩阵 |
