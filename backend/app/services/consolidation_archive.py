"""
Consolidation Archive Service - 整合过程存档服务

功能:
- 保存整合过程中的各阶段数据
- 支持回溯和调试
- 便于分析整合效果

存档点:
1. 原始引用 (整合前)
2. 候选组信息 (粗筛后)
3. LLM 响应 (每批)
4. 最终引用 (整合后)
5. 统计信息
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional


def get_consolidation_logs_dir(project_id: str) -> Path:
    """获取项目的整合日志目录"""
    from app.services.storage import get_project_dir

    logs_dir = get_project_dir(project_id) / "consolidation_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def generate_timestamp() -> str:
    """生成时间戳字符串"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


class ConsolidationArchive:
    """整合过程存档器"""

    def __init__(self, project_id: str):
        """
        初始化存档器

        Args:
            project_id: 项目 ID
        """
        self.project_id = project_id
        self.timestamp = generate_timestamp()
        self.logs_dir = get_consolidation_logs_dir(project_id)

    def _save_json(self, filename: str, data: Any):
        """保存 JSON 数据"""
        filepath = self.logs_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save_original_quotes(self, quotes: List[Dict[str, Any]]) -> str:
        """
        保存原始引用 (Step 1)

        Args:
            quotes: 原始引用列表

        Returns:
            保存的文件名
        """
        filename = f"{self.timestamp}_original_quotes.json"
        data = {
            "timestamp": datetime.now().isoformat(),
            "project_id": self.project_id,
            "stage": "original",
            "total_quotes": len(quotes),
            "quotes": quotes
        }
        self._save_json(filename, data)
        return filename

    def save_enriched_quotes(self, quotes: List[Dict[str, Any]], bbox_stats: Dict[str, Any]) -> str:
        """
        保存富化后的引用 (Step 1.5 - 添加 bbox 后)

        Args:
            quotes: 带 bbox 的引用列表
            bbox_stats: bbox 匹配统计

        Returns:
            保存的文件名
        """
        filename = f"{self.timestamp}_enriched_quotes.json"
        data = {
            "timestamp": datetime.now().isoformat(),
            "project_id": self.project_id,
            "stage": "enriched",
            "total_quotes": len(quotes),
            "bbox_stats": bbox_stats,
            "quotes": quotes
        }
        self._save_json(filename, data)
        return filename

    def save_candidate_groups(
        self,
        candidate_groups: List[Dict[str, Any]],
        single_quotes: List[Dict[str, Any]]
    ) -> str:
        """
        保存候选整合组 (Step 2)

        Args:
            candidate_groups: 候选组列表
            single_quotes: 独立引用列表

        Returns:
            保存的文件名
        """
        filename = f"{self.timestamp}_candidate_groups.json"
        data = {
            "timestamp": datetime.now().isoformat(),
            "project_id": self.project_id,
            "stage": "candidate_groups",
            "total_groups": len(candidate_groups),
            "total_singles": len(single_quotes),
            "candidate_groups": candidate_groups,
            "single_quotes": single_quotes
        }
        self._save_json(filename, data)
        return filename

    def save_batch_info(self, batches: List[List[Dict[str, Any]]], batch_stats: Dict[str, Any]) -> str:
        """
        保存分批信息 (Step 3)

        Args:
            batches: 批次列表
            batch_stats: 批次统计

        Returns:
            保存的文件名
        """
        filename = f"{self.timestamp}_batch_info.json"
        data = {
            "timestamp": datetime.now().isoformat(),
            "project_id": self.project_id,
            "stage": "batch_split",
            "batch_stats": batch_stats,
            "batches": batches
        }
        self._save_json(filename, data)
        return filename

    def save_llm_batch_response(
        self,
        batch_index: int,
        batch_items: List[Dict[str, Any]],
        prompt: str,
        response: Any,
        decisions: List[Dict[str, Any]],
        error: Optional[str] = None
    ) -> str:
        """
        保存单批次的 LLM 响应 (Step 4)

        Args:
            batch_index: 批次索引 (从 1 开始)
            batch_items: 该批次的项目
            prompt: 发送给 LLM 的 prompt
            response: LLM 的原始响应
            decisions: 解析后的决策列表
            error: 错误信息 (如果有)

        Returns:
            保存的文件名
        """
        filename = f"{self.timestamp}_llm_batch_{batch_index}.json"
        data = {
            "timestamp": datetime.now().isoformat(),
            "project_id": self.project_id,
            "stage": "llm_decision",
            "batch_index": batch_index,
            "item_count": len(batch_items),
            "prompt_length": len(prompt),
            "batch_items": batch_items,
            "prompt": prompt[:5000] + "..." if len(prompt) > 5000 else prompt,  # 截断过长的 prompt
            "raw_response": str(response)[:10000] if response else None,
            "decisions": decisions,
            "error": error
        }
        self._save_json(filename, data)
        return filename

    def save_final_quotes(
        self,
        quotes: List[Dict[str, Any]],
        stats: Dict[str, Any]
    ) -> str:
        """
        保存最终引用 (Step 5)

        Args:
            quotes: 最终引用列表
            stats: 整合统计

        Returns:
            保存的文件名
        """
        filename = f"{self.timestamp}_final_quotes.json"
        data = {
            "timestamp": datetime.now().isoformat(),
            "project_id": self.project_id,
            "stage": "final",
            "total_quotes": len(quotes),
            "stats": stats,
            "quotes": quotes
        }
        self._save_json(filename, data)
        return filename

    def save_stats(self, stats: Dict[str, Any]) -> str:
        """
        保存完整统计信息

        Args:
            stats: 统计信息

        Returns:
            保存的文件名
        """
        filename = f"{self.timestamp}_stats.json"
        data = {
            "timestamp": datetime.now().isoformat(),
            "project_id": self.project_id,
            "stage": "complete",
            "stats": stats
        }
        self._save_json(filename, data)
        return filename


