"""Dataset-level views: train/val/test split distribution and rebalancing."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app import export as export_logic
from app import repo
from app.deps import get_conn
from app.models import RebalanceRequest

router = APIRouter(prefix="/api")


@router.get("/splits")
def get_splits(conn=Depends(get_conn)):
    """Train/val/test/unassigned counts over the Database set."""
    return repo.split_counts(conn, "database")


@router.post("/splits/rebalance")
def rebalance_splits(body: RebalanceRequest, conn=Depends(get_conn)):
    """Re-partition all Database images to the target ratios and persist splits."""
    ids = repo.database_image_ids(conn)
    by_split = export_logic.partition_three_way(ids, body.train, body.val, body.test, body.seed)
    repo.set_splits(conn, by_split)
    return repo.split_counts(conn, "database")
