"""
Entity Validation Agent - 实体验证服务

功能:
1. 验证提取的实体是否是真实的组织/媒体/人物
2. 过滤垃圾实体（句子片段、动词短语等）
3. 生成验证后的实体列表供 argument_composer 使用

验证规则:
- ORGANIZATION: 必须含公司/组织后缀或是已知组织类型
- MEDIA: 必须是已知媒体或含媒体关键词
- PERSON: 必须有完整姓名格式
"""

import re
from typing import Dict, List, Any, Optional, Set
from pathlib import Path
import json


# ============================================
# 验证规则
# ============================================

# 组织后缀 - 必须包含这些词才能被认为是组织
ORGANIZATION_SUFFIXES = {
    # 公司类型
    "ltd", "ltd.", "limited", "inc", "inc.", "incorporated",
    "co.", "co", "corp", "corp.", "corporation",
    "llc", "llp", "pte", "pte.", "gmbh", "ag",
    # 组织类型
    "club", "association", "federation", "committee", "council",
    "institute", "academy", "school", "university", "college",
    "center", "centre", "group", "team",
    # 中文组织
    "有限公司", "股份公司", "协会", "联合会", "委员会",
}

# 组织关键词 - 包含这些词的可能是组织
ORGANIZATION_KEYWORDS = {
    "sports", "athletic",
    "healthcare", "health", "medical",
    "media", "press", "publishing", "daily", "post", "times",
    "government", "ministry", "administration",
    "technology", "engineering", "research", "education",
}

# 媒体关键词
MEDIA_KEYWORDS = {
    "daily", "post", "times", "news", "journal", "magazine",
    "press", "media", "publishing", "broadcast", "tv", "radio",
    "newspaper", "tribune", "herald", "gazette", "chronicle",
    "日报", "晚报", "时报", "新闻", "杂志", "周刊",
}

# 已知媒体 (常见的)
KNOWN_MEDIA = {
    # 国际媒体
    "the jakarta post", "jakarta post",
    "new york times", "washington post", "wall street journal",
    "reuters", "associated press", "bbc", "cnn", "guardian",
    "financial times", "economist", "forbes", "bloomberg",
    "people's daily", "xinhua",
}

# 垃圾模式 - 匹配这些的一定是垃圾
GARBAGE_PATTERNS = [
    # 动词短语
    r"^(has|is|was|were|did|does|do|had|have|been|being)\s",
    r"^(to|for|at|with|by|from|in|on|of)\s",
    r"\s(has|is|was|were|did|does)\s",
    # 句子片段
    r"^(her|his|their|its|my|our|your)\s",
    r"^(and|or|but)\s",  # 注意: 移除了 "the/a/an" 因为 "The Jakarta Post" 是有效的
    r"^(this|that|these|those)\s",
    r"^(i|we|he|she|they)\s",  # 代词开头
    r"hereby",  # 法律术语
    # 动词形式
    r"^(found|driven|led|made|played|served)\s",
    r"^(on behalf of)$",
    # 太短或只有单词碎片
    r"^.{1,4}$",  # 4个字符以下
    r"^(co|inc|ltd|llc|pte)\.?$",  # 只有公司后缀
]

# 排除的"组织" - 这些看起来像组织但不是
EXCLUDED_NAMES = {
    "her effort", "on behalf of", "s first", "found a",
    "the applicant",
    "the event", "the competition", "the program",
}


