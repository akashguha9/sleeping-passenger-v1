from __future__ import annotations

from typing import Any


PRIORITY_ORDER = {
    "SAFETY_ALARM": 0,
    "DATA_INTEGRITY": 1,
    "CHAOS_VETO": 2,
    "RISK_GUARD": 3,
    "DURABILITY_VALIDATION": 4,
    "CONTEXTUAL_INTERPRETATION": 5,
    "MODEL_INFERENCE": 6,
    "AGENT_COMMITTEE": 7,
    "NARRATIVE_ENRICHMENT": 8,
    "REPORTING": 9,
    "NON_CRITICAL_ENRICHMENT": 10,
}


class ApolloPriorityScheduler:
    def assign_priority(self, task: dict[str, Any]) -> int:
        if bool(task.get("real_execution", False)):
            return 999
        return PRIORITY_ORDER.get(str(task.get("task_type") or "NON_CRITICAL_ENRICHMENT").upper(), 50)

    def prioritize(self, tasks: list[dict[str, Any]], overload_state: str | None = None) -> list[dict[str, Any]]:
        filtered = [dict(task, priority=self.assign_priority(task)) for task in tasks if not bool(task.get("real_execution", False))]
        filtered.sort(key=lambda item: (item["priority"], str(item.get("name") or "")))
        if overload_state:
            max_tasks = 5 if str(overload_state).upper() == "HIGH" else len(filtered)
            filtered = self.degrade_task_list(filtered, max_tasks=max_tasks)
        return filtered

    def degrade_task_list(self, tasks: list[dict[str, Any]], max_tasks: int) -> list[dict[str, Any]]:
        sorted_tasks = sorted(tasks, key=lambda item: (item.get("priority", self.assign_priority(item)), str(item.get("name") or "")))
        return sorted_tasks[: max(max_tasks, 0)]
