from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.models import User
from app.core.dependencies import get_current_user, require_admin
from app.database import get_db
from app.schemas import PartCreate, PartResponse, PartUpdate
from app.models.part import Part
from app.core.query_params import get_sort_params, SortOrder


class PartSearchField(str, Enum):
    name = "name"
    manufacturer = "manufacturer"
    part_number = "part_number"
    description = "description"


router = APIRouter(
    prefix="/parts",
    tags=["Parts"],
)


@router.post("/", response_model=PartResponse)
def create_part(
    part: PartCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    new_part = Part(
        name=part.name,
        manufacturer=part.manufacturer,
        part_number=part.part_number,
        description=part.description,
    )

    db.add(new_part)
    db.commit()
    db.refresh(new_part)

    return new_part


@router.get("/", response_model=list[PartResponse])
def get_parts(
    manufacturer: str | None = None,
    part_number: str | None = None,
    search: str | None = None,
    search_by: PartSearchField = PartSearchField.name,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_params=Depends(get_sort_params),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Part)

    # ---------------------------------------------------------
    # EXACT FILTERS
    # ---------------------------------------------------------

    if manufacturer is not None:
        query = query.filter(
            Part.manufacturer == manufacturer
        )

    if part_number is not None:
        query = query.filter(
            Part.part_number == part_number
        )

    # ---------------------------------------------------------
    # SEARCH
    # ---------------------------------------------------------

    if search:
        if search_by == PartSearchField.name:
            query = query.filter(
                Part.name.ilike(f"%{search}%")
            )

        elif search_by == PartSearchField.manufacturer:
            query = query.filter(
                Part.manufacturer.ilike(f"%{search}%")
            )

        elif search_by == PartSearchField.part_number:
            query = query.filter(
                Part.part_number.ilike(f"%{search}%")
            )

        else:
            query = query.filter(
                Part.description.ilike(f"%{search}%")
            )

    # ---------------------------------------------------------
    # SORTING
    # ---------------------------------------------------------

    sort_columns = {
        "name": Part.name,
        "manufacturer": Part.manufacturer,
        "part_number": Part.part_number,
    }

    sort_by = sort_params["sort_by"]
    order = sort_params["order"]

    if sort_by:
        sort_column = sort_columns.get(sort_by)

        if sort_column is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid sort field",
            )

        if order == SortOrder.asc:
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

    # ---------------------------------------------------------
    # PAGINATION
    # ---------------------------------------------------------

    return query.offset(offset).limit(limit).all()


@router.get("/{part_id}", response_model=PartResponse)
def get_part(
    part_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    part = (
        db.query(Part)
        .filter(Part.id == part_id)
        .first()
    )

    if part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Part not found",
        )

    return part


@router.patch("/{part_id}", response_model=PartResponse)
def update_part(
    part_id: int,
    part: PartUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    part_db = (
        db.query(Part)
        .filter(Part.id == part_id)
        .first()
    )

    if part_db is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Part not found",
        )

    update_data = part.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(part_db, field, value)

    db.commit()
    db.refresh(part_db)

    return part_db


@router.delete("/{part_id}")
def delete_part(
    part_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    part = (
        db.query(Part)
        .filter(Part.id == part_id)
        .first()
    )

    if part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Part not found",
        )

    db.delete(part)
    db.commit()

    return {"message": "Part deleted successfully"}
