from orbit_core.models import Task

def audit(task: Task) -> str:
    return f"audit:{task.name}"
