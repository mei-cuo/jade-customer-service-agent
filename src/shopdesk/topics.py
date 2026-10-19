"""Normalize jade-commerce question wording into retrieval topic anchors."""

GROUPS = [
    ("尺寸", ("尺寸", "规格", "直径", "外径", "长宽", "多大")),
    ("重量", ("重量", "多重", "多少克")),
    ("圈口", ("圈口", "内径", "戴多大", "手掌")),
    ("配件", ("配件", "挂绳", "礼盒")),
    ("外观", ("颜色", "飘花", "棉", "色差", "实拍")),
    ("价格", ("价格", "多少钱", "售价", "标价")),
    ("证书", ("证书", "编号", "查询")),
    ("保养", ("保养", "清洁", "清洗", "佩戴")),
    ("定制", ("定制", "刻字", "雕刻", "改圈")),
    ("拆封", ("拆封", "标签", "检查")),
    ("运费", ("运费", "邮费", "保价")),
    ("退货", ("退货", "退换", "申请售后")),
    ("发货", ("发货", "送达", "配送", "包装")),
    ("发票", ("发票", "税号")),
]


def topic_anchors(query):
    lower = query.lower()
    output = []
    for name, aliases in GROUPS:
        if any(alias in lower for alias in aliases):
            output.extend([name, *aliases])
    return list(dict.fromkeys(output))
