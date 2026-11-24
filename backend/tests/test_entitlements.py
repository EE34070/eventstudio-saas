from app.core.entitlements import METIERS, PLANS, resolve
from app.core.modules import registry


def test_core_modules_always_on():
    ent = resolve({"subscription": {"plan": "essentiel"}, "module_overrides": {"disabled": ["contacts"]}})
    assert {"contacts", "events"} <= ent.modules


def test_dependencies_are_pulled_in():
    ent = resolve({"subscription": {"plan": "essentiel", "addons": ["logistics"]}})
    assert {"logistics", "inventory", "catalog"} <= ent.modules


def test_essentiel_metier_slots():
    ent = resolve({"subscription": {"plan": "essentiel", "metier_modules": ["dj", "photobooth"]}})
    assert ent.modules & METIERS == {"dj"}


def test_all_plan_modules_exist():
    reg = registry()
    for name, plan in PLANS.items():
        assert plan["modules"] <= set(reg), name
    assert METIERS <= set(reg)


def test_market_specific_modules_flagged():
    assert registry()["payroll"].market == "FR"
