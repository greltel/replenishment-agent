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
    Base, Material, Stock, PurchaseOrder, Movement, DemandForecast, Proposal,
    CONSUMPTION_MOVEMENT_TYPES,
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

    def get_stock_at(self, material_id: str, as_of: date,
                     plant: Optional[str] = None) -> tuple[Optional[float], str]:
        """Reconstruct the stock level at the END of day `as_of`.

        Returns (quantity, source) where source is one of:
          • 'snapshot'  — a snapshot on/before `as_of` exists (latest one used)
          • 'rollback'  — only later snapshots exist: the nearest later
                          snapshot is rolled back by subtracting all signed
                          movements posted in (as_of, snapshot_date]
          • 'none'      — no snapshot at all → (None, 'none')

        Roll-back is exact when the movement history is complete (every
        stock-changing movement type exported); a negative result signals
        an incomplete history and is returned as-is for the caller to decide.
        """
        q = self.session.query(Stock).filter(Stock.material_id == material_id)
        if plant:
            q = q.filter(Stock.plant == plant)

        before = (q.filter(Stock.snapshot_date <= as_of)
                   .order_by(Stock.snapshot_date.desc()).first())
        if before is not None:
            return float(before.quantity), "snapshot"

        after = (q.filter(Stock.snapshot_date > as_of)
                  .order_by(Stock.snapshot_date.asc()).first())
        if after is None:
            return None, "none"

        from sqlalchemy import func
        moved = (self.session.query(func.coalesce(func.sum(Movement.quantity), 0.0))
                 .filter(
                     Movement.material_id == material_id,
                     Movement.posting_date > as_of,
                     Movement.posting_date <= after.snapshot_date,
                 ).scalar()) or 0.0
        return float(after.quantity) - float(moved), "rollback"

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
                    Movement.movement_type.in_(list(CONSUMPTION_MOVEMENT_TYPES)),
                    Movement.posting_date >= cutoff,
                    Movement.posting_date <= anchor,
                )
                .order_by(Movement.posting_date)
                .all())

    def get_dataset_summary(self, inactive_days: int = 180) -> dict:
        """Counts, date ranges and inactive-stock figures of the loaded dataset."""
        from sqlalchemy import func
        s = self.session
        n_materials = s.query(func.count(Material.material_id)).scalar() or 0
        n_movements = s.query(func.count(Movement.movement_id)).scalar() or 0
        n_open_pos = (s.query(func.count(PurchaseOrder.po_line_id))
                       .filter(PurchaseOrder.status == "OPEN").scalar() or 0)
        n_proposals = s.query(func.count(Proposal.proposal_id)).scalar() or 0
        first_mv, last_mv = s.query(func.min(Movement.posting_date),
                                    func.max(Movement.posting_date)).first()
        last_snapshot = s.query(func.max(Stock.snapshot_date)).scalar()

        # Inactive stock: materials with no consumption in the last
        # `inactive_days` days before the dataset's reference date, and the
        # value of the stock they still tie up (obsolescence risk).
        inactive_materials, inactive_value = 0, 0.0
        anchor = max(d for d in (last_mv, last_snapshot) if d is not None) if (last_mv or last_snapshot) else None
        if anchor is not None:
            cutoff = anchor - timedelta(days=inactive_days)
            last_cons = dict(
                s.query(Movement.material_id, func.max(Movement.posting_date))
                 .filter(Movement.movement_type.in_(list(CONSUMPTION_MOVEMENT_TYPES)))
                 .group_by(Movement.material_id).all()
            )
            for m in self.get_all_materials():
                last = last_cons.get(m.material_id)
                if last is None or last < cutoff:
                    inactive_materials += 1
                    inactive_value += self.get_current_stock(m.material_id) * float(m.standard_cost or 0)

        return {
            "n_materials":   int(n_materials),
            "n_movements":   int(n_movements),
            "n_open_pos":    int(n_open_pos),
            "n_proposals":   int(n_proposals),
            "first_movement": first_mv,
            "last_movement":  last_mv,
            "last_snapshot":  last_snapshot,
            "inactive_materials": inactive_materials,
            "inactive_stock_value": round(inactive_value, 2),
            "inactive_days": inactive_days,
        }

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
