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
    def _stock_total(self, material_id: str, plant: Optional[str],
                     snapshot_date: date) -> float:
        """Stock of a material on one snapshot date: the sum over its
        storage locations (one MARD line each)."""
        from sqlalchemy import func
        q = (self.session.query(func.coalesce(func.sum(Stock.quantity), 0.0))
             .filter(Stock.material_id == material_id,
                     Stock.snapshot_date == snapshot_date))
        if plant:
            q = q.filter(Stock.plant == plant)
        return float(q.scalar() or 0.0)

    def get_current_stock(self, material_id: str,
                          plant: Optional[str] = None,
                          as_of: Optional[date] = None) -> float:
        """
        Stock quantity of a material (sum over its storage locations).

        Without `as_of`: the latest snapshot. With `as_of`: the stock at the
        end of that day (get_stock_at) — the latest snapshot on or before
        it, or, when the data only hold a later snapshot (a single
        extraction after the as-of date), that snapshot rolled back through
        the movements in between. Never negative; 0 without any snapshot.
        """
        if as_of is None:
            from sqlalchemy import func
            q = (self.session.query(func.max(Stock.snapshot_date))
                 .filter(Stock.material_id == material_id))
            if plant:
                q = q.filter(Stock.plant == plant)
            latest = q.scalar()
            return self._stock_total(material_id, plant, latest) if latest else 0.0
        qty, _ = self.get_stock_at(material_id, as_of, plant)
        return max(float(qty), 0.0) if qty is not None else 0.0

    def get_stock_at(self, material_id: str, as_of: date,
                     plant: Optional[str] = None) -> tuple[Optional[float], str]:
        """Reconstruct the stock level at the END of day `as_of`.

        Returns (quantity, source) where source is one of:
          • 'snapshot'  — a snapshot on/before `as_of` exists (latest one used)
          • 'rollback'  — only later snapshots exist: the nearest later
                          snapshot is rolled back by subtracting all signed
                          movements posted in (as_of, snapshot_date]
          • 'none'      — no snapshot at all → (None, 'none')

        A snapshot's quantity is the sum over the material's storage
        locations on that date. Roll-back is exact when the movement history
        is complete (every stock-changing movement type exported); a
        negative result signals an incomplete history and is returned as-is
        for the caller to decide.
        """
        from sqlalchemy import func
        q = self.session.query(Stock.snapshot_date).filter(Stock.material_id == material_id)
        if plant:
            q = q.filter(Stock.plant == plant)

        before = q.filter(Stock.snapshot_date <= as_of).order_by(Stock.snapshot_date.desc()).first()
        if before is not None:
            return self._stock_total(material_id, plant, before[0]), "snapshot"

        after = q.filter(Stock.snapshot_date > as_of).order_by(Stock.snapshot_date.asc()).first()
        if after is None:
            return None, "none"

        moved = (self.session.query(func.coalesce(func.sum(Movement.quantity), 0.0))
                 .filter(
                     Movement.material_id == material_id,
                     Movement.posting_date > as_of,
                     Movement.posting_date <= after[0],
                 ).scalar()) or 0.0
        return self._stock_total(material_id, plant, after[0]) - float(moved), "rollback"

    def get_stock_levels(self, as_of: Optional[date] = None) -> dict[str, float]:
        """get_current_stock(material, as_of=as_of) for every material with a
        snapshot, in three queries instead of a few per material (the agent
        perceives tens of thousands of materials). Never negative."""
        from sqlalchemy import text
        if as_of is None:
            rows = self.session.execute(text("""
                SELECT s.material_id, SUM(s.quantity)
                FROM stock s
                JOIN (SELECT material_id, MAX(snapshot_date) AS d
                      FROM stock GROUP BY material_id) l
                  ON s.material_id = l.material_id AND s.snapshot_date = l.d
                GROUP BY s.material_id""")).all()
            return {m: max(float(q or 0.0), 0.0) for m, q in rows}

        params = {"as_of": as_of.isoformat()}
        before = self.session.execute(text("""
            SELECT s.material_id, SUM(s.quantity)
            FROM stock s
            JOIN (SELECT material_id, MAX(snapshot_date) AS d
                  FROM stock WHERE snapshot_date <= :as_of GROUP BY material_id) l
              ON s.material_id = l.material_id AND s.snapshot_date = l.d
            GROUP BY s.material_id"""), params).all()
        after = self.session.execute(text("""
            SELECT s.material_id, SUM(s.quantity)
            FROM stock s
            JOIN (SELECT material_id, MIN(snapshot_date) AS d
                  FROM stock WHERE snapshot_date > :as_of GROUP BY material_id) a
              ON s.material_id = a.material_id AND s.snapshot_date = a.d
            GROUP BY s.material_id"""), params).all()
        moved = dict(self.session.execute(text("""
            SELECT m.material_id, SUM(m.quantity)
            FROM movements m
            JOIN (SELECT material_id, MIN(snapshot_date) AS d
                  FROM stock WHERE snapshot_date > :as_of GROUP BY material_id) a
              ON m.material_id = a.material_id
            WHERE m.posting_date > :as_of AND m.posting_date <= a.d
            GROUP BY m.material_id"""), params).all())
        levels = {m: float(q or 0.0) - float(moved.get(m) or 0.0) for m, q in after}
        levels.update({m: float(q or 0.0) for m, q in before})
        return {m: max(q, 0.0) for m, q in levels.items()}

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
                      until_date: Optional[date] = None,
                      as_of: Optional[date] = None) -> list[PurchaseOrder]:
        """Open purchase order lines of a material. With `as_of`, lines
        created after that date are left out (they did not exist yet —
        e.g. test orders in a system copy); lines without a PO date stay."""
        from sqlalchemy import or_
        q = self.session.query(PurchaseOrder).filter(
            PurchaseOrder.material_id == material_id,
            PurchaseOrder.status == "OPEN",
        )
        if until_date:
            q = q.filter(PurchaseOrder.expected_date <= until_date)
        if as_of:
            q = q.filter(or_(PurchaseOrder.created_date.is_(None),
                             PurchaseOrder.created_date <= as_of))
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

    def get_dataset_summary(self, inactive_days: int = 180,
                            as_of: Optional[date] = None) -> dict:
        """Counts, date ranges and inactive-stock figures of the loaded dataset.

        `as_of` (the agent's "today", AS_OF_DATE) anchors the open orders and
        the inactive stock; without it the reference date is the latest
        movement or snapshot, as before.
        """
        from sqlalchemy import func, or_
        s = self.session
        n_materials = s.query(func.count(Material.material_id)).scalar() or 0
        n_movements = s.query(func.count(Movement.movement_id)).scalar() or 0
        open_q = s.query(func.count(PurchaseOrder.po_line_id)).filter(PurchaseOrder.status == "OPEN")
        if as_of is not None:
            open_q = open_q.filter(or_(PurchaseOrder.created_date.is_(None),
                                       PurchaseOrder.created_date <= as_of))
        n_open_pos = open_q.scalar() or 0
        n_proposals = s.query(func.count(Proposal.proposal_id)).scalar() or 0
        first_mv, last_mv = s.query(func.min(Movement.posting_date),
                                    func.max(Movement.posting_date)).first()
        last_snapshot = s.query(func.max(Stock.snapshot_date)).scalar()

        # Inactive stock: materials with no consumption in the last
        # `inactive_days` days before the dataset's reference date, and the
        # value of the stock they still tie up (obsolescence risk).
        inactive_materials, inactive_value = 0, 0.0
        anchor = max(d for d in (last_mv, last_snapshot) if d is not None) if (last_mv or last_snapshot) else None
        if as_of is not None:
            anchor = as_of
        if anchor is not None:
            cutoff = anchor - timedelta(days=inactive_days)
            cons_q = (s.query(Movement.material_id, func.max(Movement.posting_date))
                       .filter(Movement.movement_type.in_(list(CONSUMPTION_MOVEMENT_TYPES))))
            if as_of is not None:
                cons_q = cons_q.filter(Movement.posting_date <= as_of)
            last_cons = dict(cons_q.group_by(Movement.material_id).all())
            stock = self.get_stock_levels(as_of)
            for m in self.get_all_materials():
                last = last_cons.get(m.material_id)
                if last is None or last < cutoff:
                    inactive_materials += 1
                    inactive_value += stock.get(m.material_id, 0.0) * float(m.standard_cost or 0)

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
