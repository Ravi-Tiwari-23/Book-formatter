from pathlib import Path
import tomllib

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_bookloom_is_the_installable_application_package() -> None:
    import bookloom

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "bookloom"
    assert bookloom.__version__ == metadata["project"]["version"]


def test_streamlit_home_identifies_bookloom() -> None:
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=10).run()

    assert not app.exception
    assert app.title[0].value == "Bookloom"
    assert "PDF" in app.caption[0].value
