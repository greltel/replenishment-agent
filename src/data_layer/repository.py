"""
Repository pattern — single point of data access.
Hides SQLAlchemy details from agent / MRP / rules code.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from src.config import config
from src.data_layer.models import (
    Base, Material, Stock, PurchaseOrder, Movement, DemandForecast, Proposal
)


class Repository:
    """Data access layer."""

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or config.database_url
        self.engine = create_engine(self.db_url, echo=False, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session: Session = self.SessionLocal()

    # ---------- DDL ----------
    def init_schema(self, drop_existing: bool = False) -> None:
        if drop_existing:
            Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)

    # ---------- Materials ----------
    def get_all_materials(self) -> list[Material]:
        return self.session.query(Material).all()

    def get_material(self, material_id: str) -> Optional[Material]:
        return self.session.get(Material, material_id)

    def get_materials_by_class(self, abc_class: str) -> list[Material]:
        return self.session.query(Material).filter_by(abc_class=abc_class).all()

    # ---------- Stock ----------
    def get_current_stock(self, material_id: str,
                          plant: Optional[str] = None,
                          as_of: Optional[date] = None) -> float:
        """
        Latest stock quantity for a material. If `as_of` is given, returns the
        snapshot on or just before that date — useful for backtesting.
        """
        q = self.session.query(Stock).filter(Stock.material_id == material_id)
        if plant:
            q = q.filter(Stock.plant == plant)
        if as_of:
            q = q.filter(Stock.snapshot_date <= as_of)

        latest = q.order_by(Stock.snapshot_date.desc()).first()
        return float(latest.quantity) if latest else 0.0

    def get_stock_history(self, material_id: str,
                           start: Optional[date] = None,
                           end: Optional[date] = None) -> list[Stock]:
        q = self.session.query(Stock).filter(Stock.material_id == material_id)
        if start:
            q = q.filter(Stock.snapshot_date >= start)
        if end:
            q = q.filter(Stock.snapshot_date <= end)
        return q.order_by(Stock.snapshot_date).all()

    # ---------- Purchase Orders ----------
    def get_open_pos(self, material_id: str,
                      until_date: Optional[date] = None) -> list[PurchaseOrder]:
        q = self.session.query(PurchaseOrder).filter(
            PurchaseOrder.material_id == material_id,
            PurchaseOrder.status == "OPEN",
        )
        if until_date:
            q = q.filter(PurchaseOrder.expected_date <= until_date)
        return q.all()

    # ---------- Movements / consumption history ----------
    def get_consumption_history(self, material_id: str,
                                  days: int = 365,
                                  as_of: Optional[date] = None) -> list[Movement]:
        """Return consumption movements for the last `days` days from `as_of`.

        If as_of is None, uses today's wall-clock date.
        """
        anchor = as_of or date.today()
        cutoff = anchor - timedelta(days=days)
        return (self.session.query(Movement)
                .filter(
                    Movement.material_id == material_id,
                    Movement.movement_type.in_(["261", "201", "281"]),
                    Movement.posting_date >= cutoff,
                    Movement.posting_date <= anchor,
                )
                .order_by(Movement.posting_date)
                .all())

    def get_all_movements(self, material_id: str,
                           start: Optional[date] = None,
                           end: Optional[date] = None) -> list[Movement]:
        q = self.session.query(Movement).filter(Movement.material_id == material_id)
        if start:
            q = q.filter(Movement.posting_date >= start)
        if end:
            q = q.filter(Movement.posting_date <= end)
        return q.order_by(Movement.posting_date).all()

    # ---------- Forecasts ----------
    def get_forecast(self, material_id: str,
                       horizon_days: int = 60) -> list[DemandForecast]:
        cutoff = date.today() + timedelta(days=horizon_days)
        return (self.session.query(DemandForecast)
                .filter(
                    DemandForecast.material_id == material_id,
                    DemandForecast.period >= date.today(),
                    DemandForecast.period <= cutoff,
                )
                .order_by(DemandForecast.period)
                .all())

    # ---------- Proposals (write side) ----------
    def save_proposal(self, proposal: Proposal) -> None:
        self.session.add(proposal)

    def save_proposals(self, proposals: list[Proposal]) -> None:
        self.session.add_all(proposals)

    def clear_proposals(self) -> int:
        n = self.session.query(Proposal).delete()
        self.session.commit()
        return n

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def close(self) -> None:
        self.session.close()

    # ---------- Context manager ----------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        self.close()
