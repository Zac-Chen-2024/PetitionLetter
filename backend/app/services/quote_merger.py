"""
Quote Merger Service - 引用汇总服务 (本地处理，不调用 LLM)

功能:
- 合并所有 Chunk 的分析结果
- 去重 (相同引用可能出现在重叠部分)
- 按 L-1 四大核心标准分类整理
- 生成结构化的关键引用清单
"""

from typing import List, Dict, Any, Set
from datetime import datetime
import hashlib


def hash_quote(quote: str, max_length: int = 100) -> str:
    """
    计算引用的哈希值用于去重

    参数:
    - quote: 引用文本
    - max_length: 用于计算哈希的最大字符数

    返回: 哈希字符串
    """
    # 取前 max_length 个字符，去除空白后计算哈希
    normalized = quote[:max_length].strip().lower()
    return hashlib.md5(normalized.encode('utf-8')).hexdigest()


def merge_chunk_analyses(chunk_analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    合并所有 chunk 的分析结果，按 L-1 四大标准分类
    保持文档级别索引，便于精确引用

    参数:
    - chunk_analyses: Chunk 分析结果列表
      每个元素格式: {
        "chunk_id": str,
        "document_id": str,
        "exhibit_id": str,
        "quotes": [...]
      }

    返回: 按标准分类的汇总结果
    """
    merged = {
        "qualifying_relationship": [],  # 标准1: 合格的公司关系
        "qualifying_employment": [],     # 标准2: 海外合格任职
        "qualifying_capacity": [],       # 标准3: 合格的职位性质
        "doing_business": [],            # 标准4: 持续运营
        "other": []                       # 其他/未分类
    }

    seen_quotes: Set[str] = set()  # 用于去重

    for chunk_result in chunk_analyses:
        quotes = chunk_result.get("quotes", [])

        for item in quotes:
            quote_text = item.get("quote", "")
            if not quote_text:
                continue

            # 计算哈希去重
            quote_hash = hash_quote(quote_text)
            if quote_hash in seen_quotes:
                continue
            seen_quotes.add(quote_hash)

            # 获取标准 key
            standard_key = item.get("standard_key", "other")
            if standard_key not in merged:
                standard_key = "other"

            # 添加到对应分类
            merged[standard_key].append({
                "quote": quote_text,
                "standard": item.get("standard", ""),
                "standard_en": item.get("standard_en", ""),
                "relevance": item.get("relevance", ""),
                # 保持完整的文档来源信息 (关键!)
                "source": item.get("source", {})
            })

    return merged


def format_citation(source: Dict[str, Any]) -> str:
    """
    将源信息格式化为法律文书引用格式

    参数:
    - source: 来源信息 {exhibit_id, file_name, chunk_index, total_chunks}

    返回: 格式化的引用字符串
    """
    exhibit_id = source.get("exhibit_id", "X")
    file_name = source.get("file_name", "Document")
    total_chunks = source.get("total_chunks", 1)
    chunk_index = source.get("chunk_index", 1)

    # 如果文档只有1个chunk，不显示chunk信息
    if total_chunks == 1:
        return f"[Exhibit {exhibit_id}: {file_name}]"
    else:
        return f"[Exhibit {exhibit_id}, Part {chunk_index}: {file_name}]"


def generate_summary(
    merged: Dict[str, List[Dict[str, Any]]],
    project_id: str
) -> Dict[str, Any]:
    """
    生成完整的汇总报告

    参数:
    - merged: merge_chunk_analyses 的输出
    - project_id: 项目 ID

    返回: 完整的汇总报告
    """
    # 计算统计信息
    total_quotes = sum(len(quotes) for quotes in merged.values())

    # 按文档统计
    by_document: Dict[str, int] = {}
    for standard_quotes in merged.values():
        for item in standard_quotes:
            source = item.get("source", {})
            exhibit_id = source.get("exhibit_id", "unknown")
            by_document[exhibit_id] = by_document.get(exhibit_id, 0) + 1

    return {
        "project_id": project_id,
        "summary_timestamp": datetime.utcnow().isoformat(),
        "total_quotes": total_quotes,
        "by_standard": merged,
        "statistics": {
            "qualifying_relationship": len(merged.get("qualifying_relationship", [])),
            "qualifying_employment": len(merged.get("qualifying_employment", [])),
            "qualifying_capacity": len(merged.get("qualifying_capacity", [])),
            "doing_business": len(merged.get("doing_business", [])),
            "other": len(merged.get("other", []))
        },
        "by_document": by_document
    }


def get_quotes_for_standard(
    merged: Dict[str, List[Dict[str, Any]]],
    standard_key: str
) -> List[Dict[str, Any]]:
    """
    获取特定标准的所有引用

    参数:
    - merged: merge_chunk_analyses 的输出
    - standard_key: 标准 key

    返回: 该标准下的所有引用
    """
    return merged.get(standard_key, [])


def get_quotes_for_document(
    merged: Dict[str, List[Dict[str, Any]]],
    exhibit_id: str
) -> List[Dict[str, Any]]:
    """
    获取特定文档的所有引用

    参数:
    - merged: merge_chunk_analyses 的输出
    - exhibit_id: 证据编号

    返回: 该文档的所有引用
    """
    result = []
    for standard_quotes in merged.values():
        for item in standard_quotes:
            source = item.get("source", {})
            if source.get("exhibit_id") == exhibit_id:
                result.append(item)
    return result


def derive_descriptive_title(file_name: str) -> str:
    """
    从文件名推断描述性标题，用于专业法律引用格式

    参数:
    - file_name: 原始文件名 (e.g., "Exhibit B-2.pdf", "business_plan.pdf")

    返回: 描述性标题 (e.g., "Business Plan", "Certificate of Incorporation")
    """
    # 常见文件名到描述性标题的映射
    title_mappings = {
        # 公司注册和结构文件
        "certificate of incorporation": "Certificate of Incorporation",
        "articles of incorporation": "Articles of Incorporation",
        "certificate of formation": "Certificate of Formation",
        "business license": "Business License",
        "business registration": "Business Registration Certificate",
        "company registration": "Company Registration Certificate",
        "dos filing": "NYS DOS Filing Receipt",
        "nys dos": "NYS DOS Filing Receipt",
        "ein": "IRS EIN Confirmation",
        "ein letter": "IRS EIN Confirmation Letter",

        # 所有权文件
        "stock certificate": "Stock Certificate",
        "share certificate": "Share Certificate",
        "ownership": "Ownership Documentation",
        "shareholder": "Shareholder Agreement",
        "stock ledger": "Stock Ledger",
        "capitalization": "Capitalization Table",
        "equity": "Equity Documentation",

        # 商业计划和财务
        "business plan": "Business Plan",
        "financial statement": "Financial Statements",
        "financial report": "Financial Report",
        "tax return": "Tax Return",
        "bank statement": "Bank Statements",
        "profit and loss": "Profit & Loss Statement",
        "balance sheet": "Balance Sheet",
        "income statement": "Income Statement",
        "payroll": "Payroll Records",
        "payroll journal": "Payroll Journal",

        # 组织结构
        "org chart": "Organizational Chart",
        "organizational chart": "Organizational Chart",
        "organization chart": "Organizational Chart",
        "hierarchy": "Organizational Hierarchy",

        # 办公和运营
        "lease": "Commercial Lease Agreement",
        "commercial lease": "Commercial Lease Agreement",
        "office lease": "Office Lease Agreement",
        "rental agreement": "Rental Agreement",
        "utility bill": "Utility Bill",
        "invoice": "Commercial Invoice",
        "contract": "Business Contract",
        "agreement": "Business Agreement",

        # 员工相关
        "employment letter": "Employment Verification Letter",
        "offer letter": "Employment Offer Letter",
        "employment contract": "Employment Contract",
        "resume": "Resume/CV",
        "cv": "Curriculum Vitae",
        "job description": "Position Description",
        "position description": "Position Description",

        # 身份文件
        "passport": "Passport",
        "visa": "Visa Documentation",
        "i-94": "I-94 Arrival Record",

        # 海外公司文件
        "foreign": "Foreign Company Documentation",
        "parent company": "Parent Company Documentation",
        "subsidiary": "Subsidiary Documentation",
    }

    if not file_name:
        return "Document"

    # 清理文件名：移除扩展名和 Exhibit 前缀
    import re
    clean_name = file_name.lower()
    clean_name = re.sub(r'\.(pdf|doc|docx|jpg|jpeg|png|xlsx|xls)$', '', clean_name)
    clean_name = re.sub(r'^exhibit[-_\s]*[a-z]?[-_]?\d*[-_\s]*', '', clean_name)
    clean_name = clean_name.strip(' -_')

    # 尝试直接匹配
    for pattern, title in title_mappings.items():
        if pattern in clean_name:
            return title

    # 如果没有匹配，清理并返回文件名（首字母大写）
    if clean_name:
        # 将下划线和连字符替换为空格，并首字母大写
        readable = clean_name.replace('_', ' ').replace('-', ' ')
        return ' '.join(word.capitalize() for word in readable.split())

    return "Supporting Document"


def format_citation_with_title(source: Dict[str, Any]) -> str:
    """
    格式化引用，使用描述性标题而非文件名

    参数:
    - source: 来源信息

    返回: 格式化的引用字符串，使用描述性标题
    """
    exhibit_id = source.get("exhibit_id", "X")
    file_name = source.get("file_name", "Document")
    descriptive_title = derive_descriptive_title(file_name)

    return f"[Exhibit {exhibit_id}: {descriptive_title}]"


def prepare_for_writing(
    merged: Dict[str, List[Dict[str, Any]]],
    section_type: str
) -> Dict[str, Any]:
    """
    为撰写层准备证据材料

    增强版本：
    - 使用描述性标题而非原始文件名
    - 提供证据丰富度统计
    - 支持跨标准聚合相关证据

    参数:
    - merged: merge_chunk_analyses 的输出
    - section_type: 撰写章节类型

    返回: 准备好的证据材料，包含证据丰富度元数据
    """
    # 根据章节类型选择相关标准
    section_to_standards = {
        "company_relationship": ["qualifying_relationship"],
        "qualifying_relationship": ["qualifying_relationship"],  # 支持两种命名
        "employment_history": ["qualifying_employment"],
        "qualifying_employment": ["qualifying_employment"],
        "executive_capacity": ["qualifying_capacity"],
        "managerial_capacity": ["qualifying_capacity"],
        "specialized_knowledge": ["qualifying_capacity"],
        "qualifying_capacity": ["qualifying_capacity"],
        "doing_business": ["doing_business"],
        "general": ["qualifying_relationship", "qualifying_employment", "qualifying_capacity", "doing_business"]
    }

    relevant_standards = section_to_standards.get(section_type, ["qualifying_relationship", "qualifying_employment", "qualifying_capacity", "doing_business"])

    # 收集相关引用，并跟踪证据丰富度
    relevant_quotes = []
    unique_exhibits = set()
    data_types_found = {
        "dates": False,
        "percentages": False,
        "dollar_amounts": False,
        "headcounts": False
    }

    import re

    for standard_key in relevant_standards:
        quotes = merged.get(standard_key, [])
        for q in quotes:
            source = q.get("source", {})
            exhibit_id = source.get("exhibit_id", "")
            file_name = source.get("file_name", "")
            quote_text = q.get("quote", "")

            # 跟踪唯一 Exhibit
            if exhibit_id:
                unique_exhibits.add(exhibit_id)

            # 检测数据类型（用于丰富度评估）
            if quote_text:
                # 日期检测 (多种格式)
                if re.search(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b|\b\d{4}\b', quote_text):
                    data_types_found["dates"] = True
                # 百分比检测
                if re.search(r'\d+\.?\d*\s*%|\bpercent\b', quote_text, re.IGNORECASE):
                    data_types_found["percentages"] = True
                # 金额检测
                if re.search(r'\$\s*[\d,]+\.?\d*|\b\d+[\d,]*\s*(USD|dollars?)\b', quote_text, re.IGNORECASE):
                    data_types_found["dollar_amounts"] = True
                # 人数检测
                if re.search(r'\b\d+\s*(employee|staff|worker|personnel|people|person)s?\b', quote_text, re.IGNORECASE):
                    data_types_found["headcounts"] = True

            # 生成描述性标题
            descriptive_title = derive_descriptive_title(file_name)

            relevant_quotes.append({
                **q,
                "formatted_citation": format_citation_with_title(source),
                "descriptive_title": descriptive_title,
                "source": {
                    **source,
                    "descriptive_title": descriptive_title
                }
            })

    # 计算证据丰富度评分
    richness_score = len(unique_exhibits) + sum(1 for v in data_types_found.values() if v)
    richness_level = "low" if richness_score < 3 else ("medium" if richness_score < 5 else "high")

    return {
        "section_type": section_type,
        "relevant_standards": relevant_standards,
        "quotes": relevant_quotes,
        "quote_count": len(relevant_quotes),
        # 新增：证据丰富度元数据
        "evidence_metadata": {
            "unique_exhibit_count": len(unique_exhibits),
            "unique_exhibits": list(unique_exhibits),
            "data_types_found": data_types_found,
            "richness_score": richness_score,
            "richness_level": richness_level
        }
    }
