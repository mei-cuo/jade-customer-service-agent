# 验证记录

2026-10-19，Windows、Python 3.14。

- 26 项 Python 自动化测试通过。
- Ruff lint 与 format 检查通过，前端 JavaScript 语法检查通过。
- 32 轮翡翠场景 Benchmark 完成，报告包含原始 Query 基线与完整链路对照。
- 浏览器验证：商品问答、跨轮售后追问、文档保存与 v2 来源引用、人工工单创建与接单、评测运行。
- 响应式验证：1440×900 桌面与 390×844 窄屏；新建会话、设置入口及输入区可访问。
- wheel 已在独立 .venv 安装；26 项测试通过，从项目外目录执行 J01 规格问答成功，pip check 通过，资源检查通过。

本地实测模式为 hash Embedding、本地 Rerank 与抽取式回答。真实 LLM、远程 Embedding、HTTP Rerank、CrossEncoder 及 LangSmith 的连接步骤见部署文档，云端行为以接入对应服务后的运行记录为准。

截图位于 docs/images/。原始 Benchmark 保存到 examples/benchmark-result.json。