class EntityValidator:
    """实体验证器"""

    def __init__(self, project_id: str):
        """
        初始化验证器

        Args:
            project_id: 项目 ID，用于加载提取的实体
        """
        self.project_id = project_id
        self.projects_dir = Path(__file__).parent.parent.parent / "data" / "projects"
        self.project_dir = self.projects_dir / project_id

        # 加载提取的实体
        self.extracted_entities = self._load_extracted_entities()

        # 构建验证后的实体集合
        self.valid_organizations: Set[str] = set()
        self.valid_media: Set[str] = set()
        self.valid_persons: Set[str] = set()

        self._validate_all_entities()

    def _load_extracted_entities(self) -> List[Dict]:
        """加载所有提取的实体"""
        entities = []
        extraction_dir = self.project_dir / "extraction"

        if not extraction_dir.exists():
            return entities

        for f in extraction_dir.glob("*_extraction.json"):
            if "combined" in f.name:
                continue
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    for e in data.get("entities", []):
                        e["source_exhibit"] = f.stem.replace("_extraction", "")
                        entities.append(e)
            except Exception:
                continue

        return entities

    def _validate_all_entities(self):
        """验证所有实体"""
        for entity in self.extracted_entities:
            name = entity.get("name", "")
            entity_type = entity.get("type", "").lower()

            if not name:
                continue

            # 先检查是否是垃圾
            if self._is_garbage(name):
                continue

            # 根据类型验证
            if entity_type == "organization":
                # 先检查是否其实是媒体
                if self._is_valid_media(name):
                    self.valid_media.add(name)
                elif self._is_valid_organization(name):
                    self.valid_organizations.add(name)
            elif entity_type == "media":
                if self._is_valid_media(name):
                    self.valid_media.add(name)
            elif entity_type == "person":
                if self._is_valid_person(name):
                    self.valid_persons.add(name)

    def _is_garbage(self, name: str) -> bool:
        """检查是否是垃圾实体"""
        name_lower = name.lower().strip()

        # 检查排除列表
        if name_lower in EXCLUDED_NAMES:
            return True

        # 检查垃圾模式
        for pattern in GARBAGE_PATTERNS:
            if re.search(pattern, name_lower, re.IGNORECASE):
                return True

        return False

    def _is_valid_organization(self, name: str) -> bool:
        """验证是否是有效组织"""
        name_lower = name.lower()

        # 检查组织后缀
        for suffix in ORGANIZATION_SUFFIXES:
            if suffix in name_lower:
                return True

        # 检查组织关键词 (需要至少2个词)
        words = name.split()
        if len(words) >= 2:
            for keyword in ORGANIZATION_KEYWORDS:
                if keyword in name_lower:
                    return True

        return False

    def _is_valid_media(self, name: str) -> bool:
        """验证是否是有效媒体"""
        name_lower = name.lower()

        # 检查已知媒体
        if name_lower in KNOWN_MEDIA:
            return True

        # 检查媒体关键词
        for keyword in MEDIA_KEYWORDS:
            if keyword in name_lower:
                return True

        return False

    def _is_valid_person(self, name: str) -> bool:
        """验证是否是有效人名"""
        # 至少2个词，每个词首字母大写
        words = name.split()
        if len(words) < 2:
            return False

        # 检查是否像人名（首字母大写）
        for word in words:
            if not word[0].isupper():
                return False

        return True

    def is_valid_organization(self, name: str) -> bool:
        """检查名称是否在有效组织列表中"""
        # 精确匹配
        if name in self.valid_organizations:
            return True

        # 模糊匹配（忽略大小写）
        name_lower = name.lower()
        for org in self.valid_organizations:
            if org.lower() == name_lower:
                return True
            # 部分匹配（组织名包含在内）
            if name_lower in org.lower() or org.lower() in name_lower:
                return True

        return False

    def is_valid_media(self, name: str) -> bool:
        """检查名称是否在有效媒体列表中"""
        if name in self.valid_media:
            return True

        name_lower = name.lower()
        for media in self.valid_media:
            if media.lower() == name_lower:
                return True

        return False

    def get_validation_report(self) -> Dict[str, Any]:
        """获取验证报告"""
        return {
            "project_id": self.project_id,
            "total_entities": len(self.extracted_entities),
            "valid_organizations": len(self.valid_organizations),
            "valid_media": len(self.valid_media),
            "valid_persons": len(self.valid_persons),
            "organizations": sorted(list(self.valid_organizations)),
            "media": sorted(list(self.valid_media)),
            "persons": sorted(list(self.valid_persons))[:20],  # 只显示前20个
        }


def validate_project_entities(project_id: str) -> Dict[str, Any]:
    """
    验证项目实体

    Args:
        project_id: 项目 ID

    Returns:
        验证报告
    """
    validator = EntityValidator(project_id)
    return validator.get_validation_report()


def get_valid_organizations(project_id: str) -> Set[str]:
    """获取项目的有效组织列表"""
    validator = EntityValidator(project_id)
    return validator.valid_organizations


def get_valid_media(project_id: str) -> Set[str]:
    """获取项目的有效媒体列表"""
    validator = EntityValidator(project_id)
    return validator.valid_media
