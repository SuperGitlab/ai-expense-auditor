"""
增值税发票字段正则抽取(KIE)纯函数测试
"""
from app.ocr.kie import extract_fields, key_fields_complete

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
