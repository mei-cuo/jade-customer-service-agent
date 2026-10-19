# 开发指南

```powershell
python -m pip install -e ".[dev]"
python -m ruff check src tests
python -m pytest -q
python -m shopdesk evaluate
python -m build
```

改写、分块、重排和生成分别维护。新增翡翠知识时明确单件商品编号与适用范围；变更 Prompt 后执行固定评测并检查失败明细。新增业务规则同步 PRD、验收用例和示例。

运行输出、数据库、索引、密钥和个人资料不进入版本库。客户订单工具保持身份范围，所有完成问答通过唯一 request_id 保存。
