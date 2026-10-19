# 项目约定

- 安装 `python -m pip install -e ".[dev]"`；测试 `python -m pytest -q`。
- Service 为 CLI、REST 和 SSE 共用执行边界。
- 商品为翡翠，按单件商品 ID 读取规格、档案和售后条件。
- 代码资源在 src/shopdesk/assets，知识、Prompt 与前端需随 wheel 打包。
- 原始会话保留在 SQLite，模型上下文使用有限消息和结构化实体记忆。
- 请求按 (session_id,request_id) 幂等，工单复用当前未解决记录。
- 变更知识后同步索引 revision，清理失效向量。
- 模型与 Rerank 配置同步 .env.example 和部署文档。
- 产物放 runtime/、outputs/，本机密钥放 .env。
