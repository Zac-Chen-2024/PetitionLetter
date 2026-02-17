"""
Argument Generator Service - AI-powered argument assembly from extracted snippets

核心概念区分：
- L0 OCR Blocks (registry.json): 原始文本块，不使用
- L1 Snippets: 统一提取的证据片段（已包含 subject, evidence_type, is_applicant_achievement）
- L2 Arguments (generated_arguments.json): 组装后的论据 ← 输出

流程（已更新使用统一提取数据）：
1. 加载统一提取的 Snippets (combined_extraction.json)
2. 按 evidence_type 分组，只保留 is_applicant_achievement=True 的
3. 生成 Arguments（自动映射 standard_key）
"""

import json
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from collections import defaultdict
import uuid

from .snippet_extractor import load_extracted_snippets
from .relationship_analyzer import analyze_relationships
from .unified_extractor import load_combined_extraction

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
    standard_key: str  # Empty by default - user maps to standard manually
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

        Pipeline (updated to use unified extraction):
        1. Try to load unified extraction data (has subject attribution)
        2. If not available, fall back to legacy relationship analysis
        3. Group by evidence_type and create arguments

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
        # Try unified extraction first (has subject, evidence_type, is_applicant_achievement)
        unified_data = load_combined_extraction(self.project_id)

        if unified_data and unified_data.get('snippets'):
            return await self._generate_from_unified(
                unified_data,
                applicant_name,
                progress_callback
            )

        # Fall back to legacy pipeline
        return await self._generate_from_legacy(
            force_reanalyze,
            applicant_name,
            progress_callback
        )

    async def _generate_from_unified(
        self,
        unified_data: Dict,
        applicant_name: Optional[str],
        progress_callback
    ) -> Dict:
        """Generate arguments from unified extraction data (with subject attribution)"""
        snippets = unified_data.get('snippets', [])
        entities = unified_data.get('entities', [])
        relations = unified_data.get('relations', [])

        print(f"[ArgumentGenerator] Using unified extraction: {len(snippets)} snippets")

        if progress_callback:
            progress_callback(30, 100, "Filtering applicant snippets...")

        # Filter to only applicant's achievements
        applicant_snippets = [s for s in snippets if s.get('is_applicant_achievement', False)]
        skipped_count = len(snippets) - len(applicant_snippets)

        print(f"[ArgumentGenerator] Filtered: {skipped_count} non-applicant snippets skipped")
        print(f"[ArgumentGenerator] {len(applicant_snippets)} applicant snippets remaining")

        # Determine main subject
        if applicant_name:
            main_subject = applicant_name
        else:
            # Try to get from snippets
            subjects = [s.get('subject', '') for s in applicant_snippets if s.get('subject')]
            main_subject = max(set(subjects), key=subjects.count) if subjects else "Applicant"

        if progress_callback:
            progress_callback(50, 100, "Grouping by evidence type...")

        # Group by evidence_type
        by_evidence_type = defaultdict(list)
        for s in applicant_snippets:
            evidence_type = s.get('evidence_type', 'other')
            by_evidence_type[evidence_type].append(s)

        if progress_callback:
            progress_callback(70, 100, "Generating arguments...")

        # Evidence type to standard_key mapping
        evidence_to_standard = {
            'award': 'awards',
            'awards': 'awards',
            'membership': 'membership',
            'publication': 'scholarly_articles',
            'publications': 'scholarly_articles',
            'scholarly_article': 'scholarly_articles',
            'contribution': 'original_contribution',
            'original_contribution': 'original_contribution',
            'judging': 'judging',
            'leadership': 'leading_role',
            'leading_role': 'leading_role',
            'high_salary': 'high_salary',
            'salary': 'high_salary',
            'media': 'published_material',
            'press': 'published_material',
            'exhibition': 'exhibitions',
            'exhibitions': 'exhibitions',
            'commercial': 'commercial_success',
        }

        # Create an argument for each evidence type
        arguments = []

        for evidence_type, type_snippets in by_evidence_type.items():
            if not type_snippets:
                continue

            snippet_ids = [s.get('snippet_id', s.get('block_id', '')) for s in type_snippets]

            # Map to standard
            standard_key = evidence_to_standard.get(evidence_type.lower(), '')

            # Create readable title
            type_display = evidence_type.replace('_', ' ').title()
            title = f"{main_subject} - {type_display}"

            # Calculate confidence
            confidences = [s.get('confidence', 0.5) for s in type_snippets]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

            argument = GeneratedArgument(
                id=f"arg-{uuid.uuid4().hex[:8]}",
                title=title,
                subject=main_subject,
                snippet_ids=snippet_ids,
                standard_key=standard_key,
                confidence=round(avg_confidence, 2),
                created_at=datetime.now().isoformat(),
                is_ai_generated=True
            )
            arguments.append(argument)

        # Sort by number of snippets (most evidence first)
        arguments.sort(key=lambda a: len(a.snippet_ids), reverse=True)

        if progress_callback:
            progress_callback(90, 100, "Saving results...")

        # Save results
        result = {
            "success": True,
            "generated_at": datetime.now().isoformat(),
            "main_subject": main_subject,
            "arguments": [asdict(a) for a in arguments],
            "stats": {
                "total_snippets": len(snippets),
                "applicant_snippets": len(applicant_snippets),
                "skipped_snippets": skipped_count,
                "entity_count": len(entities),
                "relation_count": len(relations),
                "argument_count": len(arguments),
                "evidence_types": list(by_evidence_type.keys()),
            }
        }

        args_file = self.get_arguments_file()
        with open(args_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        if progress_callback:
            progress_callback(100, 100, "Done!")

        print(f"[ArgumentGenerator] Generated {len(arguments)} arguments for {main_subject}")
        print(f"[ArgumentGenerator] Evidence types: {list(by_evidence_type.keys())}")
        return result

    async def _generate_from_legacy(
        self,
        force_reanalyze: bool,
        applicant_name: Optional[str],
        progress_callback
    ) -> Dict:
        """Legacy pipeline using relationship_analyzer (fallback)"""
        # Step 1: Load L1 Snippets
        snippets = load_extracted_snippets(self.project_id)
        if not snippets:
            return {
                "success": False,
                "error": "No extracted snippets found. Run extraction first.",
                "arguments": [],
            }

        print(f"[ArgumentGenerator] Using legacy pipeline: {len(snippets)} snippets")
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

        # Step 4: Filter to only applicant's snippets
        if progress_callback:
            progress_callback(80, 100, "Filtering applicant snippets...")

        applicant_snippets = []
        skipped_count = 0

        for s in snippets:
            snippet_id = s.get('snippet_id', '')

            # Check attribution - only include applicant's snippets
            attr = attribution_map.get(snippet_id)
            if attr and not attr.get('is_applicant', True):
                skipped_count += 1
                continue

            applicant_snippets.append(s)

        print(f"[ArgumentGenerator] Filtered: {skipped_count} non-applicant snippets skipped")
        print(f"[ArgumentGenerator] {len(applicant_snippets)} applicant snippets remaining")

        if progress_callback:
            progress_callback(90, 100, "Generating arguments...")

        # Step 5: Generate one argument with all applicant's snippets
        # User will manually map to standards and split if needed
        arguments = []

        if applicant_snippets:
            snippet_ids = [s['snippet_id'] for s in applicant_snippets]

            title = f"{main_subject or 'Applicant'}'s Evidence"

            confidences = [s.get('confidence', 0.5) for s in applicant_snippets]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

            argument = GeneratedArgument(
                id=f"arg-{uuid.uuid4().hex[:8]}",
                title=title,
                subject=main_subject or "Unknown",
                snippet_ids=snippet_ids,
                standard_key="",  # Empty - user maps to standard manually
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
                "applicant_snippets": len(applicant_snippets),
                "skipped_snippets": skipped_count,
                "entity_count": len(entities),
                "relation_count": len(relations),
                "argument_count": len(arguments),
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
