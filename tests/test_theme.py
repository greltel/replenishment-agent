"""Dashboard theme: the light and dark palettes cover the same roles, and
apply_mode() rebinds the names every tab reads (theme.TEXT_PRIMARY, ...)."""
import pytest

from dashboard import theme


@pytest.fixture(autouse=True)
def _back_to_light():
    yield
    theme.apply_mode("light")


def test_palettes_cover_the_same_roles():
    assert set(theme._LIGHT) == set(theme._DARK)
    for role in ("ABC_COLORS", "STATUS", "BADGE"):
        assert set(theme._LIGHT[role]) == set(theme._DARK[role])


def test_apply_mode_rebinds_module_names_and_css():
    assert theme.MODE == "light" and theme.TEXT_PRIMARY == theme._LIGHT["TEXT_PRIMARY"]
    assert theme.apply_mode("dark") == "dark"
    assert theme.TEXT_PRIMARY == theme._DARK["TEXT_PRIMARY"]
    assert theme.ABC_COLORS["A"] == theme._DARK["ABC_COLORS"]["A"]
    assert theme._DARK["SURFACE"] in theme._css() and theme._LIGHT["SURFACE"] not in theme._css()
    assert theme.apply_mode("no-such-mode") == "light"       # unknown → light
    assert theme.TEXT_PRIMARY == theme._LIGHT["TEXT_PRIMARY"]


def test_material_type_label_hides_company_types():
    assert theme.material_type_label("HAWA") == "Εμπόρευμα"
    assert theme.material_type_label("ZMAT") == "Ειδικός τύπος της εταιρείας"
    assert theme.material_type_label(None) == "—" and theme.material_type_label(" ") == "—"
    assert theme.material_type_label(float("nan")) == "—"
