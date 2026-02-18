"""
Argument Composer - 律师风格论点组合器 (泛化版)

将碎片化的 snippets 组合成结构化的律师风格论点：
- Membership: 按协会分组
- Published Material: 按媒体分组
- Original Contribution: 合并成整体
- Leading Role: 按组织分组
- Awards: 按奖项分组

每个论点包含: Claim + Proof + Significance + Context + Conclusion

**泛化改进**: 使用 project_metadata.json 配置替代硬编码映射
"""

import json
import re
from typing import Dict, List, Any, Optional
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, asdict, field


# EB-1A 法规引用
LEGAL_CITATIONS = {
    "membership": "8 C.F.R. §204.5(h)(3)(ii)",
    "published_material": "8 C.F.R. §204.5(h)(3)(iii)",
    "original_contribution": "8 C.F.R. §204.5(h)(3)(v)",
    "leading_role": "8 C.F.R. §204.5(h)(3)(viii)",
    "awards": "8 C.F.R. §204.5(h)(3)(i)",
}

# 标准的正式名称
STANDARD_FORMAL_NAMES = {
    "membership": "Membership in Associations Requiring Outstanding Achievements",
    "published_material": "Published Material in Professional/Major Trade Publications",
    "original_contribution": "Original Contributions of Major Significance",
    "leading_role": "Leading/Critical Role for Distinguished Organizations",
    "awards": "Nationally/Internationally Recognized Awards",
}

# 通用的不合格会员组织 (作为 fallback)
DEFAULT_DISQUALIFIED_MEMBERSHIPS = {
    "usa weightlifting",
    "nsca",
    "national strength and conditioning association",
    "ace",
    "american council on exercise",
    "nasm",
    "issa",
}


@dataclass
class EvidenceItem:
    """单条证据"""
    text: str
    exhibit_id: str
    purpose: str  # direct_proof, selectivity_proof, credibility_proof, impact_proof
    snippet_id: str = ""
    context_before: str = ""  # 前文上下文 (来自 Context Enrichment)
    context_after: str = ""   # 后文上下文


@dataclass
class ComposedArgument:
    """组合后的论点"""
    title: str
    standard: str
    group_key: str  # 分组键（协会名/媒体名/组织名）
    claim: List[EvidenceItem] = field(default_factory=list)
    proof: List[EvidenceItem] = field(default_factory=list)
    significance: List[EvidenceItem] = field(default_factory=list)
    context: List[EvidenceItem] = field(default_factory=list)
    exhibits: List[str] = field(default_factory=list)
    conclusion: str = ""
    completeness: Dict[str, Any] = field(default_factory=dict)


