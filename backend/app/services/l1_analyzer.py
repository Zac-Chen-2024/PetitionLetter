"""
L-1 Analyzer Service - L-1 签证专项分析服务

功能:
- 针对 L-1 签证 4 大核心标准的专项提取
- 每个 Chunk 单独分析
- 返回结构化的引用信息
"""

from typing import List, Dict, Any, Optional
from datetime import datetime


def clean_ocr_for_llm(ocr_text: str) -> str:
    """
    临时清理 OCR 文本用于 LLM 分析

    只移除 DeepSeek-OCR 的调试输出，保留所有实际内容。
    原始数据库中的 ocr_text 和 text_blocks 不受影响，
    确保后续 BBox 匹配和回溯功能正常。

    Args:
        ocr_text: 原始 OCR 文本

    Returns:
        清理后的文本（仅用于发送给 LLM）
    """
    if not ocr_text:
        return ""

    lines = ocr_text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # 跳过 DeepSeek-OCR 调试输出
        if stripped.startswith('BASE:') and 'torch.Size' in stripped:
            continue
        if stripped.startswith('PATCHES:') and 'torch.Size' in stripped:
            continue
        # 跳过空的分隔线
        if stripped == '=====================':
            continue
        cleaned.append(line)
    return '\n'.join(cleaned)


# L-1 签证 4 大核心标准
L1_STANDARDS = {
    "qualifying_relationship": {
        "chinese": "合格的公司关系",
        "english": "Qualifying Corporate Relationship",
        "description": "美国公司与海外公司必须是母/子/分/关联公司关系",
        "keywords": ["母公司", "子公司", "关联公司", "分公司", "所有权", "股权", "持股", "控股", "共同控制"]
    },
    "qualifying_employment": {
        "chinese": "海外合格任职",
        "english": "Qualifying Employment Abroad",
        "description": "受益人过去3年中在海外关联公司连续工作至少1年",
        "keywords": ["任职", "工作", "职位", "入职", "离职", "任期", "年限", "海外", "境外"]
    },
    "qualifying_capacity": {
        "chinese": "合格的职位性质",
        "english": "Qualifying Capacity",
        "description": "L-1A: 高管/经理; L-1B: 专业知识人员",
        "keywords": ["高管", "经理", "管理", "决策", "战略", "专业知识", "专有技术", "指导", "监督", "人事权", "预算"]
    },
    "doing_business": {
        "chinese": "持续运营",
        "english": "Doing Business",
        "description": "美国和海外公司都必须持续、积极运营",
        "keywords": ["收入", "利润", "员工", "雇员", "银行", "存款", "合同", "业务", "办公", "注册"]
    }
}


def get_l1_analysis_prompt(doc_info: Dict[str, Any]) -> str:
    """
    生成 L-1 专项分析的提示词（整文档模式，无 Chunking）

    参数:
    - doc_info: 文档信息 {exhibit_id, file_name, text}

    返回: 格式化的提示词
    """
    exhibit_id = doc_info.get("exhibit_id", "X-1")
    file_name = doc_info.get("file_name", "unknown")
    document_text = doc_info.get("text", "")

    prompt = f"""You are a Senior L-1 Immigration Paralegal. Your mission is to COMPREHENSIVELY extract ALL factual quotes from this document that could support an L-1 visa application.

**IMPORTANT: Extract as many relevant quotes as possible. Each piece of factual information should be a separate quote. Do NOT summarize - extract the EXACT text.**

**L-1 Visa: 4 Core Legal Requirements:**

1.  **Qualifying Corporate Relationship** (qualifying_relationship)
    Extract: Company names, ownership percentages, stock amounts, parent/subsidiary mentions, affiliate relationships, shareholder info, articles of incorporation details.

2.  **Qualifying Employment Abroad** (qualifying_employment)
    Extract: Foreign company names, job titles, employment dates, work duration, position history, salary info, employment verification.

3.  **Qualifying Capacity** (qualifying_capacity)
    Extract: Job duties, management responsibilities, supervisory roles, strategic planning, decision-making authority, personnel authority, budget control, specialized knowledge, technical expertise.

4.  **Doing Business / Active Operations** (doing_business) - MOST COMMON, extract generously!
    Extract:
    - **Entity Info:** Company name, entity type, status (ACTIVE), registration dates, DOS ID, EIN, incorporation date
    - **Address:** Any business address, registered agent address, office location
    - **Financial:** Bank info, account numbers, balances, wire transfers, revenue, expenses
    - **Operations:** Employee counts, payroll, contracts, invoices, business activities
    - **Legal:** Lease agreements, rental amounts, contract terms

**Current Document Info:**
-   **Exhibit ID:** {exhibit_id}
-   **File Name:** {file_name}

**Output Format (JSON):**
Extract ALL relevant information. Use this structure:

{{
  "quotes": [
    {{
      "standard": "合格的公司关系",
      "standard_key": "qualifying_relationship",
      "standard_en": "Qualifying Corporate Relationship",
      "quote": "The exact original quote from the document...",
      "relevance": "A brief explanation of how this quote supports the standard.",
      "page": 1,
      "source": {{
        "exhibit_id": "{exhibit_id}",
        "file_name": "{file_name}"
      }}
    }}
  ]
}}

**Document Text:**
{document_text}
"""
    return prompt