def list_consolidation_logs(project_id: str) -> List[Dict[str, Any]]:
    """
    列出项目的所有整合日志

    Args:
        project_id: 项目 ID

    Returns:
        日志文件列表，每个包含 {filename, timestamp, stage, size}
    """
    logs_dir = get_consolidation_logs_dir(project_id)
    logs = []

    for filepath in sorted(logs_dir.glob("*.json"), reverse=True):
        try:
            stat = filepath.stat()
            # 从文件名解析时间戳和阶段
            parts = filepath.stem.split("_")
            timestamp = "_".join(parts[:2]) if len(parts) >= 2 else parts[0]
            stage = "_".join(parts[2:]) if len(parts) > 2 else "unknown"

            logs.append({
                "filename": filepath.name,
                "timestamp": timestamp,
                "stage": stage,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        except Exception:
            continue

    return logs


def load_consolidation_log(project_id: str, filename: str) -> Optional[Dict[str, Any]]:
    """
    加载指定的整合日志

    Args:
        project_id: 项目 ID
        filename: 日志文件名

    Returns:
        日志数据，如果不存在返回 None
    """
    logs_dir = get_consolidation_logs_dir(project_id)
    filepath = logs_dir / filename

    if not filepath.exists():
        return None

    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def cleanup_old_logs(project_id: str, keep_days: int = 7) -> int:
    """
    清理旧的整合日志

    Args:
        project_id: 项目 ID
        keep_days: 保留最近多少天的日志

    Returns:
        删除的文件数量
    """
    logs_dir = get_consolidation_logs_dir(project_id)
    cutoff = datetime.now().timestamp() - (keep_days * 24 * 60 * 60)
    deleted = 0

    for filepath in logs_dir.glob("*.json"):
        try:
            if filepath.stat().st_mtime < cutoff:
                filepath.unlink()
                deleted += 1
        except Exception:
            continue

    return deleted
