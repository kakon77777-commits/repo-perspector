from orbit_core.engine import Engine
from orbit_core.models import Task

def test_submit() -> None:
    engine = Engine()
    engine.submit(Task("x"))
    assert len(engine.storage.items) == 1
