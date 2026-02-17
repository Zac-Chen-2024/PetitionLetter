"""
Argument Composer - 律师风格论点组合器

将碎片化的 snippets 组合成结构化的律师风格论点：
- Membership: 按协会分组
- Published Material: 按媒体分组
- Original Contribution: 合并成整体
- Leading Role: 按组织分组
- Awards: 按奖项分组

每个论点包含: Claim + Proof + Significance + Context + Conclusion
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

# ============================================
# P0: 媒体名称映射 (Exhibit → Media Name)
# ============================================
EXHIBIT_TO_MEDIA = {
    # The Jakarta Post (D1-D4)
    "D1": "The Jakarta Post",
    "D2": "The Jakarta Post",
    "D3": "The Jakarta Post",
    "D4": "The Jakarta Post",
    # China Sports Daily (D5-D8)
    "D5": "China Sports Daily",
    "D6": "China Sports Daily",
    "D7": "China Sports Daily",
    "D8": "China Sports Daily",
    # Sixth Tone (D9-D13)
    "D9": "Sixth Tone",
    "D10": "Sixth Tone",
    "D11": "Sixth Tone",
    "D12": "Sixth Tone",
    "D13": "Sixth Tone",
}

# ============================================
# P1: Membership 资格过滤规则
# ============================================
# 这些协会只是普通会员资格，不满足 "outstanding achievements" 要求
DISQUALIFIED_MEMBERSHIPS = {
    "usa weightlifting",
    "nsca",
    "national strength and conditioning association",
}

# 合格的协会（有选择性要求）
QUALIFIED_MEMBERSHIPS = {
    "shanghai fitness bodybuilding association": "Shanghai Fitness Bodybuilding Association",
    "china weightlifting association": "China Weightlifting Association",
}

# ============================================
# P2: Leading Role 组织修正规则
# ============================================
# 申请人名字变体（不应作为组织名）
APPLICANT_NAME_VARIANTS = {
    "yaruo qu", "ms. qu", "gaby", "gabriella", "coach gaby", "ms. yaruo qu",
}

# 组织合并规则 (源 → 目标)
ORGANIZATION_MERGE = {
    "venus weightlifting": "Shanghai Yiqing Fitness Management Co., Ltd.",
    "venus weightlifting club": "Shanghai Yiqing Fitness Management Co., Ltd.",
}

# 合格的组织
QUALIFIED_ORGANIZATIONS = {
    "shanghai yiqing": "Shanghai Yiqing Fitness Management Co., Ltd.",
    "ishtar health": "ISHTAR Health Pte. Ltd.",
}


@dataclass
class EvidenceItem:
    """单条证据"""
    text: str
    exhibit_id: str
    purpose: str  # direct_proof, selectivity_proof, credibility_proof, impact_proof
    snippet_id: str = ""


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
    """论点组合器"""

    def __init__(self, snippets: List[Dict], applicant_name: str = "Ms. Qu"):
        self.snippets = snippets
        self.applicant_name = applicant_name
        self.snippets_by_standard = self._group_by_standard()

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
        """证据类型映射到标准"""
        mapping = {
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
        return mapping.get(etype)

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
            return [self._compose_single_argument(snippets, standard, "BAT Training System")]
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

            if standard == "membership":
                # 按协会分组 - P1: 过滤不合格会员
                group_key = self._extract_association_name(text, subject)
            elif standard == "published_material":
                # 按媒体分组 - P0: 使用 Exhibit 映射
                group_key = self._extract_media_name(text, snp.get("exhibit_id", ""))
            elif standard == "leading_role":
                # 按组织分组 - P2: 排除申请人名，合并组织
                group_key = self._extract_organization_name(text, subject)
            elif standard == "awards":
                # 按奖项分组
                group_key = self._extract_award_name(text)
            else:
                group_key = "default"

            # 只有合格的实体才加入分组 (group_key 不为 None)
            if group_key is not None:
                groups[group_key].append(snp)

        return groups

    def _extract_association_name(self, text: str, subject: str) -> str:
        """提取协会名称 - P1: 过滤不合格会员"""
        text_lower = text.lower()

        # 检查是否是不合格会员 (普通专业认证)
        for disqualified in DISQUALIFIED_MEMBERSHIPS:
            if disqualified in text_lower:
                return None  # 返回 None 表示应该被过滤

        # 检查是否是合格会员
        for pattern, formal_name in QUALIFIED_MEMBERSHIPS.items():
            if pattern in text_lower:
                return formal_name

        # 其他协会 - 检查是否有选择性证据
        # 如果没有明确识别，也返回 None 以避免碎片化
        return None

    def _extract_media_name(self, text: str, exhibit_id: str) -> str:
        """提取媒体名称 - 使用 Exhibit 映射表"""
        # P0: 只有 D 系列 Exhibit 才是 Published Material
        # 其他系列 (C, E, F, G) 应该被过滤
        if not exhibit_id.startswith("D"):
            return None  # 返回 None 表示不属于 Published Material

        # P0: 使用 Exhibit → Media 映射
        if exhibit_id in EXHIBIT_TO_MEDIA:
            return EXHIBIT_TO_MEDIA[exhibit_id]

        # 备用：从文本中识别
        media_patterns = {
            "jakarta post": "The Jakarta Post",
            "china sports daily": "China Sports Daily",
            "sixth tone": "Sixth Tone",
            "the paper": "Sixth Tone",  # The Paper 是 Sixth Tone 的中文版
            "titan sports": "China Sports Daily",  # 体坛周报属于同一集团
        }
        for pattern, name in media_patterns.items():
            if pattern in text.lower():
                return name

        # D 系列但未识别的媒体
        return "Other Media"

    def _extract_organization_name(self, text: str, subject: str) -> str:
        """提取组织名称 - P2: 排除申请人名，合并组织"""
        text_lower = text.lower()
        subject_lower = subject.lower() if subject else ""

        # P2: 排除申请人名字作为组织名
        for name_variant in APPLICANT_NAME_VARIANTS:
            if name_variant in subject_lower:
                subject = None  # 清除申请人名作为 subject
                break

        # P2: 检查是否需要合并
        for pattern, target in ORGANIZATION_MERGE.items():
            if pattern in text_lower:
                return target

        # 检查合格组织
        for pattern, formal_name in QUALIFIED_ORGANIZATIONS.items():
            if pattern in text_lower:
                return formal_name

        # 如果没有识别到合格组织，返回 None
        return None

    def _extract_award_name(self, text: str) -> str:
        """提取奖项名称"""
        patterns = [
            r"achievement award.*fitness industry",
            r"first prize",
            r"gold medal",
        ]
        for p in patterns:
            if re.search(p, text, re.IGNORECASE):
                return "Achievement Award in Fitness Industry"
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

            item = EvidenceItem(
                text=snp.get("text", "")[:500],
                exhibit_id=snp.get("exhibit_id", ""),
                purpose=snp.get("evidence_purpose", "direct_proof"),
                snippet_id=snp.get("snippet_id", "")
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
            "original_contribution": f"{self.applicant_name}'s Original BAT Training System and Its Major Significance",
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
                    lines.append("**SIGNIFICANCE:** ⭐")
                    for item in arg.significance[:5]:
                        purpose_label = {
                            "selectivity_proof": "[Selectivity]",
                            "credibility_proof": "[Credibility]",
                            "impact_proof": "[Impact]"
                        }.get(item.purpose, "")
                        lines.append(f"- {purpose_label} {item.text[:200]}... [Exhibit {item.exhibit_id}]")
                    lines.append("")
                else:
                    lines.append("**SIGNIFICANCE:** ⚠️ *Missing - needs supporting evidence*")
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


def compose_project_arguments(project_id: str, applicant_name: str = "Ms. Qu") -> Dict[str, Any]:
    """组合项目论点"""
    projects_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    project_dir = projects_dir / project_id

    # 加载 snippets
    snippets = []
    extraction_dir = project_dir / "extraction"
    if extraction_dir.exists():
        for f in extraction_dir.glob("*_extraction.json"):
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
                snippets.extend(data.get("snippets", []))

    # 组合
    composer = ArgumentComposer(snippets, applicant_name)

    return {
        "composed": {k: [asdict(a) for a in v] for k, v in composer.compose_all().items()},
        "lawyer_output": composer.generate_lawyer_output(),
        "statistics": composer.get_statistics()
    }


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    result = compose_project_arguments("yaruo_qu", "Ms. Yaruo Qu")
    print(result["lawyer_output"])
    print("\n" + "=" * 60)
    print("Statistics:", json.dumps(result["statistics"], indent=2, ensure_ascii=False))
