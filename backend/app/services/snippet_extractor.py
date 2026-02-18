"""
Snippet Extractor - LLM 驱动的 EB-1A 证据提取

功能:
- 从 OCR text_blocks 中提取有意义的证据片段 (snippets)
- 为每个 snippet 分配 EB-1A 法律标准类别
- 精确定位到具体的 block_id 和 bbox
- 保存到 snippets registry

使用 OpenAI LLM 进行语义理解和证据提取
"""

import json
import uuid
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime

from .llm_client import call_llm
from ..core.config import settings

# ==================== LLM Prompts ====================

EXTRACTION_SYSTEM_PROMPT = """You are an expert immigration attorney assistant specializing in EB-1A visa petitions.

Your task is to extract meaningful evidence snippets from document text blocks that can support an EB-1A petition.

IMPORTANT RULES:
- Only extract text that constitutes actual EVIDENCE (achievements, recognition, contributions, specific accomplishments)
- DO NOT extract: contact info, addresses, signatures, generic greetings, pleasantries, formatting artifacts, section titles
- Each snippet should reference a specific block_id from the input
- You can extract multiple snippets from the same block if it contains multiple pieces of evidence
- Confidence should reflect how well this text serves as evidence (0.5-1.0)
- Prefer fewer, higher-quality snippets over many low-quality ones
"""

EXTRACTION_USER_PROMPT = """Analyze the following document text blocks and extract evidence snippets that support an EB-1A visa petition.

Document: Exhibit {exhibit_id}
Total Pages: {total_pages}

Text blocks (each with a unique block_id in format p{{page}}_{{original_id}}):
{blocks_text}

For each piece of evidence found, provide:
- block_id: The ID of the block containing this evidence (MUST be one of the block_ids above, format: p{{page}}_{{id}})
- text: The exact evidence text (can be the full block text or a key excerpt)
- confidence: How well this text serves as evidence (0.5-1.0)
- reasoning: Brief explanation (1 sentence) of why this is useful evidence

Return JSON format:
{{"snippets": [...]}}

If no meaningful evidence is found, return {{"snippets": []}}
"""

# JSON Schema for structured output (no standard_key - classification happens at Argument level)
EXTRACTION_SCHEMA = {
    "type": "object",
    "required": ["snippets"],
    "properties": {
        "snippets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["block_id", "text", "confidence", "reasoning"],
                "properties": {
                    "block_id": {"type": "string"},
                    "text": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reasoning": {"type": "string"}
                },
                "additionalProperties": False
            }
        }
    },
    "additionalProperties": False
}

# EB-1A 8 个法律标准 (用于参考)
EB1A_STANDARDS = {
    "awards": {
        "name": "Awards",
        "name_cn": "奖项",
        "description": "Documentation of the beneficiary's receipt of lesser nationally or internationally recognized prizes or awards for excellence in the field of endeavor"
    },
    "membership": {
        "name": "Membership",
        "name_cn": "会员资格",
        "description": "Documentation of the beneficiary's membership in associations in the field for which classification is sought, which require outstanding achievements of their members"
    },
    "published_material": {
        "name": "Published Material",
        "name_cn": "出版材料",
        "description": "Published material about the beneficiary in professional or major trade publications or other major media"
    },
    "judging": {
        "name": "Judging",
        "name_cn": "评审工作",
        "description": "Evidence of the beneficiary's participation as a judge of the work of others in the same or an allied field"
    },
    "original_contribution": {
        "name": "Original Contribution",
        "name_cn": "原创贡献",
        "description": "Evidence of the beneficiary's original scientific, scholarly, artistic, athletic, or business-related contributions of major significance in the field"
    },
    "scholarly_articles": {
        "name": "Scholarly Articles",
        "name_cn": "学术文章",
        "description": "Evidence of the beneficiary's authorship of scholarly articles in professional or major trade publications or other major media"
    },
    "exhibitions": {
        "name": "Exhibitions",
        "name_cn": "展览展示",
        "description": "Evidence of the display of the beneficiary's work in the field at artistic exhibitions or showcases"
    },
    "leading_role": {
        "name": "Leading/Critical Role",
        "name_cn": "领导角色",
        "description": "Evidence that the beneficiary has performed in a leading or critical role for organizations or establishments with a distinguished reputation"
    }
}

# 数据目录
DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"


