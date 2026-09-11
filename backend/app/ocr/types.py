"""
OCR结果数据结构
"""
from dataclasses import dataclass, field


@dataclass
class OCRResult:
    """单张发票的结构化提取结果"""
    method: str = "placeholder"  # rapidocr / vlm / text / placeholder
    raw_text: str = ""           # 提取全文（docx/txt为直读文本）
    confidence: float = 0.0      # RapidOCR平均置信度，其余来源为0
    fields: dict = field(default_factory=dict)      # KIE/VLM抽取的结构化字段
    anomalies: list = field(default_factory=list)   # 业务校验异常描述

    @property
    def ok(self) -> bool:
        """抽取到字段且校验全过"""
        return bool(self.fields) and not self.anomalies
