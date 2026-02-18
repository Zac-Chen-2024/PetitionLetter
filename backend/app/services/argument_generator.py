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
from .llm_client import call_llm


# ==================== Prompt Templates ====================

SMART_GROUPING_SYSTEM_PROMPT = """You are an expert EB-1A immigration attorney. Organize evidence snippets into
fine-grained arguments. Each argument must have ONE clear legal purpose.

ARGUMENT TYPE PATTERNS:

For MEMBERSHIP evidence:
- org_intro: Prove the organization is distinguished (combine related snippets about the same org)
- requirement: Prove membership requires outstanding achievements
- process: Prove rigorous selection/review process
- peer_achievement: Use other members' credentials as benchmark

For PUBLISHED_MATERIAL or PUBLICATION evidence:
- media_coverage: For each media outlet, combine article content + media credentials into ONE argument
  Example: "The Jakarta Post Coverage" should include both the article about the applicant AND
  the media outlet's credentials (circulation, awards, etc.)
- Group by MEDIA OUTLET, not by article vs credential

For ORIGINAL_CONTRIBUTION or CONTRIBUTION evidence:
- creation: Prove the applicant created something original (combine description + features)
- commercial_success: Prove major significance via metrics (combine all metrics together)
- institutional_adoption: Prove adoption by schools/organizations
- testimonial: Group by PERSON - combine all snippets from the same recommender
- expert_endorsement: Group by PERSON - combine all snippets from the same expert

For LEADING_ROLE or LEADERSHIP evidence:
- role_at_org: For each organization, combine role description + achievements into ONE argument
- org_credential: Prove the organization's distinguished reputation
- industry_recognition: Recognition from industry bodies
- partner_endorsement: Group by PERSON/ORGANIZATION

For AWARD evidence:
- award: Combine award description + award criteria/prestige into ONE argument per award

For JUDGING evidence:
- judging: Combine role + venue credentials into ONE argument

RULES:
1. GROUP BY LOGICAL UNIT: Combine snippets about the same person/organization/media outlet
2. AVOID FRAGMENTATION: Prefer 3-7 arguments over 10+ tiny ones
3. Each argument should have 2-5 snippets ideally (unless only 1 exists)
4. Use entity names in titles (e.g., "Tom Liaw's Endorsement", "The Jakarta Post Coverage")
5. CRITICAL: You MUST assign ALL snippets to arguments. Every snippet_id must appear in exactly one argument.
6. Copy snippet_ids EXACTLY as provided - do not modify or abbreviate them."""

