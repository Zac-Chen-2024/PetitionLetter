"""
LLM Client - 统一的 LLM API 客户端

DeepSeek 和 OpenAI 都是 OpenAI 兼容 API，合并为统一接口。
默认使用 DeepSeek。
"""

import json
import re
import httpx
from typing import Dict, Optional
from ..core.config import settings


# 默认配置
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_TOKENS = 16000
DEFAULT_TEMPERATURE = 0.1

# 默认模型映射
DEFAULT_MODELS = {
    "deepseek": "deepseek-chat",
    "openai": "gpt-4.1",
}


def _get_provider_config(provider: str) -> tuple:
    """返回 (api_key, api_base, default_model) 根据 provider。"""
    if provider == "deepseek":
        return (
            settings.deepseek_api_key,
            settings.deepseek_api_base,
            DEFAULT_MODELS["deepseek"],
        )
    elif provider == "openai":
        return (
            settings.openai_api_key,
            settings.openai_api_base,
            DEFAULT_MODELS["openai"],
        )
    else:
        raise ValueError(f"Unknown provider: {provider}. Use 'deepseek' or 'openai'.")


def _build_response_format(provider: str, json_schema: Optional[Dict]) -> Optional[Dict]:
    """构建 response_format，处理 DeepSeek/OpenAI 差异。

    OpenAI 支持 strict JSON schema；DeepSeek 只支持 json_object。
    """
    if json_schema is None:
        return None
    if provider == "openai" and json_schema:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "strict": True,
                "schema": json_schema,
            },
        }
    # DeepSeek or empty schema: use json_object
    return {"type": "json_object"}


async def _call_api(
    prompt: str,
    provider: str,
    model: str = None,
    system_prompt: str = None,
    response_format: Dict = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """内部统一 API 调用，返回 content 字符串。"""
    api_key, api_base, default_model = _get_provider_config(provider)
    api_base = api_base.rstrip("/")

    if not api_key:
        raise ValueError(
            f"{provider.capitalize()} API key not configured. "
            f"Set {provider.upper()}_API_KEY in .env"
        )

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    request_body = {
        "model": model or default_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        request_body["response_format"] = response_format

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{api_base}/chat/completions",
            json=request_body,
            headers=headers,
        )
        if response.status_code != 200:
            raise Exception(f"{provider.capitalize()} API error {response.status_code}: {response.text}")
        result = response.json()

    return result.get("choices", [{}])[0].get("message", {}).get("content", "")


# ==================== 公开 API ====================

async def call_llm(
    prompt: str,
    system_prompt: str = None,
    json_schema: Dict = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
    provider: str = None,
    model: str = None,
) -> Dict:
    """统一 LLM JSON 调用。返回解析后的 Dict。"""
    provider = provider or settings.llm_provider
    response_format = _build_response_format(provider, json_schema)
    # If json_schema is None but caller expects JSON, force json_object
    if json_schema is None:
        response_format = {"type": "json_object"}

    content = await _call_api(
        prompt=prompt,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        response_format=response_format,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    return extract_json(content)


async def call_llm_text(
    prompt: str,
    system_prompt: str = None,
    temperature: float = 0.7,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
    provider: str = None,
    model: str = None,
) -> str:
    """统一 LLM 文本调用。返回纯文本。"""
    provider = provider or settings.llm_provider
    return await _call_api(
        prompt=prompt,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def extract_json(content: str) -> Dict:
    """从 LLM 响应中提取 JSON。支持纯 JSON、```json 代码块、混合文本。"""
    if not content or not content.strip():
        return {"content": ""}

    content = content.strip()

    # 1. 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2. 尝试提取 markdown 代码块
    for match in re.findall(r'```(?:json)?\s*([\s\S]*?)```', content):
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue

    # 3. 尝试查找 JSON 对象 {...}
    for match in re.findall(r'\{[\s\S]*\}', content):
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    # 4. 尝试查找 JSON 数组 [...]
    for match in re.findall(r'\[[\s\S]*\]', content):
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    return {"content": content}


async def test_connection(provider: str = "deepseek") -> Dict:
    """测试 API 连接。"""
    try:
        result = await call_llm(
            prompt="Say 'Hello, connection test successful!' in JSON format with key 'message'.",
            max_tokens=100,
            provider=provider,
        )
        return {"success": True, "provider": provider, "response": result}
    except Exception as e:
        return {"success": False, "provider": provider, "error": str(e)}
