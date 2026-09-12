"""
增值税发票字段正则抽取(KIE)纯函数测试
"""
from app.ocr.kie import extract_fields, extract_item_fields, key_fields_complete

SAMPLE = """江苏增值税电子普通发票
购买方名称：测试科技有限公司  纳税人识别号：91320100MA1EXAMPLE
销售方名称：南京某某商贸有限公司  纳税人识别号：91320100KUNOWN1234
开票日期：2026年08月15日
项目名称 规格 单价 金额 税率 税额
*信息技术服务*平台服务费        ¥95.00    6%  ¥5.00
合 计                        ¥95.00        ¥5.00
价税合计（大写） 壹佰元整      ¥100.00
发票号码：25617000000123456789"""


def test_extract_full_sample():
    fields = extract_fields(SAMPLE)
    assert fields["invoice_no"] == "25617000000123456789"
    assert fields["date"] == "2026年08月15日"
    assert fields["amount_excl"] == "95.00"
    assert fields["tax"] == "5.00"
    assert fields["amount_total"] == "100.00"
    assert fields["buyer_tax_id"] == "91320100MA1EXAMPLE"
    assert fields["seller_tax_id"] == "91320100KUNOWN1234"


def test_extract_dash_date_and_comma_amounts():
    text = "开票日期：2026-08-15\n合 计 ¥1,000.00 ¥60.00\n价税合计（大写）壹仟零陆拾元 ¥1,060.00"
    fields = extract_fields(text)
    assert fields["date"] == "2026-08-15"
    assert fields["amount_excl"] == "1000.00"
    assert fields["amount_total"] == "1060.00"


def test_key_fields_complete():
    assert key_fields_complete({"invoice_no": "1" * 8, "amount_total": "1.00"})
    assert not key_fields_complete({"invoice_no": "1" * 8})          # 缺价税合计
    assert not key_fields_complete(extract_fields("无关文本"))


def test_empty_text():
    assert extract_fields("") == {}


# ---------- extract_item_fields：上传回填五字段（真实福建专票OCR样本） ----------

FUJIAN_OCR = """福建增值税专用发票
No 01096036:50072130
3500172130
01096036
开票日期：2018年08月07日
称：厦门泰置业有限公司
密
*07<862634//>8+48/<5/2*193>
纳税人识别号：91350200MA2XNELY6K
开户行及账号：中国工商银行厦门口支行4100023509200082922
*金属制品*钢质防火门
平方
250
379.31034483
94827.59
16%
15172.41
合
计
¥15172.41
价税合计（大写）
壹拾壹万圆整
913505005917295649
）¥110000.00
称：福建福发门窗有限公司"""


def test_item_fields_full_fujian_invoice():
    f = extract_item_fields(FUJIAN_OCR)
    assert f["invoice_no"] == "01096036"      # No前缀带冒号截断
    assert f["expense_date"] == "2018-08-07"  # 年月日归一化
    assert f["amount"] == "110000.00"         # 价税合计窗口跳过穿插的税号行
    assert f["description"] == "钢质防火门"    # 密码区乱码行不误判为明细
    assert f["category_name"] == "其他费用"


def test_item_fields_prefers_invoice_no_prefix():
    f = extract_item_fields("发票号码：25617000000123456789\n开票日期：2026-08-15")
    assert f["invoice_no"] == "25617000000123456789"
    assert f["expense_date"] == "2026-08-15"


def test_item_fields_standalone_no_line():
    assert extract_item_fields("01096036")["invoice_no"] == "01096036"


def test_item_fields_category_keywords():
    assert extract_item_fields("酒店住宿费 住宿")["category_name"] == "住宿费"  # 酒店不得误判餐饮
    assert extract_item_fields("*餐饮服务*工作餐")["category_name"] == "餐饮费"
    assert extract_item_fields("机票 电子发票")["category_name"] == "差旅费"
    assert extract_item_fields("完全无关文本")["category_name"] == "其他费用"


def test_item_fields_empty_text():
    assert extract_item_fields("") == {
        "invoice_no": "", "expense_date": "", "amount": "",
        "description": "", "category_name": "其他费用",
    }
