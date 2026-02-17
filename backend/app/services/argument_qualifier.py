"""
Argument Qualifier - Human-in-the-Loop 资格审查器

为每个论点生成资格检查结果，帮助人类决策：
- 检查证据完整性
- 识别不合格论点
- 提供 AI 推荐（keep/exclude/merge）
"""

import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict


# 每个标准的资格检查规则
QUALIFICATION_RULES = {
    "membership": {
        "checks": [
            {
                "key": "has_certificate",
                "label": "Has membership certificate",
                "required": True,
                "keywords": ["member", "certificate", "membership"],
            },
            {
                "key": "has_criteria",
                "label": "Has membership criteria",
                "required": True,
                "keywords": ["criteria", "requirement", "qualification", "years", "experience", "outstanding"],
            },
            {
                "key": "has_selectivity",
                "label": "Has selectivity proof (peer achievements)",
                "required": True,
                "keywords": ["olympic", "champion", "gold medal", "national team", "members include"],
            },
        ],
        "disqualify_keywords": [
            "renewed as a member",
            "professional membership",
            "coaching certification",
            "annual membership",
        ],
    },
    "published_material": {
        "checks": [
            {
                "key": "has_article",
                "label": "Has article/coverage about applicant",
                "required": True,
                "keywords": ["article", "report", "coverage", "interview", "feature"],
            },
            {
                "key": "has_media_credibility",
                "label": "Has media credibility proof",
                "required": True,
                "keywords": ["circulation", "award", "national", "leading", "major"],
            },
        ],
        "disqualify_keywords": [],
    },
    "original_contribution": {
        "checks": [
            {
                "key": "has_contribution",
                "label": "Has original contribution description",
                "required": True,
                "keywords": ["original", "innovative", "developed", "created", "invented", "system", "method"],
            },
            {
                "key": "has_impact",
                "label": "Has impact/significance proof",
                "required": True,
                "keywords": ["impact", "influence", "adopted", "used by", "benefit", "significant"],
            },
            {
                "key": "has_expert_recognition",
                "label": "Has expert recognition",
                "required": False,
                "keywords": ["recommend", "endorse", "recognize", "expert", "leader"],
            },
        ],
        "disqualify_keywords": [],
    },
    "leading_role": {
        "checks": [
            {
                "key": "has_role",
                "label": "Has leadership role evidence",
                "required": True,
                "keywords": ["founder", "ceo", "director", "head", "lead", "chief", "president"],
            },
            {
                "key": "has_org_reputation",
                "label": "Has organization reputation proof",
                "required": True,
                "keywords": ["aaa", "rating", "award", "recognized", "leading", "distinguished"],
            },
        ],
        "disqualify_keywords": [],
    },
    "awards": {
        "checks": [
            {
                "key": "has_award",
                "label": "Has award certificate/evidence",
                "required": True,
                "keywords": ["award", "prize", "medal", "honor", "recognition"],
            },
            {
                "key": "has_national_recognition",
                "label": "Has national/international recognition",
                "required": True,
                "keywords": ["national", "international", "country", "ministry", "government"],
            },
            {
                "key": "has_selectivity",
                "label": "Has award selectivity proof",
                "required": False,
                "keywords": ["criteria", "selected", "competitive", "prestigious"],
            },
        ],
        "disqualify_keywords": [],
    },
}


@dataclass
class QualificationCheck:
    """单个检查项结果"""
    key: str
    label: str
    passed: bool
    note: Optional[str] = None


@dataclass
class ArgumentQualification:
    """论点资格检查结果"""
    recommendation: str  # keep, exclude, merge
    confidence: float
    checks: List[QualificationCheck]
    completeness: int  # 0-100
    reasons: List[str]


