"""
LLM factory — returns a LangChain chat model based on the configured model name.

Gemini models route to ``ChatGoogleGenerativeAI``, Claude to ``ChatAnthropic``, GPT to
``ChatOpenAI``. Use ``role='planner'`` to pick the (optionally stronger) planner model
and ``role='extractor'`` for the cheap default — keeps per-page extraction cheap while
allowing a smarter planner.
"""
from __future__ import annotations

from typing import Optional

from django.conf import settings


def get_llm(model: Optional[str] = None, temperature: Optional[float] = None,
            role: Optional[str] = None):
    if model is None:
        model = settings.AI_PLANNER_MODEL if role == 'planner' else settings.DEFAULT_AI_MODEL
    temperature = settings.AI_TEMPERATURE if temperature is None else temperature

    if model.startswith('gemini'):
        if not settings.GOOGLE_GEMINI_API_KEY:
            raise ValueError("GOOGLE_GEMINI_API_KEY is not configured")
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            google_api_key=settings.GOOGLE_GEMINI_API_KEY,
        )

    if model.startswith('claude'):
        if not settings.ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            temperature=temperature,
            max_tokens=settings.AI_MAX_TOKENS,
            api_key=settings.ANTHROPIC_API_KEY,
        )

    if model.startswith('gpt') or model.startswith('o1') or model.startswith('o3'):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not configured")
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=settings.OPENAI_API_KEY,
        )

    raise ValueError(f"Unsupported model: {model}")
