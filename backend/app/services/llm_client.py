"""
LLM Client - 统一的 LLM API 客户端

只使用 API 调用，不使用本地模型。
支持多个 LLM 提供商：
- DeepSeek (默认，便宜且好用)
- OpenAI (GPT-4、GPT-4o-mini 等)
- Claude (预留)
"""

import json
import re
import httpx
from typing import Dict, List, Optional, Any
from ..core.config import settings


# 默认配置
DEFAULT_TIMEOUT = 120.0  # 秒
DEFAULT_MAX_TOKENS = 16000
DEFAULT_TEMPERATURE = 0.1

# DeepSeek 模型
DEEPSEEK_CHAT_MODEL = "deepseek-chat"  # DeepSeek-V3，便宜又好用
DEEPSEEK_REASONER_MODEL = "deepseek-reasoner"  # DeepSeek-R1，推理能力强


async def call_openai(
    prompt: str,
    model: str = "gpt-4o-mini",
    system_prompt: str = None,
    json_schema: Dict = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT
) -> Dict:
    """
    调用 OpenAI API

    Args:
        prompt: 用户提示词
        model: 模型名称 (gpt-4o-mini, gpt-4o, gpt-4-turbo 等)
        system_prompt: 系统提示词
        json_schema: 如果提供，使用 strict JSON schema 模式
        temperature: 采样温度
        max_tokens: 最大输出 token 数
        timeout: 超时时间（秒）

    Returns:
        解析后的 JSON 响应，或 {"content": str} 如果不是 JSON
    """
    api_key = settings.openai_api_key
    api_base = settings.openai_api_base.rstrip('/')

    if not api_key:
        raise ValueError("OpenAI API key not configured. Set OPENAI_API_KEY in .env")

    # 构建消息
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # 构建请求体
    request_body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    # 如果有 JSON schema，使用 strict mode
    if json_schema:
        request_body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "strict": True,
                "schema": json_schema
            }
        }
    else:
        # 即使没有 schema，也要求返回 JSON
        request_body["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{api_base}/chat/completions",
            json=request_body,
            headers=headers
        )

        if response.status_code != 200:
            error_detail = response.text
            raise Exception(f"OpenAI API error {response.status_code}: {error_detail}")

        result = response.json()

    # 提取内容
    message = result.get("choices", [{}])[0].get("message", {})
    content = message.get("content", "")

    # 解析 JSON
    return extract_json(content)


async def call_openai_text(
    prompt: str,
    model: str = "gpt-4o",
    system_prompt: str = None,
    temperature: float = 0.7,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT
) -> str:
    """
    调用 OpenAI API 获取纯文本响应（不要求 JSON）

    用于自由写作等场景

    Returns:
        纯文本响应
    """
    api_key = settings.openai_api_key
    api_base = settings.openai_api_base.rstrip('/')

    if not api_key:
        raise ValueError("OpenAI API key not configured. Set OPENAI_API_KEY in .env")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    request_body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{api_base}/chat/completions",
            json=request_body,
            headers=headers
        )

        if response.status_code != 200:
            error_detail = response.text
            raise Exception(f"OpenAI API error {response.status_code}: {error_detail}")

        result = response.json()

    message = result.get("choices", [{}])[0].get("message", {})
    return message.get("content", "")


async def call_deepseek(
    prompt: str,
    model: str = DEEPSEEK_CHAT_MODEL,
    system_prompt: str = None,
    json_schema: Dict = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT
) -> Dict:
    """
    调用 DeepSeek API (OpenAI 兼容格式)

    Args:
        prompt: 用户提示词
        model: 模型名称 (deepseek-chat, deepseek-reasoner)
        system_prompt: 系统提示词
        json_schema: JSON schema (DeepSeek 不支持 strict mode，会转为普通 json_object)
        temperature: 采样温度
        max_tokens: 最大输出 token 数
        timeout: 超时时间（秒）

    Returns:
        解析后的 JSON 响应
    """
    api_key = settings.deepseek_api_key
    api_base = settings.deepseek_api_base.rstrip('/')

    if not api_key:
        raise ValueError("DeepSeek API key not configured. Set DEEPSEEK_API_KEY in .env")

    # 构建消息
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # 构建请求体
    request_body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    # DeepSeek 支持 json_object 格式，但不支持 strict schema
    if json_schema:
        request_body["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{api_base}/chat/completions",
            json=request_body,
            headers=headers
        )

        if response.status_code != 200:
            error_detail = response.text
            raise Exception(f"DeepSeek API error {response.status_code}: {error_detail}")

        result = response.json()

    # 提取内容
    message = result.get("choices", [{}])[0].get("message", {})
    content = message.get("content", "")

    # 解析 JSON
    return extract_json(content)


async def call_deepseek_text(
    prompt: str,
    model: str = DEEPSEEK_CHAT_MODEL,
    system_prompt: str = None,
    temperature: float = 0.7,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT
) -> str:
    """
    调用 DeepSeek API 获取纯文本响应

    Returns:
        纯文本响应
    """
    api_key = settings.deepseek_api_key
    api_base = settings.deepseek_api_base.rstrip('/')

    if not api_key:
        raise ValueError("DeepSeek API key not configured. Set DEEPSEEK_API_KEY in .env")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    request_body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{api_base}/chat/completions",
            json=request_body,
            headers=headers
        )

        if response.status_code != 200:
            error_detail = response.text
            raise Exception(f"DeepSeek API error {response.status_code}: {error_detail}")

        result = response.json()

    message = result.get("choices", [{}])[0].get("message", {})
    return message.get("content", "")


