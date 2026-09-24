"""
Agent基类
定义所有Agent的通用接口和行为
"""
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_function
from pydantic import BaseModel

from app.config import settings
import logging

logger = logging.getLogger(__name__)


class AgentResult(BaseModel):
    """Agent执行结果模型"""
    success: bool
    data: Dict[str, Any]
    message: str
    metadata: Optional[Dict[str, Any]] = None


class BaseAgent(ABC):
    """
    Agent基类

    提供LLM调用（结构化输出/无状态对话）等通用能力，
    子类需实现run方法并按需重写get_system_prompt。
    """

    def __init__(self, name: str, **kwargs: Any):
        """
        初始化Agent

        Args:
            name: Agent名称
        """
        self.name = name

        # LLM客户端（Kimi for Coding，兼容OpenAI接口）
        # 超时必须有界：celery --pool=solo 单并发，一个挂起的LLM调用会冻住worker、
        # 排队任务全部滞留（节点全"待执行"的假死象）
        self.llm = ChatOpenAI(
            model=settings.MODEL_NAME,
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_API_BASE,
            # K3思考模型仅允许temperature=1，不传（默认1）；稳定性由思考过程保证
            max_tokens=settings.MAX_TOKENS,
            # K3思考型模型的思考力度；推理token计入max_tokens
            reasoning_effort=settings.LLM_REASONING_EFFORT,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=settings.LLM_MAX_RETRIES,
        )

        # 结构化输出的schema（_make_structured_llm时记录，供日志打印tools定义）
        self.structured_schema: type[BaseModel] | None = None

    def _make_structured_llm(self, schema: type[BaseModel]):
        """构建结构化输出LLM并记录schema（走tool-call模式）

        tool_choice必须显式覆盖为auto：Kimi思考模型拒绝"指定函数"式强制调用
        （tool_choice 'specified' is incompatible with thinking enabled），
        改为auto+各Agent系统提示词中的格式要求引导模型自主调用。
        （Kimi的OpenAI兼容层支持response_format json_schema，但tool-call模式
        对嵌套Pydantic schema的兼容性已实测验证，保持原路径最小改动。）
        """
        self.structured_schema = schema
        return self.llm.with_structured_output(
            schema, method="function_calling", tool_choice="auto"
        )

    # 消息type → HTTP请求里的role（human/ai是LangChain内部叫法）
    _ROLE_MAP = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}

    def _log_llm_request(self, method: str, messages: list[Any]) -> None:
        """打印最终发给LLM的完整请求：模型参数 + messages prompt原文 + 结构化输出的tools定义"""
        # 只打印真实下发的参数：temperature未传（K3思考模型仅允许1，见__init__），
        # 实际生效的采样控制是reasoning_effort——日志谎报参数会误导线上排查
        lines = [
            f"Agent[{self.name}] ▶▶ 发给LLM的完整请求({method}) "
            f"model={settings.MODEL_NAME} max_tokens={settings.MAX_TOKENS} "
            f"reasoning_effort={settings.LLM_REASONING_EFFORT}"
        ]
        for i, m in enumerate(messages):
            mtype = getattr(m, "type", "unknown")
            role = self._ROLE_MAP.get(mtype, mtype)
            lines.append(f"--- messages[{i}] role={role} ---")
            lines.append(str(m.content))
        if self.structured_schema is not None:
            func = convert_to_openai_function(self.structured_schema)
            lines.append("--- tools（结构化输出，tool_choice=auto）---")
            lines.append(json.dumps([{"type": "function", "function": func}], ensure_ascii=False, indent=2))
            lines.append("--- tool_choice ---")
            # 思考模型拒绝"指定函数"式强制调用，实际下发auto（见_make_structured_llm），日志如实打印
            lines.append(json.dumps({"type": "auto"}, ensure_ascii=False))
        logger.info("\n".join(lines))

    @abstractmethod
    async def run(self, input_data: Dict[str, Any]) -> AgentResult:
        """
        执行Agent任务

        Args:
            input_data: 输入数据

        Returns:
            AgentResult: 执行结果
        """
        ...

    def get_system_prompt(self) -> str:
        """
        获取系统提示词，子类可重写以定制角色
        """
        return """你是一个专业的AI助手。
请根据输入数据，运用你的专业知识完成任务。
输出应该清晰、准确、结构化。"""

    async def structured_chat(self, prompt: str) -> Any:
        """
        结构化LLM调用：system prompt（子类重写的专家指令）+ 用户数据prompt

        子类需在__init__中先初始化 self.structured_llm（with_structured_output包装），
        返回值由各子类的schema决定（Pydantic对象）。
        """
        messages = [
            SystemMessage(content=self.get_system_prompt()),
            HumanMessage(content=prompt),
        ]
        self._log_llm_request("structured_chat", messages)
        return await self.structured_llm.ainvoke(messages)

    async def stateless_chat(self, prompt: str) -> str:
        """
        无状态普通对话：一次性消息（system + user），不保存任何历史。

        适合单次翻译/摘要类任务，避免跨报销单的上下文污染
        （Agent是模块级单例，任何带状态的对话都会跨单据累积）。
        """
        messages = [
            SystemMessage(content=self.get_system_prompt()),
            HumanMessage(content=prompt),
        ]
        self._log_llm_request("stateless_chat", messages)
        resp = await self.llm.ainvoke(messages)
        return resp.content

    def __repr__(self):
        return f"<{self.__class__.__name__}(name={self.name})>"
