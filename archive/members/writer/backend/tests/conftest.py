import asyncio
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def work_root(tmp_dir):
    p = tmp_dir / "workspace"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


@pytest.fixture
def data_dir(tmp_dir):
    p = tmp_dir / "data"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)
