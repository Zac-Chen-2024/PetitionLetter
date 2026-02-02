"""
L-1 Analyzer Service - L-1 签证专项分析服务 v3.0

功能:
- 针对 L-1 签证 4 大核心标准的专项提取
- 每个独立材料单独分析（材料分割由 material_splitter 负责）
- 接收高光分析元数据作为上下文输入
- 支持文本块级分析（v3.0 新增）
- 返回结构化的引用信息
- 支持断点续传（checkpoint）避免中断后从头开始

架构变更 (v3.0):
- 新增文本块级输入支持
- 增强提取规则以保持同一文本块内信息完整
- 改进 prompt 以减少后续整合需求

架构变更 (v3.1):
- 新增 L1AnalysisCheckpoint 类支持断点续传
- 每个文档/材料处理后保存状态
- 失败自动重试，支持中断恢复
"""

from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime
from pathlib import Path
import json
import re

# 数据存储根目录
DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"


# =============================================
# L1 分析断点管理器
# =============================================

class L1AnalysisCheckpoint:
    """L1 分析断点管理器 - 支持断点续传"""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.checkpoint_dir = PROJECTS_DIR / project_id / "l1_checkpoint"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_file = self.checkpoint_dir / "l1_checkpoint.json"
        self.state: Dict[str, Any] = {}
        self.load()

    def load(self) -> bool:
        """加载已有状态，返回是否存在有效断点"""
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                    self.state = json.load(f)
                if self.state.get("status") in ["processing", "failed"]:
                    return True
            except (json.JSONDecodeError, IOError) as e:
                print(f"[L1-Checkpoint] 加载失败: {e}")
                self.state = {}
        return False

    def _save(self):
        """保存当前状态到文件"""
        with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    def init_new(self, doc_list: List[Dict]):
        """初始化新的分析任务"""
        self.state = {
            "started_at": datetime.now().isoformat(),
            "status": "processing",
            "total_docs": len(doc_list),
            "completed_docs": [],
            "failed_docs": [],
            "current_doc": None,
            "doc_list": doc_list,  # 保存文档列表用于恢复
            "results": {}  # doc_id -> result
        }
        self._save()

    def is_doc_completed(self, doc_id: str) -> bool:
        """检查文档是否已完成"""
        return doc_id in self.state.get("completed_docs", [])

    def mark_doc_completed(self, doc_id: str, result: Dict):
        """标记文档完成并保存结果"""
        if doc_id not in self.state.get("completed_docs", []):
            self.state["completed_docs"].append(doc_id)
        # 从失败列表移除（如果是重试成功）
        if doc_id in self.state.get("failed_docs", []):
            self.state["failed_docs"].remove(doc_id)
        self.state["current_doc"] = None
        # 保存结果到单独文件
        self._save_doc_result(doc_id, result)
        self._save()

    def mark_doc_failed(self, doc_id: str, error: str):
        """标记文档失败"""
        if doc_id not in self.state.get("failed_docs", []):
            self.state["failed_docs"].append(doc_id)
        self.state["current_doc"] = None
        # 保存错误信息
        error_file = self.checkpoint_dir / f"{doc_id}_error.txt"
        with open(error_file, 'w', encoding='utf-8') as f:
            f.write(f"Time: {datetime.now().isoformat()}\n")
            f.write(f"Error: {error}\n")
        self._save()

    def mark_doc_in_progress(self, doc_id: str):
        """标记文档处理中"""
        self.state["current_doc"] = doc_id
        self._save()

    def _save_doc_result(self, doc_id: str, result: Dict):
        """保存单个文档的分析结果"""
        result_file = self.checkpoint_dir / f"{doc_id}_result.json"
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    def load_doc_result(self, doc_id: str) -> Optional[Dict]:
        """加载单个文档的分析结果"""
        result_file = self.checkpoint_dir / f"{doc_id}_result.json"
        if result_file.exists():
            with open(result_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def get_all_results(self) -> List[Dict]:
        """加载所有已完成文档的结果"""
        results = []
        for doc_id in self.state.get("completed_docs", []):
            result = self.load_doc_result(doc_id)
            if result:
                results.append(result)
        return results

    def mark_completed(self):
        """标记整体完成并清理 checkpoint"""
        self.state["status"] = "completed"
        self.state["completed_at"] = datetime.now().isoformat()
        self.clear()

    def mark_failed(self, error: str):
        """标记整体失败"""
        self.state["status"] = "failed"
        self.state["error"] = error
        self.state["failed_at"] = datetime.now().isoformat()
        self._save()

    def clear(self):
        """清除 checkpoint 目录"""
        import shutil
        if self.checkpoint_dir.exists():
            shutil.rmtree(self.checkpoint_dir)
        self.state = {}

    def has_valid_checkpoint(self) -> bool:
        """检查是否有有效的未完成断点"""
        return (
            self.state.get("status") in ["processing", "failed"] and
            self.state.get("total_docs", 0) > 0 and
            len(self.state.get("completed_docs", [])) < self.state.get("total_docs", 0)
        )

    def get_doc_list(self) -> List[Dict]:
        """获取保存的文档列表"""
        return self.state.get("doc_list", [])

    def get_resume_info(self) -> Dict:
        """获取恢复点信息"""
        completed = self.state.get("completed_docs", [])
        failed = self.state.get("failed_docs", [])
        total = self.state.get("total_docs", 0)
        return {
            "completed_count": len(completed),
            "failed_count": len(failed),
            "total": total,
            "remaining": total - len(completed)
        }

    def get_progress(self) -> Dict:
        """获取当前进度信息"""
        return {
            "completed": len(self.state.get("completed_docs", [])),
            "failed": len(self.state.get("failed_docs", [])),
            "total": self.state.get("total_docs", 0),
            "status": self.state.get("status", "unknown"),
            "started_at": self.state.get("started_at"),
            "current_doc": self.state.get("current_doc")
        }


# =============================================
# 保留：OCR 文本清理
# =============================================

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


def format_text_blocks_for_prompt(text_blocks: List[Dict[str, Any]], max_blocks: int = 100) -> str:
    """
    格式化文本块列表为 LLM 提示词输入

    每个文本块标记其边界，帮助 LLM 理解 OCR 分块信息

    Args:
        text_blocks: 文本块列表，每个包含 text_content, page_number, bbox 等
        max_blocks: 最大显示块数（避免过长）

    Returns:
        格式化后的文本
    """
    if not text_blocks:
        return ""

    parts = []
    parts.append("**DOCUMENT TEXT (organized by OCR text blocks):**\n")
    parts.append("Note: Each [BLOCK n] represents a visually distinct section. Keep related info within the same block together when extracting quotes.\n")

    current_page = None
    block_count = 0

    for block in text_blocks[:max_blocks]:
        page = block.get("page_number", 1)
        text = block.get("text_content", block.get("text", "")).strip()

        if not text:
            continue

        block_count += 1

        # 页面分隔
        if page != current_page:
            if current_page is not None:
                parts.append("")
            parts.append(f"\n--- Page {page} ---")
            current_page = page

        # 块标记 - 简化格式以节省 token
        parts.append(f"\n[BLOCK {block_count}]")
        parts.append(text)

    if len(text_blocks) > max_blocks:
        parts.append(f"\n... ({len(text_blocks) - max_blocks} more blocks truncated)")

    return "\n".join(parts)


def get_l1_analysis_prompt_for_material_with_blocks(
    material_info: Dict[str, Any],
    text_blocks: List[Dict[str, Any]],
    highlight_context: Optional[str] = None
) -> str:
    """
    生成带文本块信息的材料级 L-1 专项分析提示词

    这是 v3.0 架构的核心函数，使用文本块而非连续文本作为输入

    参数:
    - material_info: 材料信息
    - text_blocks: OCR 文本块列表
    - highlight_context: 高光分析产出的上下文（可选）

    返回: 格式化的提示词
    """
    material_id = material_info.get("material_id", "")
    exhibit_id = material_info.get("exhibit_id", "X-1")
    material_type = material_info.get("material_type", "generic")
    title = material_info.get("title", "")
    date = material_info.get("date", "")
    page_range = material_info.get("page_range", "")

    type_hint = MATERIAL_TYPE_HINTS.get(material_type, MATERIAL_TYPE_HINTS["generic"])

    material_context = f"""
**MATERIAL CONTEXT:**
- Material ID: {material_id}
- Material Type: {material_type}
- Title: {title}
- Date: {date}
- Page Range: {page_range} (within Exhibit {exhibit_id})
- {type_hint}
"""

    highlight_section = ""
    if highlight_context:
        highlight_section = f"""
**PRE-ANALYSIS HIGHLIGHTS (Reference Only):**
{highlight_context}
"""

    # 格式化文本块
    blocks_text = format_text_blocks_for_prompt(text_blocks)

    prompt = f"""You are a Senior L-1 Immigration Paralegal. Extract ALL factual quotes from this material that support an L-1 visa application.

{material_context}
{highlight_section}

**CRITICAL: You MUST use ONLY these 4 standard_key values:**

| standard_key | 中文名 | English Name | What to Extract |
|--------------|--------|--------------|-----------------|
| qualifying_relationship | 合格的公司关系 | Qualifying Corporate Relationship | Company names, ownership %, parent/subsidiary statements, incorporation details |
| qualifying_employment | 海外合格任职 | Qualifying Employment Abroad | Foreign job titles, employment dates, work duration, salary |
| qualifying_capacity | 合格的职位性质 | Qualifying Capacity | Job duties, management scope, supervisory authority, decision-making power |
| doing_business | 持续运营 | Doing Business | Revenue, profits, assets, employee count, payroll, taxes, clients, contracts |

**CRITICAL: Text Block Consolidation Rule (v3.0)**

The document is organized into [BLOCK n] sections based on OCR visual boundaries.

FOR EACH BLOCK:
- If the block contains related info for the SAME standard → Output as ONE quote
- If the block contains info for DIFFERENT standards → Output separate quotes for each standard

Example for a block with company info:
[BLOCK 5]
ENTITY NAME: KINGS ELEVATOR PARTS INC.
ENTITY TYPE: DOMESTIC BUSINESS CORPORATION
ENTITY STATUS: ACTIVE
DOS ID: 123456

✅ CORRECT: One consolidated quote
{{"quote": "ENTITY NAME: KINGS ELEVATOR PARTS INC., ENTITY TYPE: DOMESTIC BUSINESS CORPORATION, ENTITY STATUS: ACTIVE, DOS ID: 123456", "standard_key": "doing_business"}}

❌ INCORRECT: Multiple fragmented quotes from same block
{{"quote": "ENTITY NAME: KINGS ELEVATOR PARTS INC."}}
{{"quote": "ENTITY TYPE: DOMESTIC BUSINESS CORPORATION"}}

**Output Format (JSON):**

{{
  "quotes": [
    {{
      "standard": "标准中文名",
      "standard_key": "one of 4 keys",
      "standard_en": "Standard English Name",
      "quote": "Exact text from document - combine related info from same block",
      "relevance": "Why this matters for L-1",
      "page": 1
    }}
  ]
}}

{blocks_text}
"""
    return prompt


# =============================================
# L-1 签证 4 大核心标准
# =============================================

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


# =============================================
# 材料类型专用提示
# =============================================

MATERIAL_TYPE_HINTS = {
    "employment_contract": "Focus on: Job title, salary, responsibilities, employment dates, employer/employee names",
    "business_contract": "Focus on: Parties involved, contract terms, amounts, dates",
    "email": "Focus on: Key facts, decisions, confirmations mentioned in the email",
    "invoice": "Focus on: Amounts, dates, parties, goods/services",
    "org_chart": "Focus on: Job titles, reporting structure, employee counts, hierarchy levels",
    "financial_statement": "Focus on: Revenue figures, profit margins, asset values, financial metrics",
    "tax_form": "Focus on: Gross receipts, Total income, Total assets, Tax amounts",
    "business_plan": "Focus on: Business strategy, market analysis, growth projections, employee plans",
    "corporate_document": "Focus on: Company structure, ownership, incorporation details",
    "letter": "Focus on: Key facts, statements, confirmations",
    "resume_cv": "Focus on: Work experience, positions held, dates, qualifications",
    "lease": "Focus on: Lease terms, rental amounts, property address, parties",
    "generic": "Extract all relevant L-1 evidence"
}


# =============================================
# L1 分析 Prompt 生成（支持材料级分析）
# =============================================

def get_l1_analysis_prompt_for_material(
    material_info: Dict[str, Any],
    highlight_context: Optional[str] = None
) -> str:
    """
    生成材料级 L-1 专项分析的提示词

    参数:
    - material_info: 材料信息 {
        material_id, exhibit_id, file_name, text,
        material_type, title, date, page_range
      }
    - highlight_context: 高光分析产出的上下文（可选）

    返回: 格式化的提示词
    """
    material_id = material_info.get("material_id", "")
    exhibit_id = material_info.get("exhibit_id", "X-1")
    file_name = material_info.get("file_name", "unknown")
    document_text = material_info.get("text", "")
    material_type = material_info.get("material_type", "generic")
    title = material_info.get("title", "")
    date = material_info.get("date", "")
    page_range = material_info.get("page_range", "")

    # 获取材料类型专用提示
    type_hint = MATERIAL_TYPE_HINTS.get(material_type, MATERIAL_TYPE_HINTS["generic"])

    # 构建材料上下文
    material_context = f"""
**MATERIAL CONTEXT:**
- Material ID: {material_id}
- Material Type: {material_type}
- Title: {title}
- Date: {date}
- Page Range: {page_range} (within Exhibit {exhibit_id})
- {type_hint}
"""

    # 添加高光分析上下文（如果存在）
    highlight_section = ""
    if highlight_context:
        highlight_section = f"""
**PRE-ANALYSIS HIGHLIGHTS (Reference Only):**
{highlight_context}

Use the above highlights as hints, but extract ALL relevant quotes from the document text below.
"""

    prompt = f"""You are a Senior L-1 Immigration Paralegal. Extract ALL factual quotes from this material that support an L-1 visa application.

{material_context}
{highlight_section}

**CRITICAL: You MUST use ONLY these 4 standard_key values:**

| standard_key | 中文名 | English Name | What to Extract |
|--------------|--------|--------------|-----------------|
| qualifying_relationship | 合格的公司关系 | Qualifying Corporate Relationship | Company names, ownership %, parent/subsidiary statements, incorporation details, shareholder info |
| qualifying_employment | 海外合格任职 | Qualifying Employment Abroad | Foreign job titles, employment dates, work duration, salary, position history |
| qualifying_capacity | 合格的职位性质 | Qualifying Capacity | Job duties, management scope, supervisory authority, decision-making power, specialized knowledge |
| doing_business | 持续运营 | Doing Business | Revenue, profits, assets, employee count, payroll, taxes, clients, contracts, business address, EIN |

**EXTRACTION RULES:**
1. Extract EXACT text verbatim - never paraphrase
2. Extract PRECISE numbers (e.g., "$741,227" not "~$740,000")
3. Each distinct fact = one quote
4. For tables: extract each relevant cell value separately

**CLASSIFICATION GUIDE BY DOCUMENT TYPE:**

For TAX FORMS (1120, 941, W-2, state returns):
- Gross receipts, revenue, income → doing_business
- Total assets, liabilities → doing_business
- Tax amounts, payroll taxes → doing_business
- Employee wages, social security → doing_business
- Company name, EIN, address → doing_business

For EMPLOYMENT CONTRACTS / JOB OFFERS:
- Job title, position → qualifying_capacity
- Salary, compensation → qualifying_employment (if abroad) OR doing_business (if US)
- Job duties, responsibilities → qualifying_capacity
- Start date, employment period → qualifying_employment
- Employer company name → qualifying_relationship

For CORPORATE DOCUMENTS (incorporation, bylaws):
- Company names → qualifying_relationship
- Ownership structure → qualifying_relationship
- Shareholder info → qualifying_relationship
- Registration details → doing_business

For BUSINESS PLANS:
- Revenue projections → doing_business
- Employee hiring plans → doing_business
- Job descriptions → qualifying_capacity
- Company relationships → qualifying_relationship

**CRITICAL: Text Block Consolidation Rule**

When extracting quotes, KEEP RELATED INFORMATION TOGETHER as a single quote:
- If multiple pieces of information appear in the same visual block or table row, combine them into ONE quote
- Do NOT split logically connected information into separate quotes

✅ CORRECT (consolidated):
```json
{{"quote": "ENTITY NAME: KINGS ELEVATOR PARTS INC., ENTITY TYPE: DOMESTIC BUSINESS CORPORATION, ENTITY STATUS: ACTIVE"}}
```

❌ INCORRECT (fragmented):
```json
{{"quote": "ENTITY NAME: KINGS ELEVATOR PARTS INC."}}
{{"quote": "ENTITY TYPE: DOMESTIC BUSINESS CORPORATION"}}
{{"quote": "ENTITY STATUS: ACTIVE"}}
```

✅ CORRECT (consolidated table data):
```json
{{"quote": "Gross receipts or sales: $741,227, Total income: $89,445, Total assets: $285,000"}}
```

**Output Format (JSON):**

{{
  "quotes": [
    {{
      "standard": "持续运营",
      "standard_key": "doing_business",
      "standard_en": "Doing Business",
      "quote": "Gross receipts or sales: $741,227, Total income: $89,445, Total assets: $285,000",
      "relevance": "Demonstrates active US business operations with significant revenue and assets",
      "page": 1
    }},
    {{
      "standard": "合格的职位性质",
      "standard_key": "qualifying_capacity",
      "standard_en": "Qualifying Capacity",
      "quote": "Supervises a team of 5 employees in the engineering department, responsible for hiring, performance reviews, and budget allocation",
      "relevance": "Shows managerial authority over personnel with specific duties",
      "page": 3
    }}
  ]
}}

**REMEMBER:**
- standard_key MUST be one of: qualifying_relationship, qualifying_employment, qualifying_capacity, doing_business
- Do NOT invent new standard_key values like "company_name", "tax_amount", "salary", etc.
- When in doubt, use "doing_business" for financial/operational data
- COMBINE related information from the same visual block into ONE quote
- Each quote should be COMPLETE and SELF-CONTAINED (include context, not just isolated values)

**Document Text:**
{document_text}
"""
    return prompt


def get_l1_analysis_prompt(doc_info: Dict[str, Any]) -> str:
    """
    生成 L-1 专项分析的提示词（保留旧接口，兼容现有代码）

    参数:
    - doc_info: 文档信息 {exhibit_id, file_name, text, ...}

    返回: 格式化的提示词
    """
    exhibit_id = doc_info.get("exhibit_id", "X-1")
    file_name = doc_info.get("file_name", "unknown")
    document_text = doc_info.get("text", "")

    prompt = f"""You are a Senior L-1 Immigration Paralegal. Your mission is to COMPREHENSIVELY extract ALL factual quotes from this document that could support an L-1 visa application.

**CRITICAL EXTRACTION RULES:**
1. Extract the EXACT text - never paraphrase or summarize
2. Extract PRECISE NUMBERS (e.g., "$741,227" not "approximately $740,000")
3. Extract ALL company/client names mentioned (e.g., "U-Tech Elevator Inc., S&Q Elevator Inc.")
4. Pay special attention to TABLES - extract exact values from table cells
5. Each distinct fact should be a separate quote

**L-1 Visa: 4 Core Legal Requirements:**

1. **Qualifying Corporate Relationship** (qualifying_relationship)
   Extract:
   - Company names (both US and foreign entities)
   - Ownership percentages (e.g., "51% ownership stake")
   - Stock amounts and share values
   - Parent/subsidiary/affiliate relationship statements
   - Shareholder names and their ownership shares
   - Articles of incorporation details

2. **Qualifying Employment Abroad** (qualifying_employment)
   Extract:
   - Foreign company name and location
   - Job titles held abroad
   - Employment start/end dates
   - Duration of employment (e.g., "3 years", "since 2019")
   - Position history and promotions
   - Salary/compensation information

3. **Qualifying Capacity** (qualifying_capacity)
   Extract:
   - Specific job duties and responsibilities
   - Management/supervisory scope (e.g., "supervises 5 employees")
   - Strategic planning and decision-making authority
   - Personnel authority (hiring, firing, performance reviews)
   - Budget control and financial authority
   - Specialized/proprietary knowledge descriptions
   - Technical expertise and qualifications

4. **Doing Business / Active Operations** (doing_business) - EXTRACT GENEROUSLY!

   **HIGH PRIORITY - Financial Data (extract EXACT numbers from tables/text):**
   - Gross receipts/revenue (e.g., "Gross receipts or sales: 741,227")
   - Net income/profit figures
   - Total assets values
   - Bank account balances
   - Sales projections by year (e.g., "$700,000 in 2025, $1,200,000 in 2026")
   - Profit margins/rates (e.g., "35% profit rate")

   **HIGH PRIORITY - Employee Data:**
   - Current employee count (e.g., "currently employs 7 employees")
   - Planned/projected headcount (e.g., "plans to hire 19 employees")
   - Payroll information
   - Organizational structure details

   **HIGH PRIORITY - Client/Partner Names:**
   - Customer company names (e.g., "U-Tech Elevator Inc., S&Q Elevator Inc.")
   - Partner/vendor names
   - Business relationship descriptions

   **Other Operations Data:**
   - Products/services offered (list specific items)
   - Entity type, status, registration dates
   - EIN, DOS ID, incorporation date
   - Business addresses, office locations
   - Lease agreements, rental amounts
   - Contracts, invoices, purchase orders

**SPECIAL INSTRUCTIONS FOR TABLES:**
- When you see a table, COMBINE related values from the same row or section into a SINGLE quote
- For tax forms (Form 1120, etc.), group related fields: "Gross receipts: $X, Total income: $Y, Total assets: $Z"
- For financial projections, keep year-by-year figures together if they're in the same table
- For org charts, extract position titles and reporting structure together

**CRITICAL: Text Block Consolidation Rule**
- KEEP RELATED INFORMATION TOGETHER as a single quote
- Do NOT split logically connected information into separate quotes
- Each quote should be COMPLETE and SELF-CONTAINED (include field names with values)

**Current Document Info:**
- **Exhibit ID:** {exhibit_id}
- **File Name:** {file_name}

**Output Format (JSON):**

{{
  "quotes": [
    {{
      "standard": "标准中文名",
      "standard_key": "standard_key",
      "standard_en": "Standard English Name",
      "quote": "The EXACT text copied from the document - never paraphrase",
      "relevance": "Brief explanation of why this quote matters for L-1",
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


# =============================================
# 结果解析
# =============================================

def map_standard_to_key(standard_name: str) -> str:
    """
    将标准名称映射到标准 key

    参数:
    - standard_name: 标准名称 (中文、英文或任意 key)

    返回: 标准 key (只返回四个有效值之一，无法识别则返回 doing_business)
    """
    if not standard_name:
        return "doing_business"

    name_lower = standard_name.lower().strip()

    # 直接匹配四个标准 key
    if name_lower in ("qualifying_relationship", "relationship"):
        return "qualifying_relationship"
    if name_lower in ("qualifying_employment", "employment"):
        return "qualifying_employment"
    if name_lower in ("qualifying_capacity", "capacity"):
        return "qualifying_capacity"
    if name_lower in ("doing_business", "business"):
        return "doing_business"

    # qualifying_relationship 关键词
    relationship_keywords = [
        "公司关系", "corporate relationship", "ownership", "parent", "subsidiary",
        "affiliate", "shareholder", "股权", "持股", "控股", "母公司", "子公司",
        "关联公司", "分公司", "incorporation", "articles", "bylaws"
    ]
    for kw in relationship_keywords:
        if kw in name_lower:
            return "qualifying_relationship"

    # qualifying_employment 关键词
    employment_keywords = [
        "任职", "employment abroad", "foreign employment", "work abroad",
        "海外", "境外", "position abroad", "employed at", "years of service",
        "employment history", "work history", "tenure"
    ]
    for kw in employment_keywords:
        if kw in name_lower:
            return "qualifying_employment"

    # qualifying_capacity 关键词
    capacity_keywords = [
        "职位", "capacity", "job duties", "responsibilities", "duties",
        "managerial", "executive", "supervisor", "supervises", "manages",
        "decision-making", "authority", "personnel", "hiring", "firing",
        "budget", "strategic", "specialized knowledge", "专业知识",
        "管理", "经理", "高管", "职责", "权限"
    ]
    for kw in capacity_keywords:
        if kw in name_lower:
            return "qualifying_capacity"

    # doing_business 关键词 (最宽泛，作为默认)
    business_keywords = [
        "运营", "business", "revenue", "income", "profit", "sales",
        "receipts", "assets", "liabilities", "tax", "payroll", "wages",
        "employees", "employee count", "address", "ein", "registration",
        "client", "customer", "contract", "invoice", "financial",
        "收入", "利润", "员工", "雇员", "银行", "存款", "合同", "业务",
        "办公", "注册", "gross", "net", "total", "amount", "balance",
        "medicare", "social security", "withholding", "quarterly"
    ]
    for kw in business_keywords:
        if kw in name_lower:
            return "doing_business"

    # 默认返回 doing_business (不返回 other)
    return "doing_business"


def parse_analysis_result(llm_response: Any, doc_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    解析 LLM 返回的分析结果

    参数:
    - llm_response: LLM 返回的 JSON (可能是 dict 或 list)
    - doc_info: 原始文档/材料信息

    返回: 标准化的引用列表
    """
    # 如果 LLM 返回的是数组而不是对象
    if isinstance(llm_response, list):
        quotes = llm_response
    elif isinstance(llm_response, dict):
        quotes = llm_response.get("quotes", [])
    else:
        quotes = []

    # 有效的 standard_key 值
    VALID_STANDARD_KEYS = {
        "qualifying_relationship",
        "qualifying_employment",
        "qualifying_capacity",
        "doing_business"
    }

    # standard_key 到中英文名称的映射
    STANDARD_NAMES = {
        "qualifying_relationship": ("合格的公司关系", "Qualifying Corporate Relationship"),
        "qualifying_employment": ("海外合格任职", "Qualifying Employment Abroad"),
        "qualifying_capacity": ("合格的职位性质", "Qualifying Capacity"),
        "doing_business": ("持续运营", "Doing Business")
    }

    parsed = []
    for q in quotes:
        # 获取并验证/标准化 standard_key
        raw_standard_key = q.get("standard_key", "")
        raw_standard = q.get("standard", "")

        # 如果提供的 standard_key 有效，直接使用
        if raw_standard_key and raw_standard_key.lower() in VALID_STANDARD_KEYS:
            standard_key = raw_standard_key.lower()
        else:
            # 否则通过 map_standard_to_key 推断
            # 优先用 standard_key，其次用 standard
            infer_from = raw_standard_key or raw_standard
            standard_key = map_standard_to_key(infer_from)

        # 确保 standard_key 有效（map_standard_to_key 保证返回有效值）
        if standard_key not in VALID_STANDARD_KEYS:
            standard_key = "doing_business"

        # 获取标准化的中英文名称
        standard_cn, standard_en = STANDARD_NAMES.get(standard_key, ("持续运营", "Doing Business"))

        # 确保 source 信息完整
        source = q.get("source", {})
        if not source:
            source = {
                "exhibit_id": doc_info.get("exhibit_id"),
                "file_name": doc_info.get("file_name")
            }

        # 添加材料信息（如果存在）
        if doc_info.get("material_id"):
            source["material_id"] = doc_info.get("material_id")

        parsed.append({
            "standard": standard_cn,
            "standard_key": standard_key,
            "standard_en": standard_en,
            "quote": q.get("quote", ""),
            "relevance": q.get("relevance", ""),
            "page": q.get("page"),
            "source": source
        })

    return parsed


def parse_material_analysis_result(
    llm_response: Dict[str, Any],
    material_info: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    解析材料级 LLM 分析结果

    参数:
    - llm_response: LLM 返回的 JSON
    - material_info: 材料信息

    返回: 标准化的引用列表
    """
    return parse_analysis_result(llm_response, material_info)


# =============================================
# 材料分析结果数据结构
# =============================================

class MaterialAnalysisResult:
    """单个材料的分析结果"""

    def __init__(self, material_id: str, exhibit_id: str, document_id: str):
        self.material_id = material_id
        self.exhibit_id = exhibit_id
        self.document_id = document_id
        self.quotes: List[Dict[str, Any]] = []
        self.analyzed_at: Optional[datetime] = None
        self.model_used: Optional[str] = None
        self.error: Optional[str] = None

    def add_quotes(self, quotes: List[Dict[str, Any]]):
        self.quotes.extend(quotes)
        self.analyzed_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "material_id": self.material_id,
            "exhibit_id": self.exhibit_id,
            "document_id": self.document_id,
            "quotes": self.quotes,
            "quote_count": len(self.quotes),
            "analyzed_at": self.analyzed_at.isoformat() if self.analyzed_at else None,
            "model_used": self.model_used,
            "error": self.error
        }


# 保留旧类以兼容现有代码
class ChunkAnalysisResult:
    """单个 Chunk 的分析结果（保留兼容性）"""

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


# =============================================
# 存储函数
# =============================================

def save_material_analysis(
    project_id: str,
    results: List[MaterialAnalysisResult]
):
    """保存材料级分析结果"""
    base_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    l1_dir = base_dir / project_id / "l1_analysis"
    l1_dir.mkdir(parents=True, exist_ok=True)

    # 生成版本 ID
    version_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    # 按 exhibit 组织结果
    by_exhibit = {}
    for result in results:
        exhibit_id = result.exhibit_id
        if exhibit_id not in by_exhibit:
            by_exhibit[exhibit_id] = []
        by_exhibit[exhibit_id].append(result.to_dict())

    # 保存汇总文件
    analysis_data = {
        "version_id": version_id,
        "timestamp": datetime.utcnow().isoformat(),
        "analysis_mode": "material_based",
        "total_materials": len(results),
        "total_quotes": sum(len(r.quotes) for r in results),
        "by_exhibit": by_exhibit,
        "material_analyses": [r.to_dict() for r in results]
    }

    analysis_path = l1_dir / f"l1_analysis_{version_id}.json"
    with open(analysis_path, 'w', encoding='utf-8') as f:
        json.dump(analysis_data, f, ensure_ascii=False, indent=2)

    print(f"[L1Analyzer] Saved material analysis to {analysis_path}")
    return version_id


def load_material_analysis(project_id: str, version_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """加载材料级分析结果"""
    base_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    l1_dir = base_dir / project_id / "l1_analysis"

    if not l1_dir.exists():
        return None

    if version_id:
        analysis_path = l1_dir / f"l1_analysis_{version_id}.json"
    else:
        # 获取最新版本
        files = sorted(l1_dir.glob("l1_analysis_*.json"), reverse=True)
        if not files:
            return None
        analysis_path = files[0]

    if not analysis_path.exists():
        return None

    with open(analysis_path, 'r', encoding='utf-8') as f:
        return json.load(f)
