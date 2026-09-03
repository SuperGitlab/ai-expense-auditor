"""
RAG检索Agent
两路检索（财务制度+历史案例）并让LLM筛选总结，辅助审核决策
"""
import json  # 把报销单/检索结果序列化成JSON文本拼进提示词
from typing import Any, Dict, List  # 类型标注

from pydantic import BaseModel, Field  # 定义LLM结构化输出的schema（字段名+类型+说明即提示词的一部分）

from app.agents.base_agent import AgentResult, BaseAgent  # 基类：LLM客户端 + structured_chat + 统一返回结构
from app.rag.retriever import ExpenseRetriever  # 两路检索器（Chroma向量库：制度/案例两个collection）


class RAGSummary(BaseModel):
    """LLM结构化输出：检索结果筛选总结"""
    # 用Pydantic schema而非自由文本：字段名和description会随工具定义发给LLM，
    # 既约束了输出格式（下游可直接dict化使用），又天然充当格式说明提示词
    relevant_rules: List[str] = Field(default_factory=list, description="与本案相关的制度条文")
    similar_cases: List[dict] = Field(default_factory=list, description="可参考的历史案例")
    retrieval_note: str = Field("", description="检索结论说明")


class RAGAgent(BaseAgent):
    """RAG检索Agent：组查询串→两路检索→LLM筛选总结"""

    def __init__(self):
        super().__init__(name="RAG检索Agent")  # 初始化基类（LLM客户端、记忆等）
        self.retriever = ExpenseRetriever()  # 检索器：内含制度/案例两个向量库句柄
        # GLM兼容接口不支持OpenAI的response_format，必须显式走tool-call模式
        # （with_structured_output默认走json_mode，GLM下会报错/不生效）
        self.structured_llm = self.llm.with_structured_output(
            RAGSummary, method="function_calling"
        )

    def get_system_prompt(self) -> str:
        # 检索筛选的角色提示词：RAG初检是向量相似度，免不了混入不相关内容，
        # 让LLM做"精筛"并明示"宁缺毋滥"，避免无关制度/案例误导后续审核决策
        return (
            "你是财务审核知识检索专家。给你检索到的公司财务制度片段和历史报销案例，"
            "请针对当前报销单筛选出真正相关的内容：\n"
            "1. relevant_rules：与本案费用类型/金额/情形直接相关的制度条文（原文摘录）\n"
            "2. similar_cases：与本案相似的历史案例（保留expense_id/title/status/risk_level）\n"
            "不相关的检索结果直接丢弃，宁缺毋滥。检索为空时返回空列表并说明。"
        )

    def _build_query(self, snapshot: dict) -> str:
        """组装检索查询串：标题+类型+明细摘要+金额"""
        expense = snapshot["expense"]
        # 明细摘要：每条取"类别 金额 说明前30字"，用"；"拼成一段
        # 只取前5条、说明截断30字：控制查询串长度，信息密度高的前缀已足够向量检索命中
        item_brief = "；".join(
            f"{it.get('category_name')} {it.get('amount')}元 {it.get('description', '')[:30]}"
            for it in snapshot["items"][:5]
        )
        # 拼成一句话查询：标题+费用类型+总额+明细摘要（语义越丰富，向量召回越准）
        return (
            f"{expense.get('title')} {expense.get('expense_type')} "
            f"总额{expense.get('total_amount')}元 {item_brief}"
        )

    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        input_data: {"expense": snapshot}
        """
        snapshot = input_data["expense"]  # 报销单快照（expense主表 + items明细）
        query = self._build_query(snapshot)  # 组装向量检索查询串

        # 1. 两路检索（Chroma不可用/为空时返回空列表，不抛异常）
        # 同一查询串分别查"制度"和"案例"两个collection，各取相似度top3
        policies = self.retriever.retrieve_policies(query, k=3)  # 制度条文 [{content, source, section, distance}]
        cases = self.retriever.retrieve_similar_cases(query, k=3)  # 历史案例 [{content, expense_id, title, status, risk_level, distance}]

        # 2. LLM筛选总结（检索为空时跳过LLM；LLM失败降级为原始检索结果）
        # 知识库整体为空：没必要调LLM（省token），也免得LLM凭空编造制度条文
        if not policies and not cases:
            return AgentResult(
                success=True,
                data={"relevant_rules": [], "similar_cases": [], "retrieval_note": "知识库为空，跳过检索"},
                message="知识库为空",
            )

        try:
            # 提示词 = 当前单据（主表+明细） + 两路检索结果，全部JSON化喂给LLM精筛
            prompt = (
                f"当前报销单：{json.dumps(snapshot['expense'], ensure_ascii=False)}\n"
                f"明细：{json.dumps(snapshot['items'], ensure_ascii=False)}\n\n"
                f"检索到的财务制度片段：\n{json.dumps(policies, ensure_ascii=False)}\n\n"
                f"检索到的历史案例：\n{json.dumps(cases, ensure_ascii=False)}\n"
                "请筛选总结。"
            )
            # structured_chat：system prompt + 一次性prompt调self.structured_llm，
            # 返回RAGSummary对象（function_calling模式保证GLM兼容）
            result: RAGSummary = await self.structured_chat(prompt)
            data = {
                # LLM筛选后的相关制度条文（原文摘录列表）
                "relevant_rules": result.relevant_rules,
                # LLM筛出的相似案例；若LLM没返回案例则回退用原始检索结果
                # （只保留4个关键字段，去掉content长文本，控制下游prompt体积）
                "similar_cases": result.similar_cases or [
                    {k: c[k] for k in ("expense_id", "title", "status", "risk_level")}
                    for c in cases
                ],
                "retrieval_note": result.retrieval_note,  # LLM的检索结论说明
                "raw_policies": len(policies),  # 精筛前的制度片段数（观测LLM筛掉了多少）
                "raw_cases": len(cases),  # 精筛前的案例数
            }
            # message优先用LLM结论，为空则用数量统计兜底
            message = result.retrieval_note or f"检索到 {len(policies)} 段制度 / {len(cases)} 个案例"
        except Exception as e:
            # LLM失败：直接返回原始检索结果（降级）
            # 检索本身已成功，不因LLM故障丢掉检索价值；标注降级原因便于排查
            data = {
                # 制度条文截前120字：降级路径没有LLM压缩，手动控制体积
                "relevant_rules": [p["content"][:120] for p in policies],
                # 案例同样只留4个关键字段（此处用get容错，metadata缺字段不炸）
                "similar_cases": [
                    {k: c.get(k) for k in ("expense_id", "title", "status", "risk_level")}
                    for c in cases
                ],
                "retrieval_note": f"LLM筛选降级（{e}），返回原始检索结果",
                "raw_policies": len(policies),
                "raw_cases": len(cases),
            }
            message = data["retrieval_note"]

        return AgentResult(success=True, data=data, message=message)
