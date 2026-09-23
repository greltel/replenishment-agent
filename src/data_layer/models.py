"""SQLAlchemy ORM models for the replenishment system."""
from __future__ import annotations

from datetime import datetime, date, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Date, DateTime, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


# SAP movement types (BWART) that constitute DEMAND for replenishment
# purposes. For a trading company (the case company imports and distributes
# spare parts) demand is the goods issue to customers: outbound delivery
# (601) and sales without delivery (251). For a manufacturer it is the issue
# to production orders (261), cost centres (201) and projects/networks (281).
# Used consistently by the perception module, the backtest simulators, the
# forecast tab and the copilot tools. Receipts (101) are never demand.
CONSUMPTION_MOVEMENT_TYPES: tuple[str, ...] = ("601", "251", "261", "201", "281")
GOODS_RECEIPT_MOVEMENT_TYPE = "101"


def _utcnow() -> datetime:
    """Timezone-aware UTC now (replaces deprecated datetime.utcnow)."""
    return datetime.now(timezone.utc)


class Material(Base):
    """Master data per SKU."""
    __tablename__ = "materials"

    material_id     = Column(String(20), primary_key=True)
    description     = Column(String(80))      # Material description (from MAKT.MAKTX)
    material_type   = Column(String(10))      # HAWA (trading goods), ROH, HALB, FERT ...
    uom             = Column(String(5))       # KG, PCS, L, ...
    abc_class       = Column(String(1))       # A / B / C
    mrp_type        = Column(String(5))       # PD, V1, VB, ...
    lot_sizing      = Column(String(10))      # LFL, FOQ, EOQ, POQ, WW
    lead_time_days  = Column(Integer, default=7)
    safety_stock    = Column(Float, default=0.0)
    reorder_point   = Column(Float, default=0.0)
    moq             = Column(Float, default=1.0)        # Minimum Order Quantity
    fixed_lot_size  = Column(Float, default=0.0)        # for FOQ
    standard_cost   = Column(Float, default=0.0)
    preferred_supplier_id = Column(String(20))

    # Relationships
    stocks    = relationship("Stock", back_populates="material",
                             cascade="all, delete-orphan")
    movements = relationship("Movement", back_populates="material",
                             cascade="all, delete-orphan")
    pos       = relationship("PurchaseOrder", back_populates="material",
                             cascade="all, delete-orphan")
    proposals = relationship("Proposal", back_populates="material",
                             cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Material {self.material_id} ({self.abc_class})>"


class Stock(Base):
    """Stock snapshot per (material, plant, location, date)."""
    __tablename__ = "stock"

    stock_id      = Column(Integer, primary_key=True, autoincrement=True)
    material_id   = Column(String(20), ForeignKey("materials.material_id"), index=True)
    plant         = Column(String(10))
    location      = Column(String(10))
    quantity      = Column(Float, default=0.0)
    snapshot_date = Column(Date, index=True)

    material = relationship("Material", back_populates="stocks")

    __table_args__ = (
        Index("idx_stock_material_date", "material_id", "snapshot_date"),
    )


class PurchaseOrder(Base):
    """Open & historical purchase orders."""
    __tablename__ = "purchase_orders"

    po_line_id    = Column(Integer, primary_key=True, autoincrement=True)
    po_number     = Column(String(20))
    material_id   = Column(String(20), ForeignKey("materials.material_id"), index=True)
    supplier_id   = Column(String(20))
    quantity      = Column(Float, default=0.0)
    expected_date = Column(Date, index=True)
    status        = Column(String(20))       # OPEN / RECEIVED / CANCELLED

    material = relationship("Material", back_populates="pos")


class Movement(Base):
    """Inventory movements (consumption, receipts, transfers)."""
    __tablename__ = "movements"

    movement_id   = Column(Integer, primary_key=True, autoincrement=True)
    material_id   = Column(String(20), ForeignKey("materials.material_id"), index=True)
    plant         = Column(String(10))
    movement_type = Column(String(10))       # 261=consumption, 101=goods receipt
    quantity      = Column(Float, default=0.0)  # negative for consumption
    posting_date  = Column(Date, index=True)

    material = relationship("Material", back_populates="movements")


class DemandForecast(Base):
    """Optional pre-computed demand forecasts."""
    __tablename__ = "demand_forecast"

    forecast_id  = Column(Integer, primary_key=True, autoincrement=True)
    material_id  = Column(String(20), ForeignKey("materials.material_id"), index=True)
    period       = Column(Date, index=True)
    quantity     = Column(Float, default=0.0)
    source       = Column(String(20))         # 'historical_avg', 'ml_model', 'manual'

    material = relationship("Material")


class Proposal(Base):
    """Output of the agent — replenishment proposals."""
    __tablename__ = "proposals"

    proposal_id     = Column(Integer, primary_key=True, autoincrement=True)
    material_id     = Column(String(20), ForeignKey("materials.material_id"), index=True)
    proposed_date   = Column(Date)
    proposed_qty    = Column(Float, default=0.0)
    supplier_id     = Column(String(20))
    rule_triggered  = Column(String(100))
    confidence      = Column(Float, default=1.0)
    expedite        = Column(Integer, default=0)   # boolean as int (SQLite-friendly)
    estimated_cost  = Column(Float, default=0.0)
    created_at      = Column(DateTime, default=_utcnow)

    material = relationship("Material", back_populates="proposals")

    def __repr__(self) -> str:
        return (f"<Proposal {self.material_id} qty={self.proposed_qty:.0f} "
                f"on {self.proposed_date}>")
