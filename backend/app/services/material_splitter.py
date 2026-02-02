"""
Material Splitter Service - 材料分割服务

功能：
将 Exhibit PDF 拆分为独立材料（合同、邮件、发票等）

分割信号：
1. 文档类型变化（合同 → 邮件）
2. 首页特征（大标题、日期、抬头）
3. 格式变化（布局、字体、页眉页脚）
4. 明确分隔（空白页、分隔页）

输出：
Material 数据结构，包含：
- material_id: 材料唯一标识
- exhibit_id: 所属 Exhibit
- page_range: 页码范围
- material_type: 材料类型
- title: 识别出的标题
- date: 识别出的日期
- pages: 该材料包含的页面数据
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import json
import re
import asyncio


# =============================================
# 数据结构定义
# =============================================

@dataclass
class MaterialPage:
    """材料内的单页"""
    page_number: int
    text: str
    text_blocks: List[Dict[str, Any]] = field(default_factory=list)
    char_count: int = 0


@dataclass
class Material:
    """独立材料"""
    material_id: str
    exhibit_id: str
    document_id: str
    file_name: str
    page_range: str  # 如 "1-5" 或 "3"
    start_page: int
    end_page: int
    material_type: str  # contract, email, invoice, org_chart, financial, etc.
    title: str
    date: Optional[str] = None
    confidence: str = "medium"  # high, medium, low
    pages: List[MaterialPage] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（排除页面内容以减小存储）"""
        return {
            "material_id": self.material_id,
            "exhibit_id": self.exhibit_id,
            "document_id": self.document_id,
            "file_name": self.file_name,
            "page_range": self.page_range,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "material_type": self.material_type,
            "title": self.title,
            "date": self.date,
            "confidence": self.confidence,
            "page_count": len(self.pages),
            "total_chars": sum(p.char_count for p in self.pages)
        }

    def get_full_text(self) -> str:
        """获取材料的完整文本"""
        return "\n\n".join(p.text for p in self.pages)

    def get_all_text_blocks(self) -> List[Dict[str, Any]]:
        """获取材料所有的 text_blocks"""
        all_blocks = []
        for page in self.pages:
            all_blocks.extend(page.text_blocks)
        return all_blocks


# =============================================
# 材料类型定义
# =============================================

MATERIAL_TYPE_PATTERNS = {
    # (类型key, 正则模式, 中文描述, 权重)
    "employment_contract": (
        r"(?i)(employment\s*(agreement|contract)|offer\s*letter|appointment\s*letter)",
        "雇佣合同/聘用函",
        10
    ),
    "business_contract": (
        r"(?i)(agreement|contract|memorandum\s*of\s*understanding|MOU)",
        "商业合同/协议",
        5
    ),
    "email": (
        r"(?i)(from:\s*|to:\s*|subject:\s*|sent:\s*|date:\s*.*\d{1,2}[:/]\d{1,2})",
        "电子邮件",
        8
    ),
    "invoice": (
        r"(?i)(invoice|bill\s*to|total\s*(amount|due)|payment\s*terms)",
        "发票",
        9
    ),
    "org_chart": (
        r"(?i)(org(anization(al)?)?\s*chart|reporting\s*structure|hierarchy)",
        "组织架构图",
        9
    ),
    "financial_statement": (
        r"(?i)(financial\s*statement|balance\s*sheet|income\s*statement|profit\s*(and|&)\s*loss)",
        "财务报表",
        8
    ),
    "tax_form": (
        r"(?i)(form\s*1120|form\s*941|form\s*w-2|irs|internal\s*revenue)",
        "税务表格",
        10
    ),
    "business_plan": (
        r"(?i)(business\s*plan|executive\s*summary|market\s*analysis)",
        "商业计划书",
        7
    ),
    "corporate_document": (
        r"(?i)(articles\s*of\s*(incorporation|organization)|bylaws|certificate|resolution)",
        "公司文件",
        8
    ),
    "letter": (
        r"(?i)(dear\s+(mr|ms|mrs|sir|madam)|sincerely|regards|yours\s*(truly|faithfully))",
        "信函",
        6
    ),
    "resume_cv": (
        r"(?i)(resume|curriculum\s*vitae|cv|work\s*experience|education)",
        "简历",
        8
    ),
    "lease": (
        r"(?i)(lease\s*agreement|rental\s*agreement|landlord|tenant)",
        "租赁协议",
        8
    ),
}

