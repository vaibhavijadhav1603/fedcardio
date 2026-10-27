"""A hospital admin's own training dataset. Nobody else, platform admin included, can upload or read it."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, datasets
from ..db import get_db
from ..models import Hospital, HospitalDataset, User
from ..security import Perm, require

router = APIRouter(prefix="/datasets", tags=["datasets"])


class UploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    csv: str = Field(min_length=1, max_length=datasets.MAX_BYTES)


def _admin(user: User = Depends(require(Perm.dataset_manage))) -> User:
    if user.hospital_id is None:
        raise HTTPException(400, "this account is not attached to a hospital")
    return user


def _mine(user: User, db: Session) -> HospitalDataset | None:
    return db.query(HospitalDataset).filter_by(hospital_id=user.hospital_id).first()


@router.get("/template.csv", response_class=PlainTextResponse)
def template(_: User = Depends(require(Perm.dataset_manage))):
    return PlainTextResponse(datasets.TEMPLATE, media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="fedcardio-template.csv"'})


@router.get("/mine")
def mine(user: User = Depends(_admin), db: Session = Depends(get_db)):
    df, n_csv, n_patients = datasets.hospital_frame(db, db.get(Hospital, user.hospital_id))
    return {"dataset": datasets.summary(_mine(user, db)), "columns": datasets.FEATURES + ["target"],
            "min_rows": datasets.MIN_ROWS, "min_per_class": datasets.MIN_PER_CLASS,
            "rows_from_csv": n_csv, "rows_from_patients": n_patients, "n_training": len(df),
            "n_positive": int(df.y.sum()) if len(df) else 0, "usable": datasets.usable(df)}


@router.post("/mine", status_code=201)
def upload(body: UploadIn, user: User = Depends(_admin), db: Session = Depends(get_db)):
    try:
        df = datasets.parse_csv(body.csv)
    except datasets.DatasetError as e:
        audit.log(db, "dataset.upload", user=user, outcome="failure", detail={"error": str(e)[:300]})
        raise HTTPException(422, str(e)) from e
    ds = datasets.store(db, db.get(Hospital, user.hospital_id), df, body.filename, user)
    db.commit()
    audit.log(db, "dataset.upload", user=user, resource=f"hospital:{user.hospital_id}",
              detail={"rows": ds.n_rows, "positive": ds.n_positive, "sha256": ds.sha256})
    return {"dataset": datasets.summary(ds)}


@router.delete("/mine")
def remove(user: User = Depends(_admin), db: Session = Depends(get_db)):
    ds = _mine(user, db)
    if ds is None:
        raise HTTPException(404, "no dataset uploaded")
    db.delete(ds)
    db.commit()
    datasets.refresh_node(db, db.get(Hospital, user.hospital_id))
    audit.log(db, "dataset.delete", user=user, resource=f"hospital:{user.hospital_id}")
    return {"dataset": None}
