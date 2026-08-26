# kb-platform · 企业级知识库管理平台

> **给业务方**：让每位员工身边有一位"懂规矩、守口风"的 7×24 制度专家——按部门职级管住权限，回答必须附制度原文出处。👉 [产品介绍：它能为你带来什么](docs/产品介绍.md)
>
> **给工程师**：FastAPI + Vue3 + MySQL + Redis + Milvus 微服务架构；混合召回 + 权限感知 RAG + 双级 FAQ 缓存 + 全链路 E2E 测试 + RAGAS 五指标量化评估。👉 [技术白皮书：生产级设计详解](docs/技术白皮书.md)

![tests](https://img.shields.io/badge/pytest-105%20passing-brightgreen) ![acceptance](https://img.shields.io/badge/%E9%AA%8C%E6%94%B6%E6%8E%A2%E9%92%88-28%2F28-brightgreen) ![ragas](https://img.shields.io/badge/RAGAS-%E4%BA%94%E6%8C%87%E6%A0%87%E9%87%8F%E5%8C%96-blue)

---

## ✨ 核心能力一览

| 能力 | 说明 |
|------|------|
| 🔐 **权限感知 RAG** | 全局/部门/角色/个人四维数据权限（OR 组合），在召回后强制过滤——无权内容零泄露并明确提示缺失 |
| 🔎 **混合检索** | Milvus 稠密向量 ∥ MySQL ngram 关键词双路并发，RRF 融合，关键词腿 200ms 熔断不拖累主链路 |
| 📎 **可溯源回答** | 每句回答附带制度名称与引用编号 [n]，点开即见原文 |
| ♻️ **FAQ 沉淀闭环** | 高频问题自动挖掘 → 审核发布 → Redis 精确 + Milvus 语义两级缓存秒回 |
| 📊 运营看板 | 访问量、高频问题榜、知识缺口榜、Token 成本与耗时趋势 |
| 🛡️ 生产级可靠性 | LLM 主备粘性切换、embedding 故障降级检索、Milvus 索引一键重建、105 个自动化测试 |

完整功能清单与场景化价值见 [产品介绍](docs/产品介绍.md)；
架构决策（ADR）、类图/时序图/ER 图、RAGAS 量化数据见技术文档导航。

---

## 🚀 快速开始（五步跑起来）

> 前提：已安装 **Docker Desktop**（Windows 需 WSL2）或任意 Linux + Docker Compose v2。
> AI 模型运行在独立的 GPU 服务器上（AutoDL 等），**没有 GPU 也能跑**——平台会进入降级模式，
> 除"生成回答"外的全部管理功能照常可用。

### Step 1 · 克隆仓库

```bash
git clone https://github.com/nobodycare-no/kb-platform.git
cd kb-platform
```

### Step 2 · 准备环境配置

```bash
cp deploy/.env.example .env        # Linux/macOS
# Windows PowerShell: copy deploy\.env.example .env
```

`.env` 中**必看的三组配置**：

| 配置 | 说明 |
|------|------|
| `JWT_SECRET` / `INTERNAL_TOKEN` / `DB_PASSWORD` | 生产环境必须改掉默认值 |
| `LLM_BASE_URL` / `EMBEDDING_BASE_URL` / `RERANK_URL` | GPU 推理服务地址，**留空也可启动**（走降级模式） |
| 其余检索参数 | 默认值即可跑通，调优说明见 SDD §7 |

### Step 3 · 构建前端页面

```bash
cd web
npm install --registry=https://registry.npmmirror.com
npm run build          # 产物输出到 web/dist，nginx 容器直接挂载它
cd ..
```

### Step 4 · 启动全部服务

```bash
cd deploy
docker compose up -d --build     # 共 8 个容器；首次拉取镜像请配置加速源（见文末）
docker compose ps                # 等待全部 Up(/healthy)
```

### Step 5 · 初始化演示数据并登录

```bash
docker compose exec backend python -m app.tools.seed
# 可选：GPU 服务可用时，重建真实向量索引
# docker compose exec backend python -m app.tools.reindex
```

打开 **http://localhost:8081** ，用下方账号登录。

### 演示账号

| 账号 | 密码 | 角色 | 登录后可见范围 |
|------|------|------|----------------|
| admin | Abc12345! | 超管 | 全部知识 + 用户/角色管理 |
| hr001 | Abc12345! | 知识管理员(IT示例中属HR部) | HR 制度 + 公开制度 + 知识维护 |
| it001 | Abc12345! | 提问者(IT部) | 公开制度；访问 HR 制度将收到**权限缺失提示** |
| fin001 | Abc12345! | 提问者(财务部) | 公开制度 + 财务制度 |

### 建议的体验路径（10 分钟）

1. **hr001** 登录 → 导入中心拖入几份你自己的 docx/pdf → 等待任务变绿；
2. **AI 对话**页提问刚导入的内容 → 观察流式回答与底部引用来源卡片；
3. 换 **it001** 问一个 HR 敏感问题 → 观察「权限缺失」提示卡；
4. 打开**数据看板** → 查看刚才所有问答产生的统计与排行；
5. **知识沉淀**页 → 点「执行挖掘」→ 审核一条高频问题为 FAQ → 回到对话再问一次 → 秒回。

---

## 🧪 质量验证（全部命令可复现）

```bash
# 自动化测试 105 用例
cd backend    && pytest      # 74 passed
cd ai-service && pytest      # 31 passed

# 部署栈验收探针（28 断言，需栈运行中 + GPU 在线）
python deploy/acceptance/probe.py

# RAGAS 五指标量化评估（judge=Qwen3-8B）
conda activate ragas && python deploy/ragas/run_ragas_metrics.py
```

最新结果：探针 **28/28** · RAGAS 行为命中 **18/19** · 五指标详见
[测试评估报告 §4](docs/测试评估报告.md)。

## ☁️ 部署到云服务器

完整的腾讯云/阿里云轻量服务器部署流程（含国内镜像加速、防火墙策略、HTTPS 配置、
数据迁移原理与安全红线清单）已整理为独立手册：
👉 **[deploy/云端部署指南.md](deploy/云端部署指南.md)**

## 📚 文档导航

| 文档 | 目标读者 | 内容 |
|------|---------|------|
| [产品介绍](docs/产品介绍.md) | 企业经营者 / 投资人 | 场景痛点、业务价值测算、常见问题 |
| [技术白皮书](docs/技术白皮书.md) | 技术评审 / 工程师 | 十个生产级问题与解法、选型理由、质量工程 |
| [SRD 需求文档](docs/srd/SRD.md) | 产品 / 测试 | 34 条功能需求 + 验收标准 |
| [SAD 架构文档](docs/sad/SAD.md) | 架构师 | 7 条 ADR + 存储隔离约束 |
| [SDD 详细设计](docs/sdd/SDD.md) | 开发 | 类图 / 时序图 / ER 图 / 参数表 |
| [开发手册](docs/开发手册.md) | 开发 | S0~S8 迭代切片计划 |
| [测试评估报告](docs/测试评估报告.md) | QA / 评审 | 自动化+探针+RAGAS 全量证据 |

## 🛠️ 常见问题

| 现象 | 处理 |
|------|------|
| 拉镜像超时（国内） | 配置 `/etc/docker/daemon.json` 镜像加速源后重启 docker；quay.io 镜像用 `docker.m.daocloud.io/quay.io/...` 前缀改写 |
| 页面能打开但接口 404 | backend 容器是否为最新构建：`docker compose build backend && up -d backend` |
| 问答提示"降级模式" | GPU 服务不可达，检查 `.env` 三个模型地址或开机 AutoDL |
| 导入任务停在向量化 | 同上——GPU 未就绪时 embedding 无法完成，开机后执行 reindex 补建 |
| Milvus 内存不足退出 | 单机内存 <6G 所致；可临时换 Qdrant（检索层已隔离，单文件替换） |

## License

MIT — 欢迎学习交流，商用请保留版权声明。
