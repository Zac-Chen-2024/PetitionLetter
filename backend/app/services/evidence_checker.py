"""
证据完整性检查器 - 基于律师框架评估证据链

检查每个 EB-1A 标准的证据是否完整，特别关注 SIGNIFICANCE 层
"""

import json
from typing import Dict, List, Any
from pathlib import Path
from collections import defaultdict

from .evidence_requirements import EVIDENCE_REQUIREMENTS, get_significance_hints


class EvidenceChecker:
    """证据完整性检查器"""

    def __init__(self, snippets: List[Dict], arguments: List[Dict] = None):
        self.snippets = snippets
        self.arguments = arguments or []
        self.snippets_by_standard = self._group_snippets_by_standard()

    def _group_snippets_by_standard(self) -> Dict[str, List[Dict]]:
        """按标准分组 snippets"""
        grouped = defaultdict(list)
        for snp in self.snippets:
            etype = snp.get("evidence_type", "other")
            # 映射到标准
            standard = self._map_evidence_type_to_standard(etype)
            grouped[standard].append(snp)
        return grouped

    def _map_evidence_type_to_standard(self, etype: str) -> str:
        """将证据类型映射到 EB-1A 标准"""
        mapping = {
            "award": "awards",
            "membership": "membership",
            "membership_criteria": "membership",
            "membership_evaluation": "membership",
            "peer_achievement": "membership",
            "publication": "published_material",
            "media_coverage": "published_material",
            "source_credibility": "published_material",
            "contribution": "original_contribution",
            "quantitative_impact": "original_contribution",
            "leadership": "leading_role",
            "judging": "judging",
            "article": "scholarly_articles",
            "exhibition": "exhibitions",
            "recommendation": "original_contribution",
            "peer_assessment": "original_contribution",
        }
        return mapping.get(etype, "other")

    def check_all_standards(self) -> Dict[str, Any]:
        """检查所有标准的证据完整性"""
        results = {}

        for standard in ["membership", "published_material", "original_contribution", "leading_role", "awards"]:
            results[standard] = self.check_standard(standard)

        # 总体评估
        results["summary"] = self._generate_summary(results)
        return results

    def check_standard(self, standard: str) -> Dict[str, Any]:
        """检查单个标准的证据完整性"""
        snippets = self.snippets_by_standard.get(standard, [])

        if not snippets:
            return {
                "status": "missing",
                "coverage": 0,
                "snippet_count": 0,
                "layers": {},
                "missing": self._get_all_required(standard),
                "recommendations": [f"需要补充 {standard} 相关证据"]
            }

        # 分析证据层级分布
        layers = self._analyze_layers(snippets)

        # 检查每层的覆盖
        layer_analysis = {}
        missing = []

        for layer in ["claim", "proof", "significance", "context"]:
            layer_snippets = layers.get(layer, [])
            required = self._get_required_for_layer(standard, layer)

            found = []
            not_found = []

            for req in required:
                if self._check_requirement_met(req, layer_snippets, snippets):
                    found.append(req)
                else:
                    not_found.append(req)
                    missing.append({"layer": layer, **req})

            layer_analysis[layer] = {
                "count": len(layer_snippets),
                "found": found,
                "missing": not_found
            }

        # 计算覆盖率（重点关注 significance 层）
        total_required = sum(
            len(self._get_required_for_layer(standard, l))
            for l in ["claim", "proof", "significance"]
        )
        total_found = sum(
            len(layer_analysis[l]["found"])
            for l in ["claim", "proof", "significance"]
        )
        coverage = total_found / total_required if total_required > 0 else 0

        # 生成建议
        recommendations = self._generate_recommendations(standard, layer_analysis, missing)

        return {
            "status": "complete" if coverage >= 0.8 else "partial" if coverage >= 0.5 else "weak",
            "coverage": round(coverage, 2),
            "snippet_count": len(snippets),
            "layers": layer_analysis,
            "missing": missing,
            "recommendations": recommendations
        }

    def _analyze_layers(self, snippets: List[Dict]) -> Dict[str, List[Dict]]:
        """分析 snippets 的层级分布"""
        layers = defaultdict(list)
        for snp in snippets:
            layer = snp.get("evidence_layer", "claim")
            layers[layer].append(snp)
        return layers

    def _get_required_for_layer(self, standard: str, layer: str) -> List[Dict]:
        """获取某标准某层级的必需证据"""
        if standard not in EVIDENCE_REQUIREMENTS:
            return []
        layer_items = EVIDENCE_REQUIREMENTS[standard].get(layer, [])
        return [item for item in layer_items if item.get("required", False)]

    def _get_all_required(self, standard: str) -> List[Dict]:
        """获取某标准的所有必需证据"""
        all_required = []
        if standard in EVIDENCE_REQUIREMENTS:
            for layer, items in EVIDENCE_REQUIREMENTS[standard].items():
                for item in items:
                    if item.get("required", False):
                        all_required.append({"layer": layer, **item})
        return all_required

    def _check_requirement_met(self, req: Dict, layer_snippets: List[Dict], all_snippets: List[Dict]) -> bool:
        """检查某个需求是否被满足"""
        hints = req.get("hints", [])
        key = req.get("key", "")

        # 检查 layer_snippets 中是否有匹配的
        for snp in layer_snippets:
            text = snp.get("text", "").lower()
            etype = snp.get("evidence_type", "")
            purpose = snp.get("evidence_purpose", "")

            # 检查关键词匹配
            if hints:
                if any(hint.lower() in text for hint in hints):
                    return True

            # 检查证据类型/目的匹配
            if key in ["quantitative_impact", "peer_achievements", "circulation_data", "media_awards", "org_reputation_proof", "event_scale"]:
                if etype in ["quantitative_impact", "peer_achievement", "source_credibility"] or \
                   purpose in ["impact_proof", "selectivity_proof", "credibility_proof"]:
                    return True

        return False

    def _generate_recommendations(self, standard: str, layers: Dict, missing: List[Dict]) -> List[str]:
        """生成改进建议"""
        recommendations = []

        # 检查 significance 层
        sig_missing = [m for m in missing if m.get("layer") == "significance"]
        if sig_missing:
            recommendations.append(
                f"⚠️ SIGNIFICANCE层缺失 ({len(sig_missing)}项): " +
                ", ".join(m["desc"] for m in sig_missing[:3])
            )

        # 特定标准的建议
        if standard == "membership":
            if any(m["key"] == "peer_achievements" for m in missing):
                recommendations.append("💡 建议：提取其他杰出会员的成就（如奥运冠军、行业领袖）以证明协会的选择性")

        elif standard == "published_material":
            if any(m["key"] == "circulation_data" for m in missing):
                recommendations.append("💡 建议：提取媒体发行量/阅读量数据以证明是'major media'")
            if any(m["key"] == "media_awards" for m in missing):
                recommendations.append("💡 建议：提取媒体获得的奖项以证明其权威性")

        elif standard == "original_contribution":
            if any(m["key"] == "quantitative_impact" for m in missing):
                recommendations.append("💡 建议：提取量化影响数据（如用户数、浏览量、培训人数）")

        elif standard == "leading_role":
            if any(m["key"] == "org_reputation_proof" for m in missing):
                recommendations.append("💡 建议：提取组织的AAA评级、官方合作伙伴等证明'distinguished reputation'")
            if any(m["key"] == "event_scale" for m in missing):
                recommendations.append("💡 建议：提取活动规模数据（参与人数、国家数）")

        return recommendations

    def _generate_summary(self, results: Dict) -> Dict[str, Any]:
        """生成总体评估摘要"""
        total_coverage = 0
        standards_checked = 0
        all_missing_significance = []

        for standard, result in results.items():
            if standard == "summary":
                continue
            if result.get("snippet_count", 0) > 0:
                total_coverage += result.get("coverage", 0)
                standards_checked += 1

            # 收集所有缺失的 significance 证据
            for m in result.get("missing", []):
                if m.get("layer") == "significance":
                    all_missing_significance.append({
                        "standard": standard,
                        **m
                    })

        avg_coverage = total_coverage / standards_checked if standards_checked > 0 else 0

        # 总体评分
        score = int(avg_coverage * 100)

        # 核心差距
        core_gaps = []
        if all_missing_significance:
            core_gaps.append({
                "type": "SIGNIFICANCE层证据不足",
                "count": len(all_missing_significance),
                "details": all_missing_significance[:5]
            })

        return {
            "score": score,
            "avg_coverage": round(avg_coverage, 2),
            "standards_with_evidence": standards_checked,
            "core_gaps": core_gaps,
            "verdict": "strong" if score >= 80 else "moderate" if score >= 60 else "weak"
        }