# 首页特征模式
FIRST_PAGE_INDICATORS = [
    r"^\s*[A-Z][A-Z\s]{5,}$",  # 全大写标题
    r"(?i)^[\s\n]*(?:agreement|contract|certificate)",  # 开头是文档类型
    r"\bpage\s*1\s*of\s*\d+",  # "Page 1 of N"
    r"(?i)^\s*exhibit\s+[a-z]-?\d+",  # Exhibit 编号
    r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b",  # 日期
]

# 分隔符模式
SEPARATOR_PATTERNS = [
    r"^[\s\n]*$",  # 空白页
    r"^-{10,}$",  # 分隔线
    r"^\*{10,}$",  # 星号分隔
    r"^={10,}$",  # 等号分隔
    r"(?i)^\s*\[?\s*this\s+page\s+(intentionally\s+)?left\s+blank\s*\]?\s*$",  # 空白页说明
]


# =============================================
# 边界检测函数
# =============================================

def detect_material_type(text: str) -> Tuple[str, str, int]:
    """
    检测文本的材料类型

    Returns:
        (type_key, description, confidence_score)
    """
    header_text = text[:2000] if len(text) > 2000 else text

    best_match = ("generic", "通用文档", 0)

    for type_key, (pattern, desc, weight) in MATERIAL_TYPE_PATTERNS.items():
        matches = re.findall(pattern, header_text, re.MULTILINE)
        if matches:
            score = len(matches) * weight
            if score > best_match[2]:
                best_match = (type_key, desc, score)

    return best_match


def is_likely_first_page(text: str, prev_text: Optional[str] = None) -> Tuple[bool, float]:
    """
    判断该页是否可能是新材料的首页

    Returns:
        (is_first_page, confidence)
    """
    confidence = 0.0
    header_text = text[:1000] if len(text) > 1000 else text

    # 检查首页特征
    for pattern in FIRST_PAGE_INDICATORS:
        if re.search(pattern, header_text, re.MULTILINE):
            confidence += 0.2

    # 检查是否有明显的文档标题（前几行有全大写或长标题）
    lines = header_text.split('\n')[:10]
    for line in lines:
        line = line.strip()
        if len(line) > 10 and line.isupper():
            confidence += 0.3
            break
        if len(line) > 20 and line[0].isupper():
            confidence += 0.1

    # 如果有前一页，检查类型变化
    if prev_text:
        curr_type, _, _ = detect_material_type(text)
        prev_type, _, _ = detect_material_type(prev_text)
        if curr_type != prev_type and curr_type != "generic":
            confidence += 0.4

    return confidence >= 0.3, min(confidence, 1.0)


def is_separator_page(text: str) -> bool:
    """检查是否是分隔页"""
    text = text.strip()

    # 空白页
    if len(text) < 50:
        return True

    for pattern in SEPARATOR_PATTERNS:
        if re.match(pattern, text, re.MULTILINE | re.IGNORECASE):
            return True

    return False