async def call_claude(
    prompt: str,
    model: str = "claude-sonnet-4-20250514",
    system_prompt: str = None,
    temperature: float = 0.7,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT
) -> str:
    """
    调用 Claude API (预留)

    当前使用 DeepSeek 占位，后续可切换到真正的 Claude API

    Returns:
        纯文本响应
    """
    # 暂时使用 DeepSeek 作为占位
    # TODO: 实现真正的 Claude API 调用
    return await call_deepseek_text(
        prompt=prompt,
        model=DEEPSEEK_CHAT_MODEL,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout
    )


# ==================== 统一调用接口 ====================

async def call_llm(
    prompt: str,
    model: str = None,
    system_prompt: str = None,
    json_schema: Dict = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
    provider: str = None
) -> Dict:
    """
    统一的 LLM 调用接口

    根据配置自动选择提供商，默认使用 DeepSeek（便宜）

    Args:
        prompt: 用户提示词
        model: 模型名称（如果不指定，使用提供商默认模型）
        system_prompt: 系统提示词
        json_schema: JSON schema（部分提供商支持）
        temperature: 采样温度
        max_tokens: 最大输出 token 数
        timeout: 超时时间（秒）
        provider: 提供商 ("deepseek", "openai")，默认 deepseek

    Returns:
        解析后的 JSON 响应
    """
    provider = provider or "deepseek"  # 默认使用 DeepSeek

    if provider == "deepseek":
        return await call_deepseek(
            prompt=prompt,
            model=model or DEEPSEEK_CHAT_MODEL,
            system_prompt=system_prompt,
            json_schema=json_schema,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout
        )
    elif provider == "openai":
        return await call_openai(
            prompt=prompt,
            model=model or "gpt-4o-mini",
            system_prompt=system_prompt,
            json_schema=json_schema,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")


async def call_llm_text(
    prompt: str,
    model: str = None,
    system_prompt: str = None,
    temperature: float = 0.7,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
    provider: str = None
) -> str:
    """
    统一的 LLM 文本调用接口

    Returns:
        纯文本响应
    """
    provider = provider or "deepseek"

    if provider == "deepseek":
        return await call_deepseek_text(
            prompt=prompt,
            model=model or DEEPSEEK_CHAT_MODEL,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout
        )
    elif provider == "openai":
        return await call_openai_text(
            prompt=prompt,
            model=model or "gpt-4o",
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")


def extract_json(content: str) -> Dict:
    """
    从 LLM 响应中提取 JSON

    支持多种格式：
    1. 纯 JSON
    2. ```json ... ``` 代码块
    3. 混合文本中的 JSON
    """
    if not content or not content.strip():
        return {"content": ""}

    content = content.strip()

    # 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 尝试提取 markdown 代码块
    json_block_pattern = r'```(?:json)?\s*([\s\S]*?)```'
    matches = re.findall(json_block_pattern, content)
    for match in matches:
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue

    # 尝试查找 JSON 对象 {...}
    brace_pattern = r'\{[\s\S]*\}'
    brace_matches = re.findall(brace_pattern, content)
    for match in brace_matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    # 尝试查找 JSON 数组 [...]
    bracket_pattern = r'\[[\s\S]*\]'
    bracket_matches = re.findall(bracket_pattern, content)
    for match in bracket_matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    # 无法解析，返回原始内容
    return {"content": content}


# ==================== 便捷函数 ====================

async def analyze_with_schema(
    prompt: str,
    schema: Dict,
    model: str = None,
    system_prompt: str = "You are a helpful assistant that responds in JSON format.",
    provider: str = "deepseek"
) -> Dict:
    """
    使用 schema 进行分析（默认 DeepSeek）

    适用于需要结构化输出的场景
    """
    return await call_llm(
        prompt=prompt,
        model=model,
        system_prompt=system_prompt,
        json_schema=schema,
        provider=provider
    )


async def generate_prose(
    prompt: str,
    model: str = None,
    system_prompt: str = "You are a skilled professional writer.",
    provider: str = "deepseek"
) -> str:
    """
    生成自由文本（默认 DeepSeek）

    适用于写作场景
    """
    return await call_llm_text(
        prompt=prompt,
        model=model,
        system_prompt=system_prompt,
        temperature=0.7,
        provider=provider
    )


# ==================== 测试函数 ====================

async def test_connection(provider: str = "deepseek") -> Dict:
    """测试 API 连接"""
    try:
        result = await call_llm(
            prompt="Say 'Hello, connection test successful!' in JSON format with key 'message'.",
            max_tokens=100,
            provider=provider
        )
        return {
            "success": True,
            "provider": provider,
            "response": result
        }
    except Exception as e:
        return {
            "success": False,
            "provider": provider,
            "error": str(e)
        }