def map_standard_to_key(standard_name: str) -> str:
    """
    将标准名称映射到标准 key

    参数:
    - standard_name: 标准名称 (中文或英文)

    返回: 标准 key
    """
    standard_name_lower = standard_name.lower()

    # 中文映射
    if "公司关系" in standard_name or "relationship" in standard_name_lower:
        return "qualifying_relationship"
    elif "任职" in standard_name or "employment" in standard_name_lower:
        return "qualifying_employment"
    elif "职位" in standard_name or "capacity" in standard_name_lower:
        return "qualifying_capacity"
    elif "运营" in standard_name or "business" in standard_name_lower:
        return "doing_business"
    else:
        return "other"


def parse_analysis_result(llm_response: Dict[str, Any], doc_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    解析 LLM 返回的分析结果（整文档模式）

    参数:
    - llm_response: LLM 返回的 JSON
    - doc_info: 原始文档信息

    返回: 标准化的引用列表
    """
    quotes = llm_response.get("quotes", [])

    # 如果 LLM 返回的是数组而不是对象
    if isinstance(llm_response, list):
        quotes = llm_response

    parsed = []
    for q in quotes:
        # 确保 standard_key 存在
        standard_key = q.get("standard_key")
        if not standard_key:
            standard_key = map_standard_to_key(q.get("standard", ""))

        # 确保 source 信息完整（整文档模式，无 chunk 字段）
        source = q.get("source", {})
        if not source:
            source = {
                "exhibit_id": doc_info.get("exhibit_id"),
                "file_name": doc_info.get("file_name")
            }

        parsed.append({
            "standard": q.get("standard", "未知标准"),
            "standard_key": standard_key,
            "standard_en": q.get("standard_en", ""),
            "quote": q.get("quote", ""),
            "relevance": q.get("relevance", ""),
            "page": q.get("page"),
            "source": source
        })

    return parsed


class ChunkAnalysisResult:
    """单个 Chunk 的分析结果"""

    def __init__(self, chunk_id: str, document_id: str, exhibit_id: str):
        self.chunk_id = chunk_id
        self.document_id = document_id
        self.exhibit_id = exhibit_id
        self.quotes: List[Dict[str, Any]] = []
        self.analyzed_at: Optional[datetime] = None
        self.model_used: Optional[str] = None
        self.error: Optional[str] = None

    def add_quotes(self, quotes: List[Dict[str, Any]]):
        self.quotes.extend(quotes)
        self.analyzed_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "exhibit_id": self.exhibit_id,
            "quotes": self.quotes,
            "analyzed_at": self.analyzed_at.isoformat() if self.analyzed_at else None,
            "model_used": self.model_used,
            "error": self.error
        }


def get_standards_info() -> Dict[str, Any]:
    """获取 L-1 标准的详细信息"""
    return {
        "standards": L1_STANDARDS,
        "count": len(L1_STANDARDS),
        "keys": list(L1_STANDARDS.keys())
    }
