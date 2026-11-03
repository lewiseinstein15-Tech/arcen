"""Read the original local task bank; no task executes on the host."""

import json
from pathlib import Path

BANK = Path(__file__).with_name("local_tasks.json")


def load_tasks() -> list[dict]:
    tasks = json.loads(BANK.read_text(encoding="utf-8"))
    if not isinstance(tasks, list) or len(tasks) != 20:
        raise ValueError("expected exactly 20 local tasks")
    ids = set()
    for task in tasks:
        if set(task) != {"id", "goal", "files"} or not task["id"].startswith("local-"):
            raise ValueError("invalid local task")
        if task["id"] in ids or not task["goal"]:
            raise ValueError("duplicate task or empty goal")
        ids.add(task["id"])
        if set(task["files"]) != {"solution.py", "test_solution.py"}:
            raise ValueError("invalid local task files")
        for source in task["files"].values():
            if not isinstance(source, str) or len(source.encode()) > 65536:
                raise ValueError("invalid local task source")
    return tasks
