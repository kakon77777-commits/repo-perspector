from .engine import Engine
from .models import Task

engine = Engine()

def submit(name: str) -> None:
    engine.submit(Task(name=name))
