"""
Argument Generator Service - AI-powered argument assembly from extracted snippets

核心概念区分：
- L0 OCR Blocks (registry.json): 原始文本块，不使用
- L1 Snippets (extracted_snippets.json): LLM 提取的证据片段 ← 输入
- L2 Arguments (generated_arguments.json): 组装后的论据 ← 输出

流程：
1. 加载 L1 Snippets (extracted_snippets.json)
2. 运行关系分析：提取实体、识别主体、判断归属
3. 只保留归属于申请人的 snippets
4. 按 standard_key 分组生成 Arguments
5. 自动映射到 EB-1A Standards
"""

import json
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import uuid

from .snippet_extractor import load_extracted_snippets, EB1A_STANDARDS
from .relationship_analyzer import analyze_relationships

# Data storage root directory
DATA_DIR = Path(__file__).parent.parent.parent / "data"
PROJECTS_DIR = DATA_DIR / "projects"


@dataclass
class GeneratedArgument:
    """Generated argument data structure"""
    id: str
    title: str
    subject: str
    snippet_ids: List[str]
    standard_key: str
    confidence: float
    created_at: str
    is_ai_generated: bool = True


class ArgumentGenerator:
    """
    AI-powered argument generator using entity relationships

    关键：只操作 extracted_snippets.json 中的 163 条 L1 Snippets
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.project_dir = PROJECTS_DIR / project_id
        self.relationship_dir = self.project_dir / "relationship"
        self.arguments_dir = self.project_dir / "arguments"

        # Ensure directories exist
        self.relationship_dir.mkdir(parents=True, exist_ok=True)
        self.arguments_dir.mkdir(parents=True, exist_ok=True)

    def get_relationship_file(self) -> Path:
        """Get the path to the relationship analysis results"""
        return self.relationship_dir / "relationship_graph.json"

    def get_arguments_file(self) -> Path:
        """Get the path to the generated arguments"""
        return self.arguments_dir / "generated_arguments.json"

    def has_relationship_analysis(self) -> bool:
        """Check if relationship analysis has been completed"""
        return self.get_relationship_file().exists()

    def load_relationship_graph(self) -> Optional[Dict]:
        """Load existing relationship analysis results"""
        rel_file = self.get_relationship_file()
        if rel_file.exists():
            with open(rel_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def save_relationship_graph(self, graph_data: Dict):
        """Save relationship analysis results"""
        rel_file = self.get_relationship_file()
        with open(rel_file, 'w', encoding='utf-8') as f:
            json.dump(graph_data, f, ensure_ascii=False, indent=2)
        print(f"[ArgumentGenerator] Saved relationship graph to {rel_file}")

    async def generate_arguments(
        self,
        progress_callback=None,
        force_reanalyze: bool = False,
        applicant_name: Optional[str] = None
    ) -> Dict:
        """
        Main entry point: Generate arguments from extracted snippets

        Pipeline:
        1. Load L1 Snippets (extracted_snippets.json)
        2. Run relationship analysis (using OpenAI API)
        3. Filter to only applicant's snippets
        4. Group by standard_key
        5. Create arguments

        Args:
            progress_callback: Optional callback (current, total, message)
            force_reanalyze: If True, re-run relationship analysis
            applicant_name: Known applicant name (for accurate identification)

        Returns:
            {
                "success": True,
                "arguments": [...],
                "main_subject": "...",
                "stats": {...}
            }
        """
        # Step 1: Load L1 Snippets
        snippets = load_extracted_snippets(self.project_id)
        if not snippets:
            return {
                "success": False,
                "error": "No extracted snippets found. Run extraction first.",
                "arguments": [],
            }

        print(f"[ArgumentGenerator] Loaded {len(snippets)} extracted snippets")
        if applicant_name:
            print(f"[ArgumentGenerator] Using provided applicant name: {applicant_name}")

        # Step 2: Check if we need to run relationship analysis
        graph_data = None
        need_reanalyze = force_reanalyze

        # Check if applicant name changed - requires re-analysis
        if not need_reanalyze and applicant_name and self.has_relationship_analysis():
            existing_graph = self.load_relationship_graph()
            existing_subject = existing_graph.get('main_subject', '') if existing_graph else ''
            if existing_subject.lower() != applicant_name.lower():
                print(f"[ArgumentGenerator] Applicant name changed: '{existing_subject}' -> '{applicant_name}', forcing re-analysis")
                need_reanalyze = True

        if not need_reanalyze and self.has_relationship_analysis():
            print("[ArgumentGenerator] Loading existing relationship analysis...")
            graph_data = self.load_relationship_graph()

        if graph_data is None or need_reanalyze:
            # Run new relationship analysis
            if progress_callback:
                progress_callback(0, 100, "Running relationship analysis...")

            graph_data = await analyze_relationships(
                snippets=snippets,
                model="gpt-4o-mini",
                applicant_name=applicant_name,  # Pass known applicant name
                progress_callback=lambda c, t, m: progress_callback(
                    int(c * 0.6), 100, m
                ) if progress_callback else None
            )

            # Save results
            self.save_relationship_graph(graph_data)

        # Use provided applicant name or detected main_subject
        main_subject = applicant_name or graph_data.get('main_subject')
        attributions = graph_data.get('attributions', [])
        entities = graph_data.get('entities', [])
        relations = graph_data.get('relations', [])

        if progress_callback:
            progress_callback(70, 100, "Filtering applicant snippets...")

        # Step 3: Build attribution map
        attribution_map = {a['snippet_id']: a for a in attributions}

        # Step 4: Group snippets by standard_key (only applicant's)
        if progress_callback:
            progress_callback(80, 100, "Grouping snippets...")

        standard_groups = defaultdict(list)
        skipped_count = 0

        for s in snippets:
            snippet_id = s.get('snippet_id', '')
            standard_key = s.get('standard_key', '')

            if not standard_key or standard_key not in EB1A_STANDARDS:
                continue

            # Check attribution - only include applicant's snippets
            attr = attribution_map.get(snippet_id)
            if attr and not attr.get('is_applicant', True):
                skipped_count += 1
                continue

            standard_groups[standard_key].append(s)

        print(f"[ArgumentGenerator] Filtered: {skipped_count} non-applicant snippets skipped")

        if progress_callback:
            progress_callback(90, 100, "Generating arguments...")

        # Step 5: Generate arguments
        arguments = []

        for standard_key, group_snippets in standard_groups.items():
            if not group_snippets:
                continue

            standard_info = EB1A_STANDARDS.get(standard_key, {})
            standard_name = standard_info.get('name', standard_key)

            snippet_ids = [s['snippet_id'] for s in group_snippets]

            title = f"{main_subject or 'Applicant'}'s {standard_name}"

            confidences = [s.get('confidence', 0.5) for s in group_snippets]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

            argument = GeneratedArgument(
                id=f"arg-{uuid.uuid4().hex[:8]}",
                title=title,
                subject=main_subject or "Unknown",
                snippet_ids=snippet_ids,
                standard_key=standard_key,
                confidence=round(avg_confidence, 2),
                created_at=datetime.now().isoformat(),
                is_ai_generated=True
            )
            arguments.append(argument)

        # Save results
        result = {
            "success": True,
            "generated_at": datetime.now().isoformat(),
            "main_subject": main_subject,
            "arguments": [asdict(a) for a in arguments],
            "stats": {
                "total_snippets": len(snippets),
                "applicant_snippets": len(snippets) - skipped_count,
                "skipped_snippets": skipped_count,
                "entity_count": len(entities),
                "relation_count": len(relations),
                "argument_count": len(arguments),
                "by_standard": {k: len(v) for k, v in standard_groups.items()}
            }
        }

        args_file = self.get_arguments_file()
        with open(args_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        if progress_callback:
            progress_callback(100, 100, "Done!")

        print(f"[ArgumentGenerator] Generated {len(arguments)} arguments for {main_subject}")
        return result

    def load_generated_arguments(self) -> Optional[Dict]:
        """Load previously generated arguments"""
        args_file = self.get_arguments_file()
        if args_file.exists():
            with open(args_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def get_generation_status(self) -> Dict:
        """Get current generation status"""
        has_relationship = self.has_relationship_analysis()
        args_data = self.load_generated_arguments()

        return {
            "has_relationship_analysis": has_relationship,
            "has_generated_arguments": args_data is not None,
            "argument_count": len(args_data.get("arguments", [])) if args_data else 0,
            "main_subject": args_data.get("main_subject") if args_data else None,
            "generated_at": args_data.get("generated_at") if args_data else None,
        }


# Convenience function for async generation
async def generate_arguments_for_project(
    project_id: str,
    progress_callback=None,
    force_reanalyze: bool = False,
    applicant_name: Optional[str] = None
) -> Dict:
    """
    Generate arguments for a project

    Args:
        project_id: Project ID
        progress_callback: Optional callback (current, total, message)
        force_reanalyze: If True, re-run relationship analysis
        applicant_name: Known applicant name (for accurate attribution)

    Returns:
        Generation result with arguments
    """
    generator = ArgumentGenerator(project_id)
    return await generator.generate_arguments(
        progress_callback=progress_callback,
        force_reanalyze=force_reanalyze,
        applicant_name=applicant_name
    )