def check_project_evidence(project_id: str) -> Dict[str, Any]:
    """检查项目的证据完整性"""
    projects_dir = Path(__file__).parent.parent.parent / "data" / "projects"
    project_dir = projects_dir / project_id

    # 加载所有 snippets
    snippets = []
    extraction_dir = project_dir / "extraction"
    if extraction_dir.exists():
        for f in extraction_dir.glob("*_extraction.json"):
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
                snippets.extend(data.get("snippets", []))

    # 加载 arguments
    arguments = []
    args_file = project_dir / "arguments" / "generated_arguments.json"
    if args_file.exists():
        with open(args_file, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
            arguments = data.get("arguments", [])

    # 运行检查
    checker = EvidenceChecker(snippets, arguments)
    return checker.check_all_standards()


def print_evidence_report(results: Dict[str, Any]):
    """打印证据完整性报告"""
    print("\n" + "=" * 70)
    print("EB-1A 证据完整性报告")
    print("=" * 70)

    summary = results.get("summary", {})
    print(f"\n📊 总体评分: {summary.get('score', 0)}/100 ({summary.get('verdict', 'unknown')})")
    print(f"📈 平均覆盖率: {summary.get('avg_coverage', 0):.0%}")

    for standard in ["membership", "published_material", "original_contribution", "leading_role", "awards"]:
        if standard not in results:
            continue
        result = results[standard]
        print(f"\n### {standard.upper()}")
        print(f"   状态: {result['status']} | 覆盖率: {result['coverage']:.0%} | Snippets: {result['snippet_count']}")

        # 层级分析
        for layer in ["claim", "proof", "significance"]:
            layer_data = result["layers"].get(layer, {})
            count = layer_data.get("count", 0)
            missing = len(layer_data.get("missing", []))
            status = "✓" if missing == 0 else "⚠️"
            print(f"   {status} {layer}: {count} snippets, {missing} missing")

        # 建议
        for rec in result.get("recommendations", [])[:2]:
            print(f"   {rec}")

    # 核心差距
    if summary.get("core_gaps"):
        print("\n" + "-" * 70)
        print("🎯 核心差距:")
        for gap in summary["core_gaps"]:
            print(f"   • {gap['type']}: {gap['count']}项")


if __name__ == "__main__":
    # 测试 — 用法: python -m app.services.evidence_checker <project_id>
    import sys
    project_id = sys.argv[1] if len(sys.argv) > 1 else "test_project"
    results = check_project_evidence(project_id)
    print_evidence_report(results)
