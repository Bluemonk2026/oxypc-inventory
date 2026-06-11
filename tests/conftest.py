# tests/conftest.py
import asyncio
import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop so async tests share one loop."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    try:
        loop.stop()
        loop.close()
    except RuntimeError:
        pass
