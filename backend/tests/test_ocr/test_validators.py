"""
增值税发票业务校验纯函数测试
税号位数 / 勾稽 ±0.01 / 日期 / 发票号一致性
"""
from app.ocr.validators import validate_invoice


GOOD = {
    "invoice_no": "25617000000123456789",
    "date": "2026-08-15",
    "amount_excl": "95.00",
    "tax": "5.00",
    "amount_total": "100.00",
    "buyer_tax_id": "91320100MA1EXAMPLE",   # 18位含字母
    "seller_tax_id": "91320100123456789X",
}


def test_all_pass():
    assert validate_invoice(GOOD) == []


def test_missing_invoice_no():
    fields = {**GOOD, "invoice_no": ""}
    anomalies = validate_invoice(fields)
    assert any("发票号码缺失" in a for a in anomalies)


def test_bad_invoice_no_format():
    fields = {**GOOD, "invoice_no": "12345"}  # 太短
    assert any("发票号码格式异常" in a for a in validate_invoice(fields))


def test_invoice_no_mismatch_with_declared():
    assert any("发票号不一致" in a for a in validate_invoice(GOOD, declared_no="9999999999"))
    # 手填为空不比对
    assert validate_invoice(GOOD, declared_no=None) == []


def test_tax_id_length():
    fields = {**GOOD, "seller_tax_id": "91320100KUNOWN12345"}  # 19位(合法为18/20)
    assert any("销方税号格式异常" in a for a in validate_invoice(fields))
    # 缺失不报(票面可能无)
    fields = {k: v for k, v in GOOD.items() if k != "buyer_tax_id"}
    assert not any("税号" in a for a in validate_invoice(fields))


def test_amount_reconciliation():
    fields = {**GOOD, "tax": "6.00"}  # 95+6 != 100
    assert any("勾稽不符" in a for a in validate_invoice(fields))
    ok = {**GOOD, "amount_excl": "95.005", "tax": "4.995", "amount_total": "100.00"}
    assert validate_invoice(ok) == []  # ±0.01容差


def test_amounts_missing():
    fields = {k: v for k, v in GOOD.items() if k not in ("amount_excl", "tax")}
    assert any("金额字段缺失" in a for a in validate_invoice(fields))


def test_date_formats():
    assert any("开票日期格式异常" in a for a in validate_invoice({**GOOD, "date": "2026/8/15"}))
    assert validate_invoice({**GOOD, "date": "2026年08月15日"}) == []