def generate_snippet_id(exhibit_id: str, block_id: str) -> str:
    """生成唯一 snippet ID"""
    unique_suffix = uuid.uuid4().hex[:8]
    return f"snp_{exhibit_id}_{block_id}_{unique_suffix}"


def format_blocks_for_llm(pages: List[Dict]) -> tuple:
    """将所有页的 blocks 格式化为 LLM 输入格式

    Args:
        pages: 文档的所有页数据列表

    Returns:
        tuple: (blocks_text, block_map)
            - blocks_text: 格式化后的文本
            - block_map: {composite_id -> (page_num, block)} 的映射
    """
    lines = []
    block_map = {}

    for page_data in pages:
        page_num = page_data.get("page_number", 0)
        blocks = page_data.get("text_blocks", [])

        for block in blocks:
            block_id = block.get("block_id", "")
            text = block.get("text_content", "").strip()
            block_type = block.get("block_type", "text")

            # 跳过空文本或太短的文本
            if not text or len(text) < 5:
                continue

            # 跳过纯标题类型的简短文本
            if block_type in ["title", "sub_title"] and len(text) < 30:
                continue

            # 复合 ID: p{页码}_{block_id}
            composite_id = f"p{page_num}_{block_id}"
            block_map[composite_id] = (page_num, block)
            lines.append(f"[{composite_id}] {text}")

    return "\n".join(lines), block_map


async def extract_snippets_for_exhibit(
    project_id: str,
    exhibit_id: str
) -> List[Dict]:
    """
    从单个 exhibit 提取所有证据 snippets（一次性发送整个文档）

    Args:
        project_id: 项目 ID
        exhibit_id: 展品 ID

    Returns:
        提取的 snippets 列表
    """
    doc_path = PROJECTS_DIR / project_id / "documents" / f"{exhibit_id}.json"
    if not doc_path.exists():
        print(f"[Extract] Document not found: {doc_path}")
        return []

    with open(doc_path, 'r', encoding='utf-8') as f:
        doc_data = json.load(f)

    pages = doc_data.get("pages", [])
    if not pages:
        print(f"[Extract] No pages in exhibit {exhibit_id}")
        return []

    print(f"[Extract] Processing exhibit {exhibit_id} with {len(pages)} pages (single API call)...")

    # 合并所有页的 blocks，构建 block_map
    blocks_text, block_map = format_blocks_for_llm(pages)

    if not blocks_text or len(blocks_text) < 50:
        print(f"[Extract] Not enough text content in {exhibit_id}")
        return []

    # 一次性发送整个文档
    prompt = EXTRACTION_USER_PROMPT.format(
        exhibit_id=exhibit_id,
        total_pages=len(pages),
        blocks_text=blocks_text
    )

    try:
        model = getattr(settings, 'openai_model', 'gpt-4o')
        print(f"[LLM] Extracting from {exhibit_id} ({len(pages)} pages) using {model}...")

        result = await call_llm(
            prompt=prompt,
            model=model,
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
            json_schema=EXTRACTION_SCHEMA,
            temperature=0.1,
            max_tokens=4000
        )

        raw_snippets = result.get("snippets", [])

        # 解析结果，从 composite_id 提取页码和 bbox
        snippets = []
        for item in raw_snippets:
            if item.get("confidence", 0) < 0.5:
                continue

            composite_id = item.get("block_id", "")
            page_block = block_map.get(composite_id)

            if not page_block:
                print(f"[Warning] composite_id '{composite_id}' not found, skipping snippet")
                continue

            page_num, block = page_block
            original_block_id = block.get("block_id", "")

            snippet_id = generate_snippet_id(exhibit_id, composite_id)

            snippets.append({
                "snippet_id": snippet_id,
                "exhibit_id": exhibit_id,
                "document_id": f"doc_{exhibit_id}",
                "text": item.get("text", ""),
                "page": page_num,  # 从 composite_id 提取的页码
                "bbox": block.get("bbox"),  # 使用原始 block 的精确 bbox
                "block_id": original_block_id,  # 保留原始 block_id（不含页码前缀）
                # NOTE: standard_key removed - classification happens at Argument level
                "confidence": item.get("confidence", 0.5),
                "reasoning": item.get("reasoning", ""),
                "is_ai_suggested": True,
                "is_confirmed": False
            })

        print(f"[LLM] Extracted {len(snippets)} snippets from {exhibit_id} (1 API call for {len(pages)} pages)")
        return snippets

    except Exception as e:
        print(f"[LLM Error] Failed to extract from {exhibit_id}: {e}")
        return []


