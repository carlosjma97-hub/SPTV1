import pytest

from docprinter.backend_fake import FakeBackend
from docprinter.paths import get_dirs


@pytest.fixture
def fake():
    return FakeBackend.demo()


@pytest.fixture
def dirs(tmp_path):
    return get_dirs(tmp_path / "data").ensure()


def no_sleep(_):
    pass
