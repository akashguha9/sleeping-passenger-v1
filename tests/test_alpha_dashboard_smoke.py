"""Dashboard import/render smoke test (no Streamlit dependency)."""

from __future__ import annotations


class _RecordingSt:
    """Minimal Streamlit stand-in: records calls, returns inert values."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        def _record(*args, **kwargs):
            self.calls.append(name)
            return None  # text_area returns None -> parse box stays idle

        return _record


def test_alpha_framework_section_renders_without_streamlit() -> None:
    from src.dashboard.alpha_framework_view import render_alpha_framework_section

    fake = _RecordingSt()
    render_alpha_framework_section(fake)
    # The section must render headline panels and tables.
    assert "subheader" in fake.calls
    assert fake.calls.count("dataframe") >= 4
    assert "caption" in fake.calls


def test_dashboard_module_imports_cleanly() -> None:
    import src.dashboard.streamlit_app  # noqa: F401
    import src.dashboard.alpha_framework_view  # noqa: F401