def qualify_argument(argument: Dict, snippets: List[Dict]) -> Dict:
    """
    为单个论点生成资格检查结果

    Args:
        argument: 论点数据
        snippets: 该论点包含的 snippet 列表

    Returns:
        qualification 结果字典
    """
    # 支持 camelCase 和 snake_case
    standard_key = argument.get("standardKey") or argument.get("standard_key", "")
    rules = QUALIFICATION_RULES.get(standard_key, {})

    if not rules:
        # 没有规则，默认通过
        return asdict(ArgumentQualification(
            recommendation="keep",
            confidence=0.5,
            checks=[],
            completeness=50,
            reasons=["No specific rules for this standard"]
        ))

    # 合并所有 snippet 文本用于检查
    combined_text = " ".join([s.get("content", "") + " " + s.get("text", "") for s in snippets]).lower()

    # 执行检查
    check_results = []
    required_passed = 0
    required_total = 0
    optional_passed = 0

    for check_rule in rules.get("checks", []):
        is_required = check_rule.get("required", False)
        keywords = check_rule.get("keywords", [])

        # 检查关键词是否存在
        found_keywords = [kw for kw in keywords if kw.lower() in combined_text]
        passed = len(found_keywords) > 0

        note = None
        if passed and found_keywords:
            note = f"Found: {', '.join(found_keywords[:2])}"

        check_results.append(QualificationCheck(
            key=check_rule["key"],
            label=check_rule["label"],
            passed=passed,
            note=note
        ))

        if is_required:
            required_total += 1
            if passed:
                required_passed += 1
        elif passed:
            optional_passed += 1

    # 检查 disqualify 关键词
    disqualify_keywords = rules.get("disqualify_keywords", [])
    disqualify_found = []
    for dkw in disqualify_keywords:
        if dkw.lower() in combined_text:
            disqualify_found.append(dkw)

    # 如果发现 disqualify 关键词，添加一个失败的检查
    if disqualify_found:
        check_results.append(QualificationCheck(
            key="no_disqualify",
            label="No disqualifying indicators",
            passed=False,
            note=f"Found: {disqualify_found[0]}"
        ))

    # 计算完整性分数
    total_checks = len(check_results)
    passed_checks = sum(1 for c in check_results if c.passed)
    completeness = int((passed_checks / total_checks) * 100) if total_checks > 0 else 0

    # 决定推荐
    reasons = []

    if disqualify_found:
        recommendation = "exclude"
        confidence = 0.85
        reasons.append(f"Disqualifying indicator found: {disqualify_found[0]}")
    elif required_total > 0 and required_passed < required_total:
        missing = required_total - required_passed
        if missing >= 2:
            recommendation = "exclude"
            confidence = 0.8
            reasons.append(f"Missing {missing} required evidence types")
        else:
            recommendation = "keep"
            confidence = 0.6
            reasons.append(f"Missing {missing} required evidence type, but may still qualify")
    else:
        recommendation = "keep"
        confidence = 0.9 if completeness >= 70 else 0.7
        reasons.append("All required checks passed")

    return asdict(ArgumentQualification(
        recommendation=recommendation,
        confidence=confidence,
        checks=[asdict(c) for c in check_results],
        completeness=completeness,
        reasons=reasons
    ))


def qualify_all_arguments(arguments: List[Dict], all_snippets: List[Dict]) -> List[Dict]:
    """
    为所有论点添加资格检查结果

    Args:
        arguments: 论点列表
        all_snippets: 所有 snippet 列表

    Returns:
        带有 qualification 字段的论点列表
    """
    # 创建 snippet 查找表 (支持 id 或 snippet_id)
    snippet_map = {}
    for s in all_snippets:
        sid = s.get("id") or s.get("snippet_id")
        if sid:
            snippet_map[sid] = s

    qualified_arguments = []
    for arg in arguments:
        # 获取该论点的 snippets (支持 camelCase 和 snake_case)
        snippet_ids = arg.get("snippetIds") or arg.get("snippet_ids", [])
        arg_snippets = [snippet_map[sid] for sid in snippet_ids if sid in snippet_map]

        # 生成资格检查
        qualification = qualify_argument(arg, arg_snippets)

        # 添加到论点
        qualified_arg = {**arg, "qualification": qualification}
        qualified_arguments.append(qualified_arg)

    return qualified_arguments


def get_qualification_summary(arguments: List[Dict]) -> Dict:
    """
    获取资格检查汇总

    Returns:
        统计信息
    """
    total = len(arguments)
    keep_count = sum(1 for a in arguments if a.get("qualification", {}).get("recommendation") == "keep")
    exclude_count = sum(1 for a in arguments if a.get("qualification", {}).get("recommendation") == "exclude")
    merge_count = sum(1 for a in arguments if a.get("qualification", {}).get("recommendation") == "merge")

    avg_completeness = sum(
        a.get("qualification", {}).get("completeness", 0) for a in arguments
    ) / total if total > 0 else 0

    return {
        "total": total,
        "keep": keep_count,
        "exclude": exclude_count,
        "merge": merge_count,
        "avg_completeness": round(avg_completeness, 1),
    }


if __name__ == "__main__":
    # 测试
    import json
    from pathlib import Path

    # 加载测试数据
    project_dir = Path(__file__).parent.parent.parent / "data" / "projects" / "yaruo_qu"

    # 加载 arguments
    args_file = project_dir / "arguments" / "generated_arguments.json"
    if args_file.exists():
        with open(args_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            arguments = data.get("arguments", [])
    else:
        arguments = []

    # 加载 snippets
    snippets = []
    extraction_dir = project_dir / "extraction"
    if extraction_dir.exists():
        for f in extraction_dir.glob("*_extraction.json"):
            with open(f, 'r', encoding='utf-8') as fp:
                ext_data = json.load(fp)
                snippets.extend(ext_data.get("snippets", []))

    # 资格检查
    qualified = qualify_all_arguments(arguments, snippets)

    # 输出结果
    print("=" * 60)
    print("Qualification Summary")
    print("=" * 60)
    summary = get_qualification_summary(qualified)
    print(f"Total: {summary['total']}")
    print(f"Keep: {summary['keep']}")
    print(f"Exclude: {summary['exclude']}")
    print(f"Avg Completeness: {summary['avg_completeness']}%")
    print()

    # 显示每个论点的结果
    for arg in qualified[:5]:  # 只显示前5个
        qual = arg.get("qualification", {})
        print(f"[{qual.get('recommendation', '?').upper()}] {arg.get('title', 'Untitled')}")
        print(f"  Standard: {arg.get('standardKey', 'N/A')}")
        print(f"  Completeness: {qual.get('completeness', 0)}%")
        for check in qual.get("checks", []):
            status = "✓" if check["passed"] else "✗"
            note = f" ({check['note']})" if check.get("note") else ""
            print(f"    {status} {check['label']}{note}")
        print()