class ArgumentComposer:
    """论点组合器 (泛化版)"""

    def __init__(
        self,
        snippets: List[Dict],
        applicant_name: str = "the applicant",
        metadata: Optional[Dict] = None,
        entity_validator: Optional[Any] = None
    ):
        """
        初始化

        Args:
            snippets: 提取的 snippets 列表
            applicant_name: 申请人姓名
            metadata: project_metadata 配置 (如果为 None 则使用空配置)
            entity_validator: EntityValidator 实例 (可选，用于验证实体)
        """
        self.snippets = snippets
        self.applicant_name = applicant_name
        self.metadata = metadata or self._create_empty_metadata()
        self.entity_validator = entity_validator
        self.snippets_by_standard = self._group_by_standard()

        # 从配置中提取映射
        self._init_mappings()

    def _create_empty_metadata(self) -> Dict:
        """创建空配置"""
        return {
            "applicant": {
                "formal_name": self.applicant_name,
                "name_variants": []
            },
            "exhibit_mappings": {
                "media": {},
                "associations": {},
                "organizations": {}
            },
            "entity_merges": [],
            "disqualified_memberships": [],
            "key_achievements": {
                "original_contribution": "",
                "awards": []
            }
        }

    def _init_mappings(self):
        """从配置初始化映射"""
        exhibit_mappings = self.metadata.get("exhibit_mappings", {})

        # Exhibit → 媒体名映射
        self.exhibit_to_media = exhibit_mappings.get("media", {})

        # Exhibit → 协会名映射
        self.exhibit_to_association = exhibit_mappings.get("associations", {})

        # Exhibit → 组织名映射
        self.exhibit_to_organization = exhibit_mappings.get("organizations", {})

        # 不合格会员列表 (配置 + 默认)
        config_disqualified = set(
            m.lower() for m in self.metadata.get("disqualified_memberships", [])
        )
        self.disqualified_memberships = config_disqualified | DEFAULT_DISQUALIFIED_MEMBERSHIPS

        # 实体合并映射 (variant → canonical)
        self.entity_merge_map = {}
        for merge in self.metadata.get("entity_merges", []):
            canonical = merge.get("canonical", "")
            for variant in merge.get("variants", []):
                self.entity_merge_map[variant.lower()] = canonical

        # 申请人名字变体
        self.applicant_variants = set(
            v.lower() for v in self.metadata.get("applicant", {}).get("name_variants", [])
        )

        # 关键成就
        key_achievements = self.metadata.get("key_achievements", {})
        self.original_contribution_name = key_achievements.get("original_contribution", "Original Contribution")
        self.award_names = key_achievements.get("awards", [])

    def _group_by_standard(self) -> Dict[str, List[Dict]]:
        """按标准分组"""
        grouped = defaultdict(list)
        for snp in self.snippets:
            # 只处理申请人相关的证据
            if not snp.get("is_applicant_achievement", True):
                continue
            etype = snp.get("evidence_type", "other")
            standard = self._map_to_standard(etype)
            if standard:
                grouped[standard].append(snp)
        return grouped

    def _map_to_standard(self, etype: str) -> Optional[str]:
        """证据类型映射到标准 - 支持自由分类的关键词匹配"""
        if not etype:
            return None

        etype_lower = etype.lower()

        # 先检查精确匹配（向后兼容）
        exact_mapping = {
            "membership": "membership",
            "membership_criteria": "membership",
            "membership_evaluation": "membership",
            "peer_achievement": "membership",
            "publication": "published_material",
            "media_coverage": "published_material",
            "source_credibility": "published_material",
            "contribution": "original_contribution",
            "quantitative_impact": "original_contribution",
            "recommendation": "original_contribution",
            "peer_assessment": "original_contribution",
            "leadership": "leading_role",
            "award": "awards",
        }

        if etype_lower in exact_mapping:
            return exact_mapping[etype_lower]

        # 关键词匹配 - 处理自由分类的变体
        # 注意：invitation 不应归入 leading_role
        invitation_keywords = ["invitation", "invited", "speaking", "guest speaker", "keynote"]
        if any(kw in etype_lower for kw in invitation_keywords):
            # invitation 可以支持 original_contribution（证明方法被认可）
            return "original_contribution"

        leadership_keywords = ["leadership", "leading", "critical role", "founder", "director", "ceo", "legal representative"]
        if any(kw in etype_lower for kw in leadership_keywords):
            return "leading_role"

        membership_keywords = ["membership", "member", "association", "selectivity", "criteria"]
        if any(kw in etype_lower for kw in membership_keywords):
            return "membership"

        media_keywords = ["media", "publication", "article", "coverage", "press", "news", "journal"]
        if any(kw in etype_lower for kw in media_keywords):
            return "published_material"

        contribution_keywords = ["contribution", "original", "innovation", "impact", "influence"]
        if any(kw in etype_lower for kw in contribution_keywords):
            return "original_contribution"

        award_keywords = ["award", "prize", "honor", "recognition"]
        if any(kw in etype_lower for kw in award_keywords):
            return "awards"

        return None

    def compose_all(self) -> Dict[str, List[ComposedArgument]]:
        """组合所有标准的论点"""
        composed = {}
        for standard in ["membership", "published_material", "original_contribution", "leading_role", "awards"]:
            composed[standard] = self._compose_standard(standard)
        return composed

    def _compose_standard(self, standard: str) -> List[ComposedArgument]:
        """组合单个标准的论点"""
        snippets = self.snippets_by_standard.get(standard, [])
        if not snippets:
            return []

        if standard == "original_contribution":
            # Original Contribution: 合并成一个整体论点
            group_key = self.original_contribution_name or "Original Contribution"
            return [self._compose_single_argument(snippets, standard, group_key)]
        elif standard == "awards":
            # Awards: 合并成一个整体论点
            group_key = self.award_names[0] if self.award_names else "Award"
            return [self._compose_single_argument(snippets, standard, group_key)]
        else:
            # 其他标准: 按实体分组
            groups = self._group_by_entity(snippets, standard)
            return [
                self._compose_single_argument(group_snippets, standard, group_key)
                for group_key, group_snippets in groups.items()
                if group_snippets
            ]

    def _group_by_entity(self, snippets: List[Dict], standard: str) -> Dict[str, List[Dict]]:
        """按核心实体分组 - 过滤不合格实体"""
        groups = defaultdict(list)

        for snp in snippets:
            text = snp.get("text", "")
            subject = snp.get("subject", "")
            exhibit_id = snp.get("exhibit_id", "")

            if standard == "membership":
                # 按协会分组 - 使用配置映射
                group_key = self._extract_association_name(text, subject, exhibit_id)
            elif standard == "published_material":
                # 按媒体分组 - 使用配置映射
                group_key = self._extract_media_name(text, exhibit_id)
            elif standard == "leading_role":
                # 按组织分组 - 使用配置映射
                group_key = self._extract_organization_name(text, subject, exhibit_id)
            elif standard == "awards":
                # 按奖项分组
                group_key = self._extract_award_name(text)
            else:
                group_key = "default"

            # 只有合格的实体才加入分组 (group_key 不为 None)
            if group_key is not None:
                groups[group_key].append(snp)

        return groups

    def _extract_association_name(self, text: str, subject: str, exhibit_id: str = "") -> Optional[str]:
        """提取协会名称 - 使用配置映射"""
        text_lower = text.lower()

        # 检查是否是不合格会员 (普通专业认证)
        for disqualified in self.disqualified_memberships:
            if disqualified in text_lower:
                return None  # 返回 None 表示应该被过滤

        # 优先使用 Exhibit → 协会映射
        if exhibit_id in self.exhibit_to_association:
            return self.exhibit_to_association[exhibit_id]

        # 检查实体合并映射
        for pattern, canonical in self.entity_merge_map.items():
            if pattern in text_lower:
                return canonical

        # 从文本中尝试识别协会名称
        association_patterns = [
            r"([\w\s]+)\s+association",
            r"([\w\s]+)\s+society",
            r"member\s+of\s+([\w\s]+)",
        ]
        for p in association_patterns:
            match = re.search(p, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                if len(name) > 3 and name.lower() not in self.disqualified_memberships:
                    return name.title()

        # 未识别的协会 - 返回 None
        return None

    def _extract_media_name(self, text: str, exhibit_id: str) -> Optional[str]:
        """提取媒体名称 - 使用配置映射"""
        # 只有 D 系列 Exhibit 才是 Published Material
        if not exhibit_id.startswith("D"):
            return None

        # 优先使用 Exhibit → Media 映射
        if exhibit_id in self.exhibit_to_media:
            return self.exhibit_to_media[exhibit_id]

        # 检查实体合并映射
        text_lower = text.lower()
        for pattern, canonical in self.entity_merge_map.items():
            if pattern in text_lower:
                return canonical

        # 备用：从文本中识别常见媒体
        media_patterns = {
            "jakarta post": "The Jakarta Post",
            "china sports daily": "China Sports Daily",
            "sixth tone": "Sixth Tone",
            "the paper": "The Paper",
            "new york times": "The New York Times",
            "washington post": "The Washington Post",
            "bbc": "BBC",
            "cnn": "CNN",
            "reuters": "Reuters",
        }
        for pattern, name in media_patterns.items():
            if pattern in text_lower:
                return name

        # D 系列但未识别的媒体
        return "Media Coverage"

    def _extract_organization_name(self, text: str, subject: str, exhibit_id: str = "") -> Optional[str]:
        """提取组织名称 - 使用配置映射 + 实体验证

        对于 Leading Role，需要提取申请人实际领导的组织，而不是文本中任意提到的组织。
        """
        text_lower = text.lower()
        subject_lower = subject.lower() if subject else ""

        # 排除申请人名字作为组织名
        if subject_lower in self.applicant_variants:
            subject = None

        # 关键词检查：只有当文本表明申请人领导/创建某组织时才提取
        leadership_keywords = ["founded", "founder", "established", "created", "co-founded",
                               "legal representative", "ceo", "director", "president", "chairman",
                               "创始人", "法定代表人", "董事长", "总经理"]
        has_leadership_indicator = any(kw in text_lower for kw in leadership_keywords)

        # 排除邀请性质的文本 - 这不是 leadership 证据
        invitation_keywords = ["invite", "invitation", "invited", "as a guest", "as an industry",
                              "sharing guest", "look forward to", "邀请"]
        is_invitation = any(kw in text_lower for kw in invitation_keywords)

        if is_invitation and not has_leadership_indicator:
            # 这是邀请信，不是 leadership 证据
            return None

        # 优先使用 Exhibit → Organization 映射 (来自 LLM 分析)
        if exhibit_id in self.exhibit_to_organization:
            return self.exhibit_to_organization[exhibit_id]

        # 检查实体合并映射
        for pattern, canonical in self.entity_merge_map.items():
            if pattern in text_lower:
                return canonical

        # 使用 EntityValidator 验证组织名称 (Multi-Agent 方法)
        if self.entity_validator:
            # 从文本中尝试识别组织名称
            org_patterns = [
                r"([\w\s]+(?:Co\.|Company|Corp|Inc|Ltd|LLC|Pte)[\w\s]*)",
                r"([\w\s]+(?:Club|Center|Academy|Institute|Association|Federation))",
            ]
            for p in org_patterns:
                match = re.search(p, text, re.IGNORECASE)
                if match:
                    name = match.group(1).strip()
                    # 过滤太短的名字
                    if len(name) <= 5:
                        continue
                    # 过滤句子片段
                    if any(word in name.lower() for word in ["hereby", "i ", "we ", "you ", "this ", "that "]):
                        continue
                    # 使用 EntityValidator 验证
                    if self.entity_validator.is_valid_organization(name):
                        return name

            # 如果没有匹配到，尝试检查 subject
            if subject and len(subject) > 5:
                if not any(word in subject.lower() for word in ["hereby", "i ", "we ", "you "]):
                    if self.entity_validator.is_valid_organization(subject):
                        return subject

            # 未通过验证 - 返回 None (过滤垃圾)
            return None

        # Fallback: 没有 EntityValidator 时使用原始 regex (不推荐)
        org_patterns = [
            r"([\w\s]+)\s+(?:co\.|company|corp|inc|ltd|llc|pte)",
            r"([\w\s]+)\s+(?:club|center|academy|institute|association|federation)",
        ]
        for p in org_patterns:
            match = re.search(p, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                if len(name) > 3 and name.lower() not in self.applicant_variants:
                    return name.title()

        # 未识别的组织 - 返回 None
        return None

    def _extract_award_name(self, text: str) -> str:
        """提取奖项名称"""
        # 使用配置中的奖项名称
        if self.award_names:
            for award in self.award_names:
                if award.lower() in text.lower():
                    return award

        # 通用奖项模式
        patterns = [
            r"([\w\s]+)\s+award",
            r"([\w\s]+)\s+prize",
            r"(gold|silver|bronze)\s+medal",
            r"first\s+(?:place|prize)",
        ]
        for p in patterns:
            match = re.search(p, text, re.IGNORECASE)
            if match:
                return match.group(0).title()

        return "Award"

    def _compose_single_argument(self, snippets: List[Dict], standard: str, group_key: str) -> ComposedArgument:
        """组合单个论点"""
        # 按层级分类
        layers = {"claim": [], "proof": [], "significance": [], "context": []}
        exhibits = set()

        for snp in snippets:
            layer = snp.get("evidence_layer", "claim")
            if layer not in layers:
                layer = "claim"

            # 提取上下文 (来自 Context Enrichment)
            context_data = snp.get("context", {}) or {}

            item = EvidenceItem(
                text=snp.get("text", "")[:500],
                exhibit_id=snp.get("exhibit_id", ""),
                purpose=snp.get("evidence_purpose", "direct_proof"),
                snippet_id=snp.get("snippet_id", ""),
                context_before=context_data.get("before", "")[:200] if context_data else "",
                context_after=context_data.get("after", "")[:200] if context_data else ""
            )
            layers[layer].append(item)
            exhibits.add(snp.get("exhibit_id", ""))

        # 生成标题
        title = self._generate_title(group_key, standard)

        # 生成结论
        conclusion = self._generate_conclusion(standard, group_key)

        # 计算完整性
        completeness = {
            "has_claim": len(layers["claim"]) > 0,
            "has_proof": len(layers["proof"]) > 0,
            "has_significance": len(layers["significance"]) > 0,
            "has_context": len(layers["context"]) > 0,
            "score": self._calculate_completeness_score(layers)
        }

        return ComposedArgument(
            title=title,
            standard=standard,
            group_key=group_key,
            claim=layers["claim"],
            proof=layers["proof"],
            significance=layers["significance"],
            context=layers["context"],
            exhibits=sorted(list(exhibits)),
            conclusion=conclusion,
            completeness=completeness
        )

    def _generate_title(self, group_key: str, standard: str) -> str:
        """生成律师风格标题"""
        templates = {
            "membership": f"{self.applicant_name}'s Membership in {group_key}",
            "published_material": f"{group_key} Coverage of {self.applicant_name}",
            "original_contribution": f"{self.applicant_name}'s Original {group_key} and Its Major Significance",
            "leading_role": f"{self.applicant_name}'s Leadership at {group_key}",
            "awards": f"{self.applicant_name}'s {group_key}",
        }
        return templates.get(standard, f"{self.applicant_name} - {group_key}")

    def _generate_conclusion(self, standard: str, group_key: str) -> str:
        """生成法律结论"""
        citation = LEGAL_CITATIONS.get(standard, "")
        conclusions = {
            "membership": f"{self.applicant_name}'s membership in {group_key} clearly meets the requirements of {citation}.",
            "published_material": f"The coverage by {group_key}, a major publication, meets the requirements of {citation}.",
            "original_contribution": f"{self.applicant_name} has made original contributions of major significance to the field, as required under {citation}.",
            "leading_role": f"{self.applicant_name} has performed a leading and critical role for {group_key}, an organization of distinguished reputation, as required under {citation}.",
            "awards": f"{self.applicant_name}'s receipt of this award meets the requirements of {citation}.",
        }
        return conclusions.get(standard, "")

    def _calculate_completeness_score(self, layers: Dict) -> int:
        """计算完整性分数"""
        score = 0
        if layers["claim"]:
            score += 30
        if layers["proof"]:
            score += 20
        if layers["significance"]:
            score += 40  # 最重要
        if layers["context"]:
            score += 10
        return score

    def generate_lawyer_output(self) -> str:
        """生成律师风格的 Markdown 输出"""
        composed = self.compose_all()
        lines = []

        lines.append("# EB-1A Petition - Evidence Summary")
        lines.append(f"## Petitioner: {self.applicant_name}")
        lines.append("")
        lines.append("---")

        for standard in ["membership", "published_material", "original_contribution", "leading_role", "awards"]:
            args = composed.get(standard, [])
            if not args:
                continue

            formal_name = STANDARD_FORMAL_NAMES.get(standard, standard)
            lines.append(f"\n## {formal_name}")
            lines.append("")

            for arg in args:
                completeness_icon = "✅" if arg.completeness.get("score", 0) >= 70 else "⚠️"
                lines.append(f"### {arg.title} {completeness_icon}")
                lines.append("")

                # Claim
                if arg.claim:
                    lines.append("**CLAIM:**")
                    for item in arg.claim[:3]:
                        lines.append(f"- {item.text[:200]}... [Exhibit {item.exhibit_id}]")
                    lines.append("")

                # Proof
                if arg.proof:
                    lines.append("**PROOF:**")
                    for item in arg.proof[:3]:
                        lines.append(f"- {item.text[:200]}... [Exhibit {item.exhibit_id}]")
                    lines.append("")

                # Significance (最重要)
                if arg.significance:
                    lines.append("**SIGNIFICANCE:**")
                    for item in arg.significance[:5]:
                        purpose_label = {
                            "selectivity_proof": "[Selectivity]",
                            "credibility_proof": "[Credibility]",
                            "impact_proof": "[Impact]"
                        }.get(item.purpose, "")
                        lines.append(f"- {purpose_label} {item.text[:200]}... [Exhibit {item.exhibit_id}]")
                    lines.append("")
                else:
                    lines.append("**SIGNIFICANCE:** *Missing - needs supporting evidence*")
                    lines.append("")

                # Context
                if arg.context:
                    lines.append("**CONTEXT:**")
                    for item in arg.context[:2]:
                        lines.append(f"- {item.text[:150]}... [Exhibit {item.exhibit_id}]")
                    lines.append("")

                # Conclusion
                lines.append(f"**CONCLUSION:** {arg.conclusion}")
                lines.append("")
                lines.append(f"*Exhibits: {', '.join(arg.exhibits)}*")
                lines.append("")
                lines.append("---")

        return "\n".join(lines)

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计数据"""
        composed = self.compose_all()

        stats = {
            "by_standard": {},
            "total_arguments": 0,
            "with_significance": 0,
            "avg_completeness": 0
        }

        total_score = 0
        for standard, args in composed.items():
            std_stats = {
                "count": len(args),
                "with_significance": sum(1 for a in args if a.significance),
                "avg_score": sum(a.completeness.get("score", 0) for a in args) / len(args) if args else 0
            }
            stats["by_standard"][standard] = std_stats
            stats["total_arguments"] += len(args)
            stats["with_significance"] += std_stats["with_significance"]
            total_score += sum(a.completeness.get("score", 0) for a in args)

        stats["avg_completeness"] = total_score / stats["total_arguments"] if stats["total_arguments"] > 0 else 0
        return stats


def compose_project_arguments(
    project_id: str,
    applicant_name: str = "the applicant",
    metadata: Optional[Dict] = None,
    use_entity_validator: bool = True,
    use_context_enrichment: bool = True
) -> Dict[str, Any]:
    """
    组合项目论点

    Args:
        project_id: 项目 ID
        applicant_name: 申请人姓名
        metadata: project_metadata 配置 (如果为 None 则从文件加载)
        use_entity_validator: 是否使用 EntityValidator 验证实体 (推荐开启)
        use_context_enrichment: 是否使用 Context Enrichment 添加上下文 (推荐开启)
    """
    projects_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    project_dir = projects_dir / project_id

    # 加载 snippets
    snippets = []
    enriched_used = False

    # 优先使用 enriched snippets (Context Enrichment)
    if use_context_enrichment:
        enriched_file = project_dir / "enriched" / "enriched_snippets.json"
        if enriched_file.exists():
            with open(enriched_file, 'r', encoding='utf-8') as f:
                enriched_data = json.load(f)
                snippets = enriched_data.get("snippets", [])
                enriched_used = True
                print(f"[ArgumentComposer] Using enriched snippets ({len(snippets)} total)")

    # Fallback: 从 extraction 目录加载
    if not snippets:
        extraction_dir = project_dir / "extraction"
        if extraction_dir.exists():
            for f in extraction_dir.glob("*_extraction.json"):
                with open(f, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                    snippets.extend(data.get("snippets", []))

    # 如果没有提供 metadata，尝试从文件加载
    if metadata is None:
        metadata_file = project_dir / "project_metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

    # 创建 EntityValidator (Multi-Agent: Entity Validation Agent)
    entity_validator = None
    if use_entity_validator:
        try:
            from .entity_validator import EntityValidator
            entity_validator = EntityValidator(project_id)
        except Exception as e:
            print(f"[ArgumentComposer] Warning: Could not create EntityValidator: {e}")

    # 组合
    composer = ArgumentComposer(snippets, applicant_name, metadata, entity_validator)

    return {
        "composed": {k: [asdict(a) for a in v] for k, v in composer.compose_all().items()},
        "lawyer_output": composer.generate_lawyer_output(),
        "statistics": composer.get_statistics(),
        "enrichment_info": {
            "enriched_used": enriched_used,
            "snippet_count": len(snippets),
            "snippets_with_context": sum(1 for s in snippets if s.get("context"))
        }
    }


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    result = compose_project_arguments("yaruo_qu", "Ms. Yaruo Qu")
    print(result["lawyer_output"])
    print("\n" + "=" * 60)
    print("Statistics:", json.dumps(result["statistics"], indent=2, ensure_ascii=False))
