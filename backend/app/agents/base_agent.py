"""
Agent基类
定义所有Agent的通用接口和行为
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from pydantic import BaseModel

from app.config import settings
import logging

logger = logging.getLogger(__name__)


class ConversationBufferMemory:
    """
    简单的对话记忆，保存LangChain消息对象。
    langchain 1.x 已移除 langchain.memory.ConversationBufferMemory，
    此处提供同接口的本地实现（等价于旧版 return_messages=True 模式）。
    """

    def __init__(self) -> None:
        self.messages: List[Any] = []

    def load_memory_variables(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """返回历史消息列表"""
        return {"chat_history": list(self.messages)}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        """保存一轮对话（用户输入 + AI回复）"""
        self.messages.append(HumanMessage(content=inputs["input"]))
        self.messages.append(AIMessage(content=outputs["output"]))

    def clear(self) -> None:
        """清空历史消息"""
        self.messages.clear()


class AgentResult(BaseModel):
    """Agent执行结果模型"""
    success: bool
    data: Dict[str, Any]
    message: str
    metadata: Optional[Dict[str, Any]] = None


class BaseAgent(ABC):
    """
    Agent基类

    提供LLM调用、对话记忆、工具管理等通用能力，
    子类需实现run方法并按需重写get_system_prompt。
    """

    def __init__(self, name: str, **kwargs: Any):
        """
        初始化Agent

        Args:
            name: Agent名称
        """
        self.name = name

        # LLM客户端（GLM，兼容OpenAI接口）
        self.llm = ChatOpenAI(
            model=settings.MODEL_NAME,
            api_key=settings.GLM_API_KEY,
            base_url=settings.GLM_API_BASE,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )

        # 对话记忆
        self.memory = ConversationBufferMemory()

        # 工具列表
        self.tools: List[Any] = []

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

    async def chat(self, user_input: str, system_prompt: Optional[str] = None) -> str:
        """
        与LLM进行对话

        Args:
            user_input: 用户输入
            system_prompt: 系统提示词（可选）

        Returns:
            str: LLM响应
        """
        # 构建消息列表
        messages = []

        # 添加系统消息
        system_content = system_prompt or self.get_system_prompt()
        messages.append(SystemMessage(content=system_content))

        # 添加历史记忆
        chat_history = self.memory.load_memory_variables({}).get("chat_history", [])
        messages.extend(chat_history)

        # 添加用户消息
        messages.append(HumanMessage(content=user_input))

        try:
            # 调用LLM
            response = await self.llm.ainvoke(messages)
            ai_message = response.content

            # 保存到记忆
            self.memory.save_context(
                {"input": user_input},
                {"output": ai_message}
            )

            return ai_message

        except Exception as e:
            logger.error(f"Agent [{self.name}] LLM调用失败: {str(e)}")
            raise

    async def structured_chat(self, prompt: str) -> Any:
        """
        结构化LLM调用：system prompt（子类重写的专家指令）+ 用户数据prompt

        与chat()对称：chat()管普通对话，structured_chat()管结构化输出。
        子类需在__init__中先初始化 self.structured_llm（with_structured_output包装），
        返回值由各子类的schema决定（Pydantic对象）。
        """
        messages = [
            SystemMessage(content=self.get_system_prompt()),
            HumanMessage(content=prompt),
        ]
        return await self.structured_llm.ainvoke(messages)

    async def stateless_chat(self, prompt: str) -> str:
        """
        无状态普通对话：一次性消息（system + user），不读写对话记忆。

        与chat()的区别：chat()会把每轮对话存入self.memory并在下次全部带上，
        适合多轮会话；单次翻译/摘要类任务用本方法，避免历史越积越多、
        以及跨报销单的上下文污染（Agent是模块级单例，记忆会跨单据累积）。
        """
        messages = [
            SystemMessage(content=self.get_system_prompt()),
            HumanMessage(content=prompt),
        ]
        resp = await self.llm.ainvoke(messages)
        return resp.content

    def add_tool(self, tool: Any):
        """
        添加工具

        Args:
            tool: 工具实例
        """
        self.tools.append(tool)
        logger.info(f"Agent [{self.name}] 添加工具: {tool.__class__.__name__}")

    def clear_memory(self):
        """清空记忆"""
        self.memory.clear()
        logger.info(f"Agent [{self.name}] 记忆已清空")

    def __repr__(self):
        return f"<{self.__class__.__name__}(name={self.name})>"
