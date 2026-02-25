"""
Standards Registry - Single source of truth for all petition types and their legal standards.

Supports EB-1A (10 criteria) and NIW (Dhanasar 3-prong test).
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Optional


PROJECT_TYPES = ["EB-1A", "NIW"]


@dataclass
class LegalStandardDef:
    """Definition of a legal standard/criterion for a petition type."""
    key: str            # Backend key: "awards", "prong1_merit"
    name: str           # Full name: "Awards", "Substantial Merit & National Importance"
    short_name: str     # Short display: "Awards", "Prong 1"
    description: str    # Legal description
    color: str          # Hex color (aligned with frontend STANDARD_COLORS)
    order: int

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_frontend_dict(self) -> Dict:
        """Convert to frontend LegalStandard format."""
        return {
            "id": f"std-{self.key}",
            "name": self.name,
            "shortName": self.short_name,
            "description": self.description,
            "color": self.color,
            "order": self.order,
        }


# ==================== EB-1A Standards ====================
# 8 C.F.R. §204.5(h)(3)(i)-(x) — 10 criteria
# Keys and colors aligned with frontend legalStandards.ts and colors.ts

EB1A_LEGAL_STANDARDS = [
    LegalStandardDef(
        key="awards",
        name="Awards",
        short_name="Awards",
        description="(i) Nationally or internationally recognized prizes or awards for excellence",
        color="#3B82F6",
        order=1,
    ),
    LegalStandardDef(
        key="membership",
        name="Membership",
        short_name="Membership",
        description="(ii) Membership in associations requiring outstanding achievements",
        color="#8B5CF6",
        order=2,
    ),
    LegalStandardDef(
        key="published",
        name="Published Material",
        short_name="Published",
        description="(iii) Published material about the alien in professional publications",
        color="#EC4899",
        order=3,
    ),
    LegalStandardDef(
        key="judging",
        name="Judging",
        short_name="Judging",
        description="(iv) Participation as a judge of the work of others",
        color="#F59E0B",
        order=4,
    ),
    LegalStandardDef(
        key="contribution",
        name="Original Contribution",
        short_name="Contribution",
        description="(v) Original scientific, scholarly, or business contributions of major significance",
        color="#10B981",
        order=5,
    ),
    LegalStandardDef(
        key="scholarly",
        name="Scholarly Articles",
        short_name="Scholarly",
        description="(vi) Authorship of scholarly articles in professional journals",
        color="#06B6D4",
        order=6,
    ),
    LegalStandardDef(
        key="display",
        name="Artistic Display",
        short_name="Display",
        description="(vii) Display of work at artistic exhibitions or showcases",
        color="#F472B6",
        order=7,
    ),
    LegalStandardDef(
        key="leading",
        name="Leading/Critical Role",
        short_name="Leading Role",
        description="(viii) Leading or critical role in distinguished organizations",
        color="#EF4444",
        order=8,
    ),
    LegalStandardDef(
        key="salary",
        name="High Salary",
        short_name="High Salary",
        description="(ix) High salary or remuneration significantly above others in the field",
        color="#84CC16",
        order=9,
    ),
    LegalStandardDef(
        key="commercial",
        name="Commercial Success",
        short_name="Commercial",
        description="(x) Commercial success in the performing arts (box office, sales, etc.)",
        color="#A78BFA",
        order=10,
    ),
]


# ==================== NIW Standards ====================
# Matter of Dhanasar, 26 I&N Dec. 884 (AAO 2016) — 3-prong test

NIW_LEGAL_STANDARDS = [
    LegalStandardDef(
        key="prong1_merit",
        name="Substantial Merit & National Importance",
        short_name="Prong 1",
        description="The proposed endeavor has both substantial merit and national importance",
        color="#3B82F6",
        order=1,
    ),
    LegalStandardDef(
        key="prong2_positioned",
        name="Well Positioned to Advance",
        short_name="Prong 2",
        description="The foreign national is well positioned to advance the proposed endeavor",
        color="#10B981",
        order=2,
    ),
    LegalStandardDef(
        key="prong3_balance",
        name="Balance of Equities",
        short_name="Prong 3",
        description="On balance, it would be beneficial to the United States to waive the requirements of a job offer and thus of a labor certification",
        color="#F59E0B",
        order=3,
    ),
]


# ==================== Registry ====================

STANDARDS_BY_TYPE: Dict[str, List[LegalStandardDef]] = {
    "EB-1A": EB1A_LEGAL_STANDARDS,
    "NIW": NIW_LEGAL_STANDARDS,
}


def get_standards_for_type(project_type: str) -> List[LegalStandardDef]:
    """Get the list of legal standards for a project type.

    Falls back to EB-1A if the type is unknown.
    """
    return STANDARDS_BY_TYPE.get(project_type, EB1A_LEGAL_STANDARDS)


def get_standard_name(project_type: str, standard_key: str) -> str:
    """Get the display name for a standard key within a project type.

    Falls back to the key itself if not found.
    """
    for std in get_standards_for_type(project_type):
        if std.key == standard_key:
            return std.name
    return standard_key


def get_standard_def(project_type: str, standard_key: str) -> Optional[LegalStandardDef]:
    """Get the full standard definition for a key."""
    for std in get_standards_for_type(project_type):
        if std.key == standard_key:
            return std
    return None


def get_all_types_with_standards() -> Dict:
    """Return all project types with their standards (for /api/projects/types endpoint)."""
    result = {}
    for ptype, standards in STANDARDS_BY_TYPE.items():
        result[ptype] = {
            "type": ptype,
            "standards": [s.to_frontend_dict() for s in standards],
            "standard_count": len(standards),
        }
    return result
