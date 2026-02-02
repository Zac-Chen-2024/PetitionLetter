"""
Highlight Analyzer Service - 高光分析服务 v2.0

功能：
对每个独立材料进行预处理和关键信息标记

高光分析内容：
1. 基础信息提取（日期、标题、当事人、文档类型）
2. 关键内容标记（重要条款、关键数字、核心陈述）

输出用途：
1. 作为 L1 分析的参考输入 - 帮助 L1 更准确地提取引用
2. 在前端 PDF 上显示 - 用不同颜色区分高光分析标记和 L1 引用标记

颜色设计：
- 高光分析-基础信息: 蓝色
- 高光分析-关键内容: 绿色
- L1引用: 黄色
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json
import re
import asyncio

from app.services.material_splitter import Material, MaterialPage
from app.services import bbox_matcher


# =============================================
# 数据结构定义
# =============================================

@dataclass
class Highlight:
    """单个高光标记"""
    text: str
    highlight_type: str  # "basic_info" | "key_content"
    category: str  # document_type, date, party, title, amount, clause, statement, etc.
    page: int
    bbox: Optional[Dict[str, int]] = None  # {x1, y1, x2, y2}
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "highlight_type": self.highlight_type,
            "category": self.category,
            "page": self.page,
            "bbox": self.bbox,
            "confidence": self.confidence,
            "reason": self.reason
        }


@dataclass
class MaterialMetadata:
    """材料的结构化元数据"""
    document_type: str
    title: str
    date: Optional[str] = None
    parties: List[str] = field(default_factory=list)
    key_points_summary: List[str] = field(default_factory=list)
    language: str = "en"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_type": self.document_type,
            "title": self.title,
            "date": self.date,
            "parties": self.parties,
            "key_points_summary": self.key_points_summary,
            "language": self.language
        }


@dataclass
class HighlightResult:
    """高光分析结果"""
    material_id: str
    metadata: MaterialMetadata
    highlights: List[Highlight] = field(default_factory=list)
    analyzed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "material_id": self.material_id,
            "metadata": self.metadata.to_dict(),
            "highlights": [h.to_dict() for h in self.highlights],
            "analyzed_at": self.analyzed_at.isoformat() if self.analyzed_at else None
        }


# =============================================
# 高光类别定义
# =============================================

# 基础信息类别
BASIC_INFO_CATEGORIES = {
    "document_type": "文档类型",
    "date": "日期",
    "title": "标题",
    "party": "当事人",
    "address": "地址",
    "signature": "签名",
}

# 关键内容类别
KEY_CONTENT_CATEGORIES = {
    "amount": "金额数字",
    "clause": "重要条款",
    "statement": "核心陈述",
    "term": "期限/期间",
    "position": "职位",
    "duty": "职责",
    "requirement": "要求/条件",
}


# =============================================
# LLM 高光分析 Prompt
# =============================================

HIGHLIGHT_ANALYSIS_PROMPT = """分析以下文档材料，提取基础信息和关键内容。

## 材料信息
- 材料ID: {material_id}
- 页码范围: {page_range}
- 初步类型: {material_type}

## 文档内容
{document_text}

## 任务

### 1. 提取基础信息 (basic_info)
识别以下信息并标记原文：
- document_type: 文档类型（如 employment_contract, email, invoice 等）
- date: 文档日期
- title: 文档标题
- party: 当事人（公司名、人名）
- address: 地址
- signature: 签名

### 2. 标记关键内容 (key_content)
识别以下重要信息并标记原文：
- amount: 金额数字（工资、费用、收入等）
- clause: 重要条款（合同关键条款、责任条款等）
- statement: 核心陈述（关键事实、重要声明）
- term: 期限/期间（合同期限、工作年限等）
- position: 职位（职位名称、管理级别）
- duty: 职责（工作职责、管理权限）
- requirement: 要求/条件（资格要求、履行条件）

## 输出格式
```json
{{
  "metadata": {{
    "document_type": "employment_contract",
    "title": "Employment Agreement",
    "date": "2024-01-15",
    "parties": ["ABC Corporation", "John Smith"],
    "key_points_summary": [
      "年薪 $150,000",
      "管理 5 名员工",
      "合同期限 3 年"
    ],
    "language": "en"
  }},
  "highlights": [
    {{
      "text": "EXACT text from document",
      "highlight_type": "basic_info",
      "category": "date",
      "page": 1,
      "reason": "文档签署日期"
    }},
    {{
      "text": "EXACT text from document",
      "highlight_type": "key_content",
      "category": "amount",
      "page": 2,
      "reason": "年薪金额"
    }}
  ]
}}
```