async def extract_all_snippets(
    project_id: str,
    progress_callback=None,
    skip_existing: bool = True  # 默认跳过已提取的文档
) -> Dict:
    """
    提取项目中所有 exhibit 的 snippets

    Args:
        project_id: 项目 ID
        progress_callback: 进度回调
        skip_existing: 是否跳过已提取的文档（节省 API credits）
    """
    project_dir = PROJECTS_DIR / project_id
    documents_dir = project_dir / "documents"

    if not documents_dir.exists():
        return {"success": False, "error": "Documents directory not found"}

    exhibit_files = list(documents_dir.glob("*.json"))
    total_exhibits = len(exhibit_files)

    # 加载已有的 snippets，找出已提取的 exhibit_ids
    existing_snippets = load_extracted_snippets(project_id)
    existing_exhibit_ids = set(s.get("exhibit_id") for s in existing_snippets)

    print(f"[Extract] Starting extraction for {total_exhibits} exhibits in project {project_id}")
    if skip_existing and existing_exhibit_ids:
        print(f"[Extract] Will skip {len(existing_exhibit_ids)} already extracted exhibits: {sorted(existing_exhibit_ids)}")

    # 保留已有的 snippets（如果跳过已提取的）
    all_snippets = existing_snippets if skip_existing else []
    seen_ids = set(s["snippet_id"] for s in all_snippets)

    skipped = 0
    extracted = 0

    for idx, exhibit_file in enumerate(exhibit_files):
        exhibit_id = exhibit_file.stem

        # 跳过已提取的文档
        if skip_existing and exhibit_id in existing_exhibit_ids:
            skipped += 1
            if progress_callback:
                progress_callback(idx + 1, total_exhibits)
            continue

        snippets = await extract_snippets_for_exhibit(project_id, exhibit_id)
        extracted += 1

        for s in snippets:
            if s["snippet_id"] not in seen_ids:
                seen_ids.add(s["snippet_id"])
                all_snippets.append(s)

        if progress_callback:
            progress_callback(idx + 1, total_exhibits)

    print(f"[Extract] Skipped {skipped} exhibits, extracted {extracted} new exhibits")

    save_extracted_snippets(project_id, all_snippets)
    update_project_pipeline_stage(project_id, "snippets_ready")

    print(f"[Extract] Completed: {len(all_snippets)} total snippets")

    return {
        "success": True,
        "snippet_count": len(all_snippets),
        "skipped_count": skipped,      # 跳过的文档数
        "extracted_count": extracted,  # 新提取的文档数
        "snippets": all_snippets
    }


def save_extracted_snippets(project_id: str, snippets: List[Dict]):
    """保存提取的 snippets"""
    snippets_dir = PROJECTS_DIR / project_id / "snippets"
    snippets_dir.mkdir(parents=True, exist_ok=True)

    extracted_file = snippets_dir / "extracted_snippets.json"

    data = {
        "version": "3.0",  # 升级版本号，标识新的精确定位格式
        "extracted_at": datetime.now().isoformat(),
        "snippet_count": len(snippets),
        "extraction_method": "llm_openai_block_level",
        "model": getattr(settings, 'openai_model', 'gpt-4o'),
        "snippets": snippets
    }

    with open(extracted_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[Extract] Saved {len(snippets)} snippets to {extracted_file}")


def update_project_pipeline_stage(project_id: str, stage: str):
    """更新项目 pipeline 阶段"""
    metadata_file = PROJECTS_DIR / project_id / "metadata.json"

    if not metadata_file.exists():
        return

    with open(metadata_file, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    metadata["pipeline_stage"] = stage
    metadata["stage_updated_at"] = datetime.now().isoformat()

    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def get_project_pipeline_stage(project_id: str) -> str:
    """获取项目当前 pipeline 阶段"""
    metadata_file = PROJECTS_DIR / project_id / "metadata.json"

    if not metadata_file.exists():
        return "unknown"

    with open(metadata_file, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    return metadata.get("pipeline_stage", "ocr_complete")


def load_extracted_snippets(project_id: str) -> List[Dict]:
    """加载提取的 snippets"""
    extracted_file = PROJECTS_DIR / project_id / "snippets" / "extracted_snippets.json"

    if not extracted_file.exists():
        return []

    with open(extracted_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    return data.get("snippets", [])


# NOTE: get_snippets_by_standard removed - classification happens at Argument level
