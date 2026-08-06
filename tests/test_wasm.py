import pytest

pytest.importorskip("pytest_pyodide")

from pathlib import Path

from pytest_pyodide import spawn_web_server
from pytest_pyodide.decorator import SeleniumType

ROOT = Path(__file__).resolve().parent.parent


def test_version(selenium: SeleniumType) -> None:
    dist = ROOT / "dist"
    with spawn_web_server(dist) as (host, port, _):
        url = f"http://{host}:{port}/"
        wheel = next(dist.glob("moka_py-*.whl")).name
        selenium.run_async(f"""
        import micropip
        await micropip.install("{url}{wheel}")

        import moka_py
        assert moka_py.VERSION
        """)
