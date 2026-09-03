"""
知识库管理模块
财务制度文档与历史案例的入库管理（中文按字符滑窗切块）
"""
import logging  # Python内置日志库；logger.info() 打出的信息带模块名，方便定位来源

import uuid  # 生成全局唯一随机ID（uuid4），给每个知识块当主键用

from typing import Optional  # 类型标注工具（本文件当前未实际使用，保留的历史导入）

from app.rag.vectorstore import VectorStore  # 向量库的门面类：内部封装ChromaDB的增/查/计数
from app.rag.retriever import CASES_COLLECTION, POLICIES_COLLECTION  # 两个"表"（集合）的名字常量

# 以本模块名建logger：日志会显示来自 app.rag.knowledge_base
logger = logging.getLogger(__name__)

# 中文切块参数：500字/块，相邻块重叠50字
# 为什么切块：embedding对短文本更准；且检索时只返回相关段落，不返回整篇
# 为什么重叠：防止关键句正好被切在刀口上（如"不超过3000|元"断成两半就没法检索了）
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    中文文本滑窗切块（按字符数，不依赖tokenizers）
    （英文有按词/按token的现成切法；中文按字符数切最简单，不用装分词库）
    """
    text = text.strip()  # 去掉首尾空白/换行，避免切出无内容的块
    if not text:  # 空文本 → 返回空列表，调用方拿到[]自然跳过
        return []
    chunks = []  # 收集切出来的所有块
    start = 0  # 窗口起点，从第0个字符开始
    while start < len(text):  # 起点还没越过文本末尾就继续切
        end = start + chunk_size  # 窗口终点 = 起点 + 500（越界也没关系，Python切片自动截到末尾）
        chunks.append(text[start:end])  # 切下[start, end)这段，存入结果
        start = end - overlap  # 下一个窗口的起点 = 本次终点往回退50字 → 与上一块重叠50字
        if start >= len(text):  # 回退后的起点若已到末尾，说明尾部内容已被本块覆盖完，收工
            break
    return chunks  # 例如520字的文本 → 两块：[0:500] 和 [450:520]（重叠50字）


class KnowledgeBaseManager:
    """
    知识库管理器：
    - policies集合：公司财务制度文档
    - similar_cases集合：历史已结案报销单（AI决策后回填）
    """

    def __init__(self):
        # 打开两个向量库"表"（ChromaDB集合，数据落盘在 CHROMA_PERSIST_DIR=./data/chroma）：
        # policies_store —— 制度库：init_knowledge.py 灌的8段制度就存这里
        # cases_store    —— 案例库：AI每审完一单，把该报销单摘要回填进来，越用越厚
        self.policies_store = VectorStore(POLICIES_COLLECTION)
        self.cases_store = VectorStore(CASES_COLLECTION)

    def load_knowledge_bases(self) -> dict:
        """
        启动时加载/校验知识库（幂等：已有数据跳过）
        """
        policies_count = self.policies_store.count()  # 数一下制度库里现有几段
        cases_count = self.cases_store.count()  # 数一下案例库里现有几条
        logger.info(  # 打一条加载日志：启动时控制台能看到知识库规模
            f"知识库加载完成：财务制度 {policies_count} 段，历史案例 {cases_count} 条"
        )
        # 返回统计字典，供init_knowledge.py末尾打印 / 其他地方校验用
        return {"policies": policies_count, "similar_cases": cases_count}

    def add_policy_documents(self, docs: list[dict]) -> int:
        """
        灌入制度文档（自动切块）

        Args:
            docs: [{content, source?, section?}]
        Returns: 入库块数
        """
        # ChromaDB的add接口要求三个"平行列表"：第i块文本对应第i个元数据、第i个ID
        texts, metadatas, ids = [], [], []
        for doc in docs:  # 逐篇处理传入的制度文档（init_knowledge.py传了8篇）
            content = doc.get("content", "")  # 取正文；没写content键则当空串（切出来是[]，等于跳过）
            for i, chunk in enumerate(split_text(content)):  # 切块，enumerate顺便拿到块序号i
                texts.append(chunk)  # 块文本（之后会被embedding变成1024维向量）
                metadatas.append({  # 块的"标签"：检索命中后能显示出处，也支持按标签过滤
                    "source": doc.get("source", "公司财务制度"),  # 来自哪份文档（有默认值，可不填）
                    "section": doc.get("section", ""),  # 章节名，如"差旅费管理"
                    "chunk_index": i,  # 这是该篇的第几块，便于把同一篇的块按顺序拼回去
                })
                # 唯一ID：前缀policy- + uuid4取12位hex；每次随机生成，绝不与已有块撞车
                ids.append(f"policy-{uuid.uuid4().hex[:12]}")
        if not texts:  # 传入的文档全是空的 → 没有任何块要入库
            return 0
        # 真正入库：VectorStore内部先调GLM embedding把每块文本变向量，再连同元数据/ID写入ChromaDB
        added = self.policies_store.add_documents(texts, metadatas, ids)
        logger.info(f"财务制度入库：{added} 块")
        return added  # 返回块数（注意≠篇数：超500字的长文档会被切成多块）

    def add_case_from_expense(self, snapshot: dict, decision: dict) -> int:
        """
        将已结案报销单写入历史案例库（供后续相似检索）

        Args:
            snapshot: build_snapshot的报销单快照
            decision: {action, reason, risk_level, risk_score}
        Returns: 入库条数（0表示失败或跳过）
        """
        expense = snapshot.get("expense", {})  # 报销单主信息（标题/类型/总额），取不到则空字典不报错
        items = snapshot.get("items", [])  # 明细列表（每条含类别/金额/发票号）
        # 把所有明细拼成一行摘要，如 "差旅费553.5元(有发票); 餐饮费120元(无发票)"
        item_lines = "; ".join(
            f"{it.get('category_name') or '未分类'}{it.get('amount')}元"
            f"({'有发票' if it.get('invoice_no') else '无发票'})"
            for it in items
        )
        # 拼成一段自然语言"案例卡片"——这段文字整体会被embed，
        # 以后新报销单做语义检索时，能按相似度命中"以前类似的单子当时怎么判的"
        text = (
            f"报销单[{expense.get('title')}] 类型:{expense.get('expense_type')} "
            f"总额:{expense.get('total_amount')}元 "
            f"明细:{item_lines} "
            f"部门:{(snapshot.get('applicant') or {}).get('department')} "
            f"AI结论:{decision.get('action')} 风险:{decision.get('risk_level')}"
            f"({decision.get('risk_score')}分) 理由:{decision.get('reason')}"
        )
        metadata = {  # 结构化标签：检索命中后前端可展示，也支持按风险等级等条件过滤
            "expense_id": expense.get("id"),  # 关联的报销单ID，能反查MySQL里的原始单据
            "title": expense.get("title", ""),
            "status": decision.get("final_status", ""),  # 最终状态（approved/rejected）
            "risk_level": decision.get("risk_level", ""),  # 风险等级（low/middle/high）
            "risk_score": decision.get("risk_score"),  # 风险分0-100
        }
        # 案例ID：报销单ID + 6位随机尾巴（防同一单多次入库时ID冲突）
        case_id = f"case-{expense.get('id')}-{uuid.uuid4().hex[:6]}"
        # 单条入库：注意三个参数都是只装1个元素的列表（复用同一个批量接口）
        return self.cases_store.add_documents([text], [metadata], [case_id])

    def reset(self) -> None:
        """清空两个集合（开发调试用）"""
        self.policies_store.reset()  # 清空制度库
        self.cases_store.reset()  # 清空案例库
        logger.info("知识库已清空")
