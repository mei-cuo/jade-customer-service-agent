# 技术架构

## 应用边界

CLI、REST 和 SSE 共用 Service。Service 注入 Store、Retriever、Planner、Generator 和 Reranker，并以 LangGraph 编排问题处理。前端使用同源 HTML/CSS/JS，所有数据显示来自 API。

## 存储

SQLite 保存知识版本、会话、已完成消息、请求状态、工单和反馈。Qdrant 保存子块向量与来源元数据，Embedding 缓存按模型指纹和文本摘要复用。SQLite 连接显式关闭，兼容 Windows 文件生命周期。

知识是权威数据源。首次建立库时写入演示材料；之后即使删除全部知识，也不会在重启时重新种入。新增、修改、启停和删除都会改变活动知识的 revision，检索前检查 revision 并更新索引。稳定块 ID 包含来源、版本与内容，重建后显式删除失效点。

## Chunk 与上下文

商品档案按标题分段，再以相邻句向量相似度和长度分组；FAQ 优先保持 Q/A 配对；SOP 按步骤拆分。长片段使用 380/60 的窗口与重叠。父段用于生成补全条件，例如尺寸与测量说明、拆封与未佩戴要求。

本地 hash Embedding 是字符 n-gram 特征。配置 OpenAI 兼容 Embedding 后，相同分块逻辑使用语义向量。模型、端点指纹变化触发重建，维度变化要求新 collection。

## 检索与重排

jieba 分词进入 BM25Okapi；向量进入 Qdrant cosine 检索；RRF 按 k=60 融合。当前商品过滤允许该商品及店铺通用文档，排除其他单件档案。默认最多召回 10 个候选并重排到 4 个，限制同文档重复片段。

本地重排使用问题词项覆盖、标题、商品范围、意图和领域主题。HTTP 后端兼容 query/documents/results 格式，校验索引和有限数值；CrossEncoder 后端延迟加载指定模型。

## Memory 与 Query

SQLite 原始消息保留完整对话；每次推理读取近期 12 条消息及结构化商品、意图、订单和 600 字符诉求摘要。显式商品名更新实体；指代和简短追问继承当前商品。LLM 模式通过 QueryPlan Schema 返回意图、完整问题、商品 ID 和澄清标记。

## 生成与来源

本地后端从相关父段选取句子，LLM 后端通过 AnswerDraft 生成回答与来源 ID。来源 ID 必须来自本次重排结果，重复或未知引用转人工。实物判断类请求在检索前直接路由人工。

## 请求与工单幂等

(session_id,request_id) 唯一。已完成请求复用答案；同 ID 更换消息会拒绝。消息和会话记忆在成功后共同提交。工单按会话复用未解决记录，防止多轮连续转接产生重复工单。

Service 在进程内串行访问本地 Qdrant。部署单工作进程；多实例需 Qdrant Server、共享数据库及跨实例会话锁。订单工具绑定会话客户，只返回该客户名下演示订单的状态。

## 可观测性

图调用包含 session_id、request_id 和 mode，节点耗时在 timeline 中返回；知识入库、混合检索和重排有 LangSmith span。提示词与模型连接集中配置，Benchmark 记录所用本地模式和数据集版本。