## 关键要求
1. **text 必须是原文精确复制**，不要改写或总结
2. 每个高光标记都要有明确的 reason
3. 优先标记对 L-1 签证申请有证明价值的内容
4. 基础信息不超过 10 条，关键内容不超过 20 条
"""


# =============================================
# 分析函数
# =============================================

async def analyze_material_highlights(
    material: Material,
    call_llm_func,
    text_blocks: Optional[List[Dict[str, Any]]] = None
) -> HighlightResult:
    """
    对单个材料进行高光分析

    Args:
        material: 材料对象
        call_llm_func: LLM 调用函数
        text_blocks: 用于 bbox 匹配的 text_blocks（可选）

    Returns:
        HighlightResult 包含 metadata 和 highlights
    """
    # 获取材料全文
    full_text = material.get_full_text()

    # 如果未提供 text_blocks，从材料页面中收集
    if text_blocks is None:
        text_blocks = material.get_all_text_blocks()

    # 构建 prompt
    prompt = HIGHLIGHT_ANALYSIS_PROMPT.format(
        material_id=material.material_id,
        page_range=material.page_range,
        material_type=material.material_type,
        document_text=full_text[:15000]  # 限制长度
    )

    try:
        # 调用 LLM
        llm_result = await call_llm_func(prompt, max_retries=2)

        # 解析结果
        metadata_data = llm_result.get("metadata", {})
        highlights_data = llm_result.get("highlights", [])

        # 创建 metadata
        metadata = MaterialMetadata(
            document_type=metadata_data.get("document_type", material.material_type),
            title=metadata_data.get("title", material.title),
            date=metadata_data.get("date", material.date),
            parties=metadata_data.get("parties", []),
            key_points_summary=metadata_data.get("key_points_summary", []),
            language=metadata_data.get("language", "en")
        )

        # 创建 highlights 并匹配 bbox
        highlights = []
        for h_data in highlights_data:
            text = h_data.get("text", "")
            page = h_data.get("page", material.start_page)

            # 尝试匹配 bbox
            bbox = None
            if text and text_blocks:
                bbox = _match_text_to_bbox(text, text_blocks, page)

            highlight = Highlight(
                text=text,
                highlight_type=h_data.get("highlight_type", "key_content"),
                category=h_data.get("category", "other"),
                page=page,
                bbox=bbox,
                confidence=0.8 if bbox else 0.5,
                reason=h_data.get("reason", "")
            )
            highlights.append(highlight)

        return HighlightResult(
            material_id=material.material_id,
            metadata=metadata,
            highlights=highlights,
            analyzed_at=datetime.utcnow()
        )

    except Exception as e:
        print(f"[HighlightAnalyzer] Error analyzing {material.material_id}: {e}")
        # 返回基础结果
        return HighlightResult(
            material_id=material.material_id,
            metadata=MaterialMetadata(
                document_type=material.material_type,
                title=material.title,
                date=material.date
            ),
            highlights=[],
            analyzed_at=datetime.utcnow()
        )


class _TextBlockWrapper:
    """Wrapper to make dict look like TextBlock ORM object for bbox_matcher"""
    def __init__(self, block_dict: Dict[str, Any]):
        self.block_id = block_dict.get("block_id", "")
        self.page_number = block_dict.get("page_number", 1)
        self.text_content = block_dict.get("text", block_dict.get("text_content", ""))

        # Handle bbox - can be dict or individual fields
        bbox = block_dict.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            self.bbox_x1, self.bbox_y1, self.bbox_x2, self.bbox_y2 = bbox
        elif isinstance(bbox, dict):
            self.bbox_x1 = bbox.get("x1", 0)
            self.bbox_y1 = bbox.get("y1", 0)
            self.bbox_x2 = bbox.get("x2", 0)
            self.bbox_y2 = bbox.get("y2", 0)
        else:
            self.bbox_x1 = block_dict.get("bbox_x1", 0)
            self.bbox_y1 = block_dict.get("bbox_y1", 0)
            self.bbox_x2 = block_dict.get("bbox_x2", 0)
            self.bbox_y2 = block_dict.get("bbox_y2", 0)


def _match_text_to_bbox(
    search_text: str,
    text_blocks: List[Dict[str, Any]],
    page_hint: Optional[int] = None,
    similarity_threshold: float = 0.6
) -> Optional[Dict[str, int]]:
    """
    将文本匹配到 bbox 坐标

    Args:
        search_text: 要匹配的文本
        text_blocks: text_block 列表 (dicts)
        page_hint: 页码提示
        similarity_threshold: 匹配阈值

    Returns:
        bbox 字典或 None
    """
    if not search_text or not text_blocks:
        return None

    try:
        # Convert dicts to wrapper objects for bbox_matcher
        wrapped_blocks = [_TextBlockWrapper(b) for b in text_blocks]

        # 使用 bbox_matcher 进行匹配
        match_result = bbox_matcher.match_text_to_blocks(
            search_text=search_text,
            text_blocks=wrapped_blocks,
            page_hint=page_hint,
            similarity_threshold=similarity_threshold
        )

        if match_result.get("matched") and match_result.get("matches"):
            best_match = match_result["matches"][0]
            return best_match.get("bbox")

    except Exception as e:
        print(f"[HighlightAnalyzer] Bbox match failed: {e}")

    return None


async def analyze_material_highlights_simple(
    material: Material
) -> HighlightResult:
    """
    简单的规则高光分析（无 LLM）

    用于降级或快速预览场景
    """
    full_text = material.get_full_text()

    # 提取基础信息
    metadata = _extract_metadata_with_rules(full_text, material)

    # 提取关键内容
    highlights = _extract_highlights_with_rules(full_text, material)

    return HighlightResult(
        material_id=material.material_id,
        metadata=metadata,
        highlights=highlights,
        analyzed_at=datetime.utcnow()
    )


def _extract_metadata_with_rules(text: str, material: Material) -> MaterialMetadata:
    """使用规则提取元数据"""
    # 提取日期
    date = None
    date_patterns = [
        r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b',
        r'\b(\w+\s+\d{1,2},?\s+\d{4})\b',
        r'\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b',
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text[:2000])
        if match:
            date = match.group(1)
            break

    # 提取当事人（公司名或人名）
    parties = []
    # 常见公司后缀
    company_pattern = r'\b([A-Z][A-Za-z\s&]+(?:Inc\.|LLC|Ltd\.|Corp\.|Corporation|Company|Co\.))\b'
    companies = re.findall(company_pattern, text[:3000])
    parties.extend(list(set(companies))[:5])

    # 提取标题
    title = material.title
    lines = text.split('\n')[:10]
    for line in lines:
        line = line.strip()
        if 15 < len(line) < 80 and (line.isupper() or line[0].isupper()):
            title = line
            break

    return MaterialMetadata(
        document_type=material.material_type,
        title=title,
        date=date or material.date,
        parties=parties,
        key_points_summary=[],
        language="en"
    )


def _extract_highlights_with_rules(text: str, material: Material) -> List[Highlight]:
    """使用规则提取高光标记"""
    highlights = []

    # 金额模式
    amount_pattern = r'\$[\d,]+(?:\.\d{2})?|\d{1,3}(?:,\d{3})+(?:\.\d{2})?'
    for match in re.finditer(amount_pattern, text):
        highlights.append(Highlight(
            text=match.group(),
            highlight_type="key_content",
            category="amount",
            page=material.start_page,
            reason="金额数字"
        ))
        if len(highlights) >= 10:
            break

    # 日期模式
    date_pattern = r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b'
    for match in re.finditer(date_pattern, text[:3000]):
        highlights.append(Highlight(
            text=match.group(),
            highlight_type="basic_info",
            category="date",
            page=material.start_page,
            reason="日期"
        ))
        if len([h for h in highlights if h.category == "date"]) >= 3:
            break

    # 年份/期限模式
    term_pattern = r'\b\d+\s*(?:years?|months?|days?)\b'
    for match in re.finditer(term_pattern, text, re.IGNORECASE):
        highlights.append(Highlight(
            text=match.group(),
            highlight_type="key_content",
            category="term",
            page=material.start_page,
            reason="期限"
        ))
        if len([h for h in highlights if h.category == "term"]) >= 5:
            break

    return highlights


# =============================================
# 批量分析
# =============================================

async def analyze_all_materials(
    materials: List[Material],
    call_llm_func,
    use_llm: bool = True
) -> Dict[str, HighlightResult]:
    """
    批量分析所有材料

    Args:
        materials: 材料列表
        call_llm_func: LLM 调用函数
        use_llm: 是否使用 LLM

    Returns:
        {material_id: HighlightResult}
    """
    results = {}

    for material in materials:
        print(f"[HighlightAnalyzer] Analyzing {material.material_id}...")

        if use_llm and call_llm_func:
            result = await analyze_material_highlights(material, call_llm_func)
        else:
            result = await analyze_material_highlights_simple(material)

        results[material.material_id] = result

        # 间隔避免速率限制
        if use_llm:
            await asyncio.sleep(0.5)

    return results


# =============================================
# 存储函数
# =============================================

def save_highlight_results(
    project_id: str,
    results: Dict[str, HighlightResult]
):
    """保存高光分析结果"""
    base_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    highlights_dir = base_dir / project_id / "highlights"
    highlights_dir.mkdir(parents=True, exist_ok=True)

    for material_id, result in results.items():
        result_path = highlights_dir / f"{material_id}_highlights.json"
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

    print(f"[HighlightAnalyzer] Saved {len(results)} highlight results")


def load_highlight_result(project_id: str, material_id: str) -> Optional[HighlightResult]:
    """加载单个材料的高光分析结果"""
    base_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    result_path = base_dir / project_id / "highlights" / f"{material_id}_highlights.json"

    if not result_path.exists():
        return None

    with open(result_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    metadata = MaterialMetadata(
        document_type=data["metadata"]["document_type"],
        title=data["metadata"]["title"],
        date=data["metadata"].get("date"),
        parties=data["metadata"].get("parties", []),
        key_points_summary=data["metadata"].get("key_points_summary", []),
        language=data["metadata"].get("language", "en")
    )

    highlights = [
        Highlight(
            text=h["text"],
            highlight_type=h["highlight_type"],
            category=h["category"],
            page=h["page"],
            bbox=h.get("bbox"),
            confidence=h.get("confidence", 0.5),
            reason=h.get("reason", "")
        )
        for h in data.get("highlights", [])
    ]

    return HighlightResult(
        material_id=data["material_id"],
        metadata=metadata,
        highlights=highlights,
        analyzed_at=datetime.fromisoformat(data["analyzed_at"]) if data.get("analyzed_at") else None
    )


def load_all_highlight_results(project_id: str) -> Dict[str, HighlightResult]:
    """加载项目所有高光分析结果"""
    base_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    highlights_dir = base_dir / project_id / "highlights"

    if not highlights_dir.exists():
        return {}

    results = {}
    for f in highlights_dir.iterdir():
        if f.name.endswith("_highlights.json"):
            material_id = f.name.replace("_highlights.json", "")
            result = load_highlight_result(project_id, material_id)
            if result:
                results[material_id] = result

    return results


# =============================================
# 辅助函数：为 L1 分析准备高光上下文
# =============================================

def get_highlight_context_for_l1(highlight_result: HighlightResult) -> str:
    """
    将高光分析结果转换为 L1 分析的上下文字符串

    Args:
        highlight_result: 高光分析结果

    Returns:
        上下文描述字符串
    """
    metadata = highlight_result.metadata

    context_parts = [
        f"**Document Type:** {metadata.document_type}",
        f"**Title:** {metadata.title}",
    ]

    if metadata.date:
        context_parts.append(f"**Date:** {metadata.date}")

    if metadata.parties:
        context_parts.append(f"**Parties:** {', '.join(metadata.parties)}")

    if metadata.key_points_summary:
        context_parts.append("**Key Points:**")
        for point in metadata.key_points_summary[:5]:
            context_parts.append(f"  - {point}")

    # 添加已识别的关键内容提示
    key_highlights = [h for h in highlight_result.highlights if h.highlight_type == "key_content"]
    if key_highlights:
        context_parts.append("\n**Pre-identified Key Content:**")
        for h in key_highlights[:10]:
            context_parts.append(f"  - [{h.category}] {h.text[:100]}...")

    return "\n".join(context_parts)
