# 运行、配置与 API

## 本地运行

```powershell
python -m pip install -e ".[dev]"
python -m shopdesk serve
```

默认 http://127.0.0.1:8010，Swagger 位于 /docs。程序只读取工作目录下 .env，终端环境变量优先。CLI 全局 --home 可指定其他工作目录。

默认配置运行虚构翡翠店铺，知识和页面均打入 wheel。安装 wheel 后也可从新目录运行。

## 配置项

| 配置 | 作用 |
|---|---|
| SHOPDESK_MODE | local 或 llm |
| SHOPDESK_HOME | 运行根目录 |
| SHOPDESK_ADMIN_TOKEN | 管理 API 的 X-Admin-Token |
| OPENAI_API_KEY / OPENAI_BASE_URL / CHAT_MODEL | 结构化 Query 与回答模型 |
| STRUCTURED_METHOD | function_calling / json_schema / json_mode |
| EMBEDDING_BACKEND | hash 或 openai |
| EMBEDDING_MODEL / EMBEDDING_BASE_URL / EMBEDDING_API_KEY | 向量模型 |
| RERANK_BACKEND | local / http / cross_encoder |
| RERANK_URL / RERANK_API_KEY / RERANK_MODEL | HTTP 或本地神经重排配置 |
| QDRANT_URL / QDRANT_API_KEY / QDRANT_COLLECTION | 空 URL 使用本地持久库 |
| LANGSMITH_TRACING / LANGSMITH_API_KEY / LANGSMITH_PROJECT | 云端追踪 |

本地模式使用演示客户 demo-customer。X-Customer-ID 用于演示不同身份下的会话和订单隔离；实际部署时应由可信身份网关设置该身份，管理接口使用独立口令。

## Rerank

HTTP 请求：

```json
{"model":"指定模型","query":"平安扣拆封能退吗","documents":["片段一","片段二"],"top_n":2}
```

响应：

```json
{"results":[{"index":0,"relevance_score":0.92},{"index":1,"relevance_score":0.71}]}
```

CrossEncoder 建议使用兼容 PyTorch 的 Python 3.12 环境：

```powershell
python -m pip install -e ".[cross-encoder]"
```

配置 RERANK_BACKEND=cross_encoder 与 RERANK_MODEL，首次运行下载模型。

## 主要接口

| 接口 | 功能 |
|---|---|
| POST /api/sessions | 建立当前客户会话 |
| GET /api/sessions/{id} | 查询会话与历史 |
| POST /api/chat | JSON 问答 |
| POST /api/chat/stream | SSE 节点进度、answer、error、done |
| GET /api/knowledge | 管理端读取知识 |
| POST /api/knowledge | 新增文档 |
| PUT /api/knowledge/{id} | 修改并递增版本 |
| DELETE /api/knowledge/{id} | 删除文档，下一次问答同步移除索引 |
| POST /api/knowledge/reindex | 手动重建，strategy=adaptive/window |
| GET /api/tickets | 人工工单列表 |
| PATCH /api/tickets/{id} | 状态与处理说明 |
| POST /api/feedback | 客户对已完成回答反馈 |
| POST /api/benchmark | 运行固定本地评测 |
| GET /api/metrics | 实际请求与负向反馈统计 |

问答请求：

```json
{"session_id":"实际会话ID","request_id":"本轮唯一ID","message":"那它拆封后还能退吗？"}
```

## 容器

```powershell
docker build -t shopdesk-ai .
docker run --rm -p 127.0.0.1:8010:8010 -v shopdesk_data:/workspace --env-file .env shopdesk-ai
```

容器运行目录为 /workspace。使用单 worker 访问本地 Qdrant，持久卷保存 SQLite、索引与输出。开启 LangSmith 时模型与工具输入输出会发送到配置服务，按业务资料范围选择追踪设置。
