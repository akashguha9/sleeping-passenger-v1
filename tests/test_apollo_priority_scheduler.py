from __future__ import annotations

from scripts.core.apollo_priority_scheduler import ApolloPriorityScheduler


def test_apollo_priority_scheduler_priority_and_degrade_behavior() -> None:
    scheduler = ApolloPriorityScheduler()
    tasks = [
        {"name": "report", "task_type": "REPORTING"},
        {"name": "safety", "task_type": "SAFETY_ALARM"},
        {"name": "narrative", "task_type": "NON_CRITICAL_ENRICHMENT"},
        {"name": "bad", "task_type": "MODEL_INFERENCE", "real_execution": True},
    ]
    prioritized = scheduler.prioritize(tasks)
    assert prioritized[0]["name"] == "safety"
    assert all(task["name"] != "bad" for task in prioritized)
    degraded = scheduler.degrade_task_list(prioritized, max_tasks=1)
    assert len(degraded) == 1
    assert degraded[0]["name"] == "safety"
