from .models import Task

class MemoryStorage:
    def __init__(self) -> None:
        self.items: list[Task] = []
