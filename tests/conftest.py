from pathlib import Path
import pytest

from oso.core.paths import AppPaths
from oso.core.service import AppService


@pytest.fixture
def service(tmp_path):
    return AppService(AppPaths.create("web", tmp_path / "data", tmp_path / "videos"), "web")
