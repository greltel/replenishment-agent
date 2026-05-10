"""
Pytest fixtures shared across all tests.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from src.data_layer.models import Material, PurchaseOrder, Movement
from src.data_layer.repository import Repository


@pytest.fixture(autouse=True)
def _stub_as_of_date():
    """For tests, anchor the effective "today" to wall-clock today so that
    fixtures using ``date.today() - timedelta(...)`` behave as expected.

    Patches both the as_of_date module AND the consumers that imported it
    at module load time (Python binds 'from X import Y' to the local name).
    """
    with patch("src.utils.as_of_date.get_effective_today", side_effect=date.today), \
         patch("src.rules.policies.get_effective_today", side_effect=date.today), \
         patch("src.agent.perception.get_effective_today", side_effect=date.today):
        yield


@pytest.fixture
def in_memory_repo() -> Repository:
    """A fresh in-memory SQLite repo for each test."""
    repo = Repository(db_url="sqlite:///:memory:")
    repo.init_schema()
    yield repo
    repo.close()


@pytest.fixture
def sample_material() -> Material:
    """A fully-populated test material."""
    m = Material(
        material_id="TEST001",
        material_type="ROH",
        uom="KG",
        abc_class="A",
        mrp_type="PD",
        lot_sizing="LFL",
        lead_time_days=5,
        safety_stock=50.0,
        reorder_point=100.0,
        moq=10.0,
        fixed_lot_size=0.0,
        standard_cost=25.0,
    )
    return m


@pytest.fixture
def sample_material_eoq() -> Material:
    """A material configured for EOQ lot sizing."""
    m = Material(
        material_id="TEST002",
        material_type="ROH",
        uom="PCS",
        abc_class="B",
        mrp_type="PD",
        lot_sizing="EOQ",
        lead_time_days=10,
        safety_stock=30.0,
        moq=5.0,
        standard_cost=10.0,
    )
    return m


@pytest.fixture
def constant_demand() -> list[float]:
    """Flat 10/day demand for 60 days."""
    return [10.0] * 60


@pytest.fixture
def variable_demand() -> list[float]:
    """Variable demand for testing."""
    base = [5, 8, 10, 15, 20, 8, 5]   # weekly pattern
    return [base[i % 7] for i in range(60)]


@pytest.fixture
def empty_pos() -> list[PurchaseOrder]:
    return []


@pytest.fixture
def sample_open_pos() -> list[PurchaseOrder]:
    """Two open POs."""
    today = date.today()
    return [
        PurchaseOrder(
            po_number="PO001",
            material_id="TEST001",
            supplier_id="SUP001",
            quantity=100.0,
            expected_date=today + timedelta(days=10),
            status="OPEN",
        ),
        PurchaseOrder(
            po_number="PO002",
            material_id="TEST001",
            supplier_id="SUP001",
            quantity=50.0,
            expected_date=today + timedelta(days=20),
            status="OPEN",
        ),
    ]


@pytest.fixture
def consumption_movements() -> list[Movement]:
    """30 days of consumption movements."""
    today = date.today()
    return [
        Movement(
            material_id="TEST001",
            plant="P001",
            movement_type="261",
            quantity=-10.0,
            posting_date=today - timedelta(days=i),
        )
        for i in range(30)
    ]
