from .models import Task
from .storage import MemoryStorage

class Engine:
    def __init__(self) -> None:
        self.storage = MemoryStorage()

    def submit(self, task: Task) -> None:
        self.storage.items.append(task)
