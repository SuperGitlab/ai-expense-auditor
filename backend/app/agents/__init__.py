"""
AI Agent模块
包含Agent基类、专业Agent实现和LangGraph工作流编排。
具体Agent（Document/Rule/RAG/Risk/Decision）与workflow按需从各自模块导入。
"""
from app.agents.base_agent import AgentResult, BaseAgent

__all__ = ["AgentResult", "BaseAgent"]