def extract_title_and_date(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    从文本中提取标题和日期

    Returns:
        (title, date)
    """
    lines = text.split('\n')[:20]

    title = None
    date = None

    # 提取标题（前几行中最长的有意义的行）
    for line in lines:
        line = line.strip()
        if 10 < len(line) < 100:
            # 跳过日期行
            if re.match(r'^[\d/\-\s:]+$', line):
                continue
            # 跳过页码行
            if re.match(r'(?i)page\s*\d+', line):
                continue
            if not title or (len(line) > len(title) and not line.startswith('•')):
                title = line

    # 提取日期
    date_patterns = [
        r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b',
        r'\b(\w+\s+\d{1,2},?\s+\d{4})\b',  # January 15, 2024
        r'\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b',  # 2024-01-15
    ]

    header_text = text[:1500]
    for pattern in date_patterns:
        match = re.search(pattern, header_text)
        if match:
            date = match.group(1)
            break

    return title, date


# =============================================
# LLM 边界识别
# =============================================

MATERIAL_BOUNDARY_PROMPT = """分析以下 PDF 页面序列，识别独立文档的边界。

## 页面摘要
{pages_summary}

## 任务
识别哪些页面属于同一份独立文档（如一份合同、一封邮件、一份发票）。

## 判断依据
1. 文档类型变化（合同→邮件）
2. 首页特征（标题、日期、抬头）
3. 分隔页（空白页、分隔线）
4. 页眉页脚变化

## 输出格式
```json
{{
  "materials": [
    {{
      "start_page": 1,
      "end_page": 5,
      "type": "employment_contract",
      "title": "Employment Agreement",
      "date": "2024-01-15",
      "confidence": "high"
    }},
    {{
      "start_page": 6,
      "end_page": 7,
      "type": "email",
      "title": "RE: Position Confirmation",
      "date": "2024-01-20",
      "confidence": "high"
    }}
  ]
}}
```

请确保:
- 每一页都被分配到某个材料中
- 不遗漏任何页面
- 相邻页面之间没有断层
"""


def prepare_pages_summary(pages: List[Dict[str, Any]], max_preview: int = 300) -> str:
    """
    准备页面摘要用于 LLM 分析

    Args:
        pages: 页面列表
        max_preview: 每页的最大预览字符数
    """
    summaries = []

    for page in pages:
        page_num = page.get("page_number", 0)
        text = page.get("text", page.get("markdown_text", ""))

        # 提取前几行作为预览
        lines = text.split('\n')[:10]
        preview = '\n'.join(line[:100] for line in lines if line.strip())
        if len(preview) > max_preview:
            preview = preview[:max_preview] + "..."

        # 检测当前页的材料类型
        mat_type, mat_desc, score = detect_material_type(text)

        summaries.append(f"--- Page {page_num} ---\n[Type hint: {mat_desc}]\n{preview}")

    return "\n\n".join(summaries)


async def split_with_llm(
    pages: List[Dict[str, Any]],
    call_llm_func,
    exhibit_id: str,
    document_id: str,
    file_name: str
) -> List[Material]:
    """
    使用 LLM 进行材料分割

    Args:
        pages: OCR 页面数据
        call_llm_func: LLM 调用函数
        exhibit_id: Exhibit ID
        document_id: 文档 ID
        file_name: 文件名

    Returns:
        材料列表
    """
    if not pages:
        return []

    # 准备页面摘要
    pages_summary = prepare_pages_summary(pages)

    # 构建 prompt
    prompt = MATERIAL_BOUNDARY_PROMPT.format(pages_summary=pages_summary)

    try:
        # 调用 LLM
        llm_result = await call_llm_func(prompt, max_retries=2)

        # 解析结果
        materials_data = llm_result.get("materials", [])

        if not materials_data:
            # LLM 未返回结果，使用规则分割
            print(f"[MaterialSplitter] LLM returned no materials, falling back to rule-based")
            return await split_with_rules(pages, exhibit_id, document_id, file_name)

        # 创建 Material 对象
        materials = []
        for i, mat_data in enumerate(materials_data):
            start_page = mat_data.get("start_page", 1)
            end_page = mat_data.get("end_page", start_page)

            # 收集该材料的页面
            mat_pages = []
            for page in pages:
                page_num = page.get("page_number", 0)
                if start_page <= page_num <= end_page:
                    text = page.get("text", page.get("markdown_text", ""))
                    text_blocks = page.get("text_blocks", [])
                    mat_pages.append(MaterialPage(
                        page_number=page_num,
                        text=text,
                        text_blocks=text_blocks,
                        char_count=len(text)
                    ))

            page_range = f"{start_page}" if start_page == end_page else f"{start_page}-{end_page}"

            material = Material(
                material_id=f"{exhibit_id}_m{i+1}",
                exhibit_id=exhibit_id,
                document_id=document_id,
                file_name=file_name,
                page_range=page_range,
                start_page=start_page,
                end_page=end_page,
                material_type=mat_data.get("type", "generic"),
                title=mat_data.get("title", f"Material {i+1}"),
                date=mat_data.get("date"),
                confidence=mat_data.get("confidence", "medium"),
                pages=mat_pages
            )
            materials.append(material)

        return materials

    except Exception as e:
        print(f"[MaterialSplitter] LLM split failed: {e}, falling back to rule-based")
        return await split_with_rules(pages, exhibit_id, document_id, file_name)


# =============================================
# 规则分割（无 LLM 降级方案）
# =============================================

async def split_with_rules(
    pages: List[Dict[str, Any]],
    exhibit_id: str,
    document_id: str,
    file_name: str
) -> List[Material]:
    """
    使用规则进行材料分割（无 LLM 降级方案）
    """
    if not pages:
        return []

    # 按页码排序
    sorted_pages = sorted(pages, key=lambda p: p.get("page_number", 0))

    # 检测边界
    boundaries = [0]  # 第一页总是边界

    for i in range(1, len(sorted_pages)):
        page = sorted_pages[i]
        prev_page = sorted_pages[i - 1]

        page_text = page.get("text", page.get("markdown_text", ""))
        prev_text = prev_page.get("text", prev_page.get("markdown_text", ""))

        # 检查分隔页
        if is_separator_page(prev_text):
            boundaries.append(i)
            continue

        # 检查首页特征
        is_first, conf = is_likely_first_page(page_text, prev_text)
        if is_first and conf >= 0.5:
            boundaries.append(i)
            continue

        # 检查材料类型变化
        curr_type, _, curr_score = detect_material_type(page_text)
        prev_type, _, _ = detect_material_type(prev_text)

        if curr_type != prev_type and curr_type != "generic" and curr_score >= 8:
            boundaries.append(i)

    # 根据边界创建材料
    materials = []
    boundaries.append(len(sorted_pages))  # 添加结束边界

    for i in range(len(boundaries) - 1):
        start_idx = boundaries[i]
        end_idx = boundaries[i + 1]

        mat_pages = []
        for j in range(start_idx, end_idx):
            page = sorted_pages[j]
            page_num = page.get("page_number", j + 1)
            text = page.get("text", page.get("markdown_text", ""))
            text_blocks = page.get("text_blocks", [])

            mat_pages.append(MaterialPage(
                page_number=page_num,
                text=text,
                text_blocks=text_blocks,
                char_count=len(text)
            ))

        if not mat_pages:
            continue

        # 获取材料的全文用于类型检测
        full_text = "\n\n".join(p.text for p in mat_pages)
        mat_type, mat_desc, _ = detect_material_type(full_text)
        title, date = extract_title_and_date(full_text)

        start_page = mat_pages[0].page_number
        end_page = mat_pages[-1].page_number
        page_range = f"{start_page}" if start_page == end_page else f"{start_page}-{end_page}"

        material = Material(
            material_id=f"{exhibit_id}_m{i+1}",
            exhibit_id=exhibit_id,
            document_id=document_id,
            file_name=file_name,
            page_range=page_range,
            start_page=start_page,
            end_page=end_page,
            material_type=mat_type,
            title=title or f"Material {i+1}",
            date=date,
            confidence="medium",
            pages=mat_pages
        )
        materials.append(material)

    return materials


# =============================================
# 主入口函数
# =============================================

async def split_exhibit_into_materials(
    project_id: str,
    exhibit_id: str,
    document_id: str,
    file_name: str,
    ocr_pages: List[Dict[str, Any]],
    call_llm_func=None,
    use_llm: bool = True
) -> List[Material]:
    """
    将 Exhibit 拆分为独立材料

    Args:
        project_id: 项目 ID
        exhibit_id: Exhibit ID (如 A-3)
        document_id: 文档 ID
        file_name: 文件名
        ocr_pages: OCR 结果，包含每页的文本和 text_blocks
        call_llm_func: LLM 调用函数（可选）
        use_llm: 是否使用 LLM 分割

    Returns:
        材料列表
    """
    if not ocr_pages:
        return []

    print(f"[MaterialSplitter] Splitting {exhibit_id} ({len(ocr_pages)} pages)")

    # 如果只有单页，直接作为一个材料
    if len(ocr_pages) == 1:
        page = ocr_pages[0]
        text = page.get("text", page.get("markdown_text", ""))
        text_blocks = page.get("text_blocks", [])
        mat_type, _, _ = detect_material_type(text)
        title, date = extract_title_and_date(text)

        return [Material(
            material_id=f"{exhibit_id}_m1",
            exhibit_id=exhibit_id,
            document_id=document_id,
            file_name=file_name,
            page_range="1",
            start_page=1,
            end_page=1,
            material_type=mat_type,
            title=title or file_name,
            date=date,
            confidence="high",
            pages=[MaterialPage(
                page_number=1,
                text=text,
                text_blocks=text_blocks,
                char_count=len(text)
            )]
        )]

    # 使用 LLM 或规则分割
    if use_llm and call_llm_func:
        materials = await split_with_llm(
            ocr_pages, call_llm_func, exhibit_id, document_id, file_name
        )
    else:
        materials = await split_with_rules(
            ocr_pages, exhibit_id, document_id, file_name
        )

    print(f"[MaterialSplitter] Split into {len(materials)} materials:")
    for mat in materials:
        print(f"  - {mat.material_id}: {mat.title} (pages {mat.page_range}, type: {mat.material_type})")

    return materials


def load_ocr_pages_for_document(project_id: str, document_id: str) -> List[Dict[str, Any]]:
    """
    从文件系统加载文档的 OCR 页面数据

    Args:
        project_id: 项目 ID
        document_id: 文档 ID

    Returns:
        OCR 页面数据列表
    """
    base_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    pages_dir = base_dir / project_id / "ocr_pages" / document_id

    if not pages_dir.exists():
        return []

    pages = []
    for f in sorted(pages_dir.iterdir()):
        if f.name.startswith("page_") and f.suffix == ".json":
            with open(f) as fp:
                data = json.load(fp)
                pages.append({
                    "page_number": data.get("page_number", 0),
                    "text": data.get("markdown_text", ""),
                    "markdown_text": data.get("markdown_text", ""),
                    "text_blocks": data.get("text_blocks", [])
                })

    return sorted(pages, key=lambda p: p["page_number"])


# =============================================
# 存储函数
# =============================================

def save_materials(project_id: str, exhibit_id: str, materials: List[Material]):
    """
    保存材料分割结果
    """
    base_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    materials_dir = base_dir / project_id / "materials"
    materials_dir.mkdir(parents=True, exist_ok=True)

    # 保存材料列表（不含页面内容）
    materials_index = {
        "exhibit_id": exhibit_id,
        "split_at": datetime.utcnow().isoformat(),
        "total_materials": len(materials),
        "materials": [mat.to_dict() for mat in materials]
    }

    index_path = materials_dir / f"{exhibit_id}_materials.json"
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(materials_index, f, ensure_ascii=False, indent=2)

    # 保存每个材料的详细数据（含页面内容）
    for mat in materials:
        mat_data = {
            **mat.to_dict(),
            "pages": [
                {
                    "page_number": p.page_number,
                    "text": p.text,
                    "text_blocks": p.text_blocks,
                    "char_count": p.char_count
                }
                for p in mat.pages
            ]
        }
        mat_path = materials_dir / f"{mat.material_id}.json"
        with open(mat_path, 'w', encoding='utf-8') as f:
            json.dump(mat_data, f, ensure_ascii=False, indent=2)

    print(f"[MaterialSplitter] Saved {len(materials)} materials to {materials_dir}")


def load_materials(project_id: str, exhibit_id: str) -> List[Material]:
    """
    加载材料分割结果
    """
    base_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    materials_dir = base_dir / project_id / "materials"
    index_path = materials_dir / f"{exhibit_id}_materials.json"

    if not index_path.exists():
        return []

    with open(index_path, 'r', encoding='utf-8') as f:
        index_data = json.load(f)

    materials = []
    for mat_info in index_data.get("materials", []):
        mat_id = mat_info.get("material_id")
        mat_path = materials_dir / f"{mat_id}.json"

        if mat_path.exists():
            with open(mat_path, 'r', encoding='utf-8') as f:
                mat_data = json.load(f)

            pages = [
                MaterialPage(
                    page_number=p["page_number"],
                    text=p["text"],
                    text_blocks=p.get("text_blocks", []),
                    char_count=p.get("char_count", len(p["text"]))
                )
                for p in mat_data.get("pages", [])
            ]

            material = Material(
                material_id=mat_data["material_id"],
                exhibit_id=mat_data["exhibit_id"],
                document_id=mat_data["document_id"],
                file_name=mat_data["file_name"],
                page_range=mat_data["page_range"],
                start_page=mat_data["start_page"],
                end_page=mat_data["end_page"],
                material_type=mat_data["material_type"],
                title=mat_data["title"],
                date=mat_data.get("date"),
                confidence=mat_data.get("confidence", "medium"),
                pages=pages
            )
            materials.append(material)

    return materials


def load_all_materials_for_project(project_id: str) -> Dict[str, List[Material]]:
    """
    加载项目的所有材料

    Returns:
        {exhibit_id: [materials...]}
    """
    base_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    materials_dir = base_dir / project_id / "materials"

    if not materials_dir.exists():
        return {}

    result = {}
    for f in materials_dir.iterdir():
        if f.name.endswith("_materials.json"):
            exhibit_id = f.name.replace("_materials.json", "")
            materials = load_materials(project_id, exhibit_id)
            if materials:
                result[exhibit_id] = materials

    return result