SMART_GROUPING_USER_PROMPT = """Evidence Type: {evidence_type}
Applicant: {applicant_name}

## Snippets (with simplified IDs: S1, S2, S3, etc.)
{snippets_formatted}

## Entities Found
{entities_summary}

## Relationships
{relations_summary}

Organize these snippets into logical argument groups.

KEY PRINCIPLES:
1. Group by person/organization/media outlet - don't split the same entity across arguments
2. For recommendations: combine all snippets from the same recommender into ONE argument
3. For media coverage: combine article content + media credentials for each outlet
4. Aim for 3-7 arguments total (not 10+ fragmented ones)

IMPORTANT: Use the simplified IDs (S1, S2, etc.). Assign ALL snippets.

Return JSON:
{{
  "arguments": [
    {{
      "type": "creation|testimonial|media_coverage|org_intro|...",
      "title": "Specific title with entity name (e.g., 'Tom Liaw Endorsement')",
      "purpose": "What legal point this proves",
      "snippet_ids": ["S1", "S3", "S5"],
      "key_entity": "Main entity name",
      "confidence": 0.9
    }}
  ]
}}"""

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

    async def _smart_group_snippets(
        self,
        snippets: List[Dict],
        evidence_type: str,
        entities: List[Dict],
        relations: List[Dict],
        applicant_name: str
    ) -> List[GeneratedArgument]:
        """
        Use LLM to intelligently group snippets into fine-grained arguments

        Args:
            snippets: Snippets of the same evidence_type
            evidence_type: Type like 'contribution', 'media', 'membership'
            entities: All entities from unified extraction
            relations: All relations from unified extraction
            applicant_name: Name of the applicant

        Returns:
            List of GeneratedArgument with fine-grained grouping
        """
        # Create a simplified ID mapping to avoid LLM copying errors
        # Use simple numeric IDs: S1, S2, S3, etc.
        id_mapping = {}  # simple_id -> real_snippet_id
        reverse_mapping = {}  # real_snippet_id -> simple_id

        # Format snippets for prompt with simplified IDs
        snippets_lines = []
        for i, s in enumerate(snippets, 1):
            real_id = s.get('snippet_id', s.get('block_id', ''))
            simple_id = f"S{i}"
            id_mapping[simple_id] = real_id
            reverse_mapping[real_id] = simple_id

            text = s.get('text', '')[:400]  # Increased limit for better context
            subject = s.get('subject', '')
            exhibit_id = s.get('exhibit_id', '')
            snippets_lines.append(f"[{simple_id}] (Exhibit: {exhibit_id}, subject: {subject}) {text}")
        snippets_formatted = "\n".join(snippets_lines)

        # Format entities summary - filter to relevant ones
        relevant_entity_names = set()
        for s in snippets:
            if s.get('subject'):
                relevant_entity_names.add(s.get('subject').lower())

        entity_lines = []
        for e in entities:
            name = e.get('name', '')
            etype = e.get('type', '')
            identity = e.get('identity', '')
            relation = e.get('relation_to_applicant', '')
            entity_lines.append(f"- {name} ({etype}): {identity} [relation: {relation}]")
        entities_summary = "\n".join(entity_lines[:20])  # Limit to 20 entities

        # Format relations summary
        relation_lines = []
        for r in relations:
            from_e = r.get('from_entity', '')
            to_e = r.get('to_entity', '')
            rel_type = r.get('relation_type', '')
            relation_lines.append(f"- {from_e} --[{rel_type}]--> {to_e}")
        relations_summary = "\n".join(relation_lines[:15])  # Limit to 15 relations

        # Build prompt
        user_prompt = SMART_GROUPING_USER_PROMPT.format(
            evidence_type=evidence_type,
            applicant_name=applicant_name,
            snippets_formatted=snippets_formatted,
            entities_summary=entities_summary or "(No entities found)",
            relations_summary=relations_summary or "(No relations found)"
        )

        # Add simplified ID list to prompt for validation
        simple_id_list = ", ".join([f"S{i}" for i in range(1, len(snippets) + 1)])
        user_prompt_with_ids = user_prompt + f"\n\nAVAILABLE SNIPPET IDS: {simple_id_list}\nYou MUST use these exact IDs. Assign ALL of them."

        try:
            result = await call_llm(
                prompt=user_prompt_with_ids,
                model="gpt-4o-mini",
                system_prompt=SMART_GROUPING_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=4000
            )

            raw_arguments = result.get('arguments', [])
            if not raw_arguments:
                print(f"[ArgumentGenerator] LLM returned no arguments for {evidence_type}, falling back")
                return self._create_simple_arguments(snippets, evidence_type, applicant_name)

            # Convert to GeneratedArgument, mapping simple IDs back to real IDs
            arguments = []
            all_simple_ids = set(id_mapping.keys())

            for arg in raw_arguments:
                # Get snippet_ids and convert from simple to real IDs
                arg_snippet_ids = arg.get('snippet_ids', [])
                real_snippet_ids = []

                for sid in arg_snippet_ids:
                    # Handle both "S1" and "s1" formats
                    normalized_sid = sid.upper() if isinstance(sid, str) else str(sid)
                    if not normalized_sid.startswith('S'):
                        normalized_sid = f"S{normalized_sid}"

                    if normalized_sid in id_mapping:
                        real_snippet_ids.append(id_mapping[normalized_sid])
                    else:
                        print(f"[ArgumentGenerator] Warning: Unknown snippet ID '{sid}' in LLM response")

                if not real_snippet_ids:
                    continue

                # Map evidence_type to standard_key
                standard_key = self._evidence_to_standard(evidence_type)

                argument = GeneratedArgument(
                    id=f"arg-{uuid.uuid4().hex[:8]}",
                    title=arg.get('title', f"{applicant_name} - {evidence_type}"),
                    subject=applicant_name,
                    snippet_ids=real_snippet_ids,
                    standard_key=standard_key,
                    confidence=arg.get('confidence', 0.8),
                    created_at=datetime.now().isoformat(),
                    is_ai_generated=True
                )
                arguments.append(argument)

            # Check for missed snippets and create catch-all if needed
            used_snippet_ids = set()
            for arg in arguments:
                used_snippet_ids.update(arg.snippet_ids)

            missed_snippets = [s for s in snippets
                              if s.get('snippet_id', s.get('block_id', '')) not in used_snippet_ids]

            if missed_snippets:
                missed_pct = len(missed_snippets) / len(snippets) * 100
                print(f"[ArgumentGenerator] {len(missed_snippets)} snippets ({missed_pct:.0f}%) not assigned, creating catch-all")
                catch_all = self._create_simple_arguments(missed_snippets, evidence_type, applicant_name)
                arguments.extend(catch_all)

            print(f"[ArgumentGenerator] Smart grouped {evidence_type}: {len(arguments)} arguments from {len(snippets)} snippets")
            return arguments

        except Exception as e:
            print(f"[ArgumentGenerator] Smart grouping failed for {evidence_type}: {e}")
            return self._create_simple_arguments(snippets, evidence_type, applicant_name)

    def _create_simple_arguments(
        self,
        snippets: List[Dict],
        evidence_type: str,
        applicant_name: str
    ) -> List[GeneratedArgument]:
        """
        Create a simple argument with all snippets (fallback)

        Used when:
        - LLM grouping fails
        - Only a few snippets (<=3)
        """
        if not snippets:
            return []

        snippet_ids = [s.get('snippet_id', s.get('block_id', '')) for s in snippets]
        standard_key = self._evidence_to_standard(evidence_type)

        type_display = evidence_type.replace('_', ' ').title()
        title = f"{applicant_name} - {type_display}"

        confidences = [s.get('confidence', 0.5) for s in snippets]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

        argument = GeneratedArgument(
            id=f"arg-{uuid.uuid4().hex[:8]}",
            title=title,
            subject=applicant_name,
            snippet_ids=snippet_ids,
            standard_key=standard_key,
            confidence=round(avg_confidence, 2),
            created_at=datetime.now().isoformat(),
            is_ai_generated=True
        )

        return [argument]

    def _evidence_to_standard(self, evidence_type: str) -> str:
        """Map evidence_type to standard_key"""
        mapping = {
            'award': 'awards',
            'awards': 'awards',
            'membership': 'membership',
            'membership_criteria': 'membership',      # 新增：会员资格要求
            'membership_evaluation': 'membership',    # 新增：会员评审
            'peer_assessment': 'membership',          # 新增：同行评价
            'peer_achievement': 'membership',         # 新增：其他杰出会员成就（证明选择性）
            'publication': 'published_material',
            'publications': 'published_material',
            'scholarly_article': 'scholarly_articles',
            'article': 'published_material',
            'media_coverage': 'published_material',   # 新增：媒体报道
            'source_credibility': 'published_material', # 新增：来源资质（证明媒体权威性）
            'quantitative_impact': 'original_contribution', # 新增：量化影响力数据
            'contribution': 'original_contribution',
            'original_contribution': 'original_contribution',
            'recommendation': 'original_contribution', # 新增：推荐信
            'judging': 'judging',
            'leadership': 'leading_role',
            'leading_role': 'leading_role',
            'high_salary': 'high_salary',
            'salary': 'high_salary',
            'media': 'published_material',
            'press': 'published_material',
            'published_material': 'published_material',
            'media_credential': 'published_material',
            'media_article': 'published_material',
            'exhibition': 'exhibitions',
            'exhibitions': 'exhibitions',
            'commercial': 'commercial_success',
            'other': '',
        }
        return mapping.get(evidence_type.lower(), '')

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
        """Generate arguments from unified extraction data (with subject attribution)

        Uses LLM to intelligently group snippets into fine-grained arguments
        """
        snippets = unified_data.get('snippets', [])
        entities = unified_data.get('entities', [])
        relations = unified_data.get('relations', [])

        print(f"[ArgumentGenerator] Using unified extraction: {len(snippets)} snippets")

        if progress_callback:
            progress_callback(10, 100, "Filtering applicant snippets...")

        # Filter to only applicant's achievements
        applicant_snippets = [s for s in snippets if s.get('is_applicant_achievement', False)]
        skipped_count = len(snippets) - len(applicant_snippets)

        print(f"[ArgumentGenerator] Filtered: {skipped_count} non-applicant snippets skipped")
        print(f"[ArgumentGenerator] {len(applicant_snippets)} applicant snippets remaining")

        # === SPECIAL HANDLING: Published Material ===
        # Media credentials (is_applicant_achievement=False) are also needed for Published Material arguments
        # They prove the media outlet is "major" (circulation, awards, etc.)
        publication_snippets = [s for s in snippets if s.get('evidence_type') == 'publication']
        if publication_snippets:
            print(f"[ArgumentGenerator] Found {len(publication_snippets)} publication snippets for Published Material")
            # Add them to applicant_snippets with a special marker
            for s in publication_snippets:
                if s not in applicant_snippets:
                    s['_is_media_credential'] = True
                    applicant_snippets.append(s)

        # Determine main subject
        if applicant_name:
            main_subject = applicant_name
        else:
            # Try to get from snippets
            subjects = [s.get('subject', '') for s in applicant_snippets if s.get('subject')]
            main_subject = max(set(subjects), key=subjects.count) if subjects else "Applicant"

        if progress_callback:
            progress_callback(20, 100, "Grouping by evidence type...")

        # Group by evidence_type
        by_evidence_type = defaultdict(list)
        for s in applicant_snippets:
            evidence_type = s.get('evidence_type', 'other')
            by_evidence_type[evidence_type].append(s)

        if progress_callback:
            progress_callback(30, 100, "Smart grouping arguments...")

        # Smart group each evidence type using LLM
        # Lowered threshold from 3 to 2 to enable fine-grained grouping for smaller sets
        SMART_GROUPING_THRESHOLD = 2

        arguments = []
        total_types = len(by_evidence_type)
        processed_types = 0

        for evidence_type, type_snippets in by_evidence_type.items():
            if not type_snippets:
                continue

            processed_types += 1
            if progress_callback:
                progress = 30 + int((processed_types / total_types) * 60)
                progress_callback(progress, 100, f"Grouping {evidence_type} ({len(type_snippets)} snippets)...")

            # Use smart grouping for larger groups, simple for small ones
            if len(type_snippets) < SMART_GROUPING_THRESHOLD:
                type_arguments = self._create_simple_arguments(type_snippets, evidence_type, main_subject)
            else:
                type_arguments = await self._smart_group_snippets(
                    type_snippets,
                    evidence_type,
                    entities,
                    relations,
                    main_subject
                )

            arguments.extend(type_arguments)

            # Small delay to avoid rate limiting
            await asyncio.sleep(0.3)

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

    def load_snippets(self) -> List[Dict]:
        """Load all snippets from extraction files"""
        snippets = []
        extraction_dir = self.project_dir / "extraction"
        if extraction_dir.exists():
            for f in extraction_dir.glob("*_extraction.json"):
                with open(f, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                    snippets.extend(data.get("snippets", []))
        return snippets

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
