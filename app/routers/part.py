from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import PartCreate, PartResponse, PartUpdate
from app.models.part import Part


router = APIRouter(
    prefix="/parts",
    tags=["Parts"],
)

@router.post("/", response_model= PartResponse)
def create_part(
    part: PartCreate,
    db: Session = Depends(get_db)
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
    db: Session = Depends(get_db)
):
    parts = db.query(Part).all()

    return parts

@router.get("/{part_id}", response_model=PartResponse)
def get_part(
    part_id: int,
    db: Session = Depends(get_db)
):
    part= db.query(Part).filter(Part.id == part_id).first()

    if part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Part not found"
        )

    return part

@router.patch("/{part_id}", response_model=PartResponse)
def update_part(
    part_id: int,
    part: PartUpdate,
    db: Session = Depends(get_db),
):
    part_db = db.query(Part).filter(Part.id == part_id).first()

    if part_db is None:
       raise HTTPException(
           status_code=status.HTTP_404_NOT_FOUND,
           detail="Part not found"
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
):
    part = db.query(Part).filter(Part.id == part_id).first()

    if part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Part not found"
        )

    db.delete(part)

    db.commit()

    return {"message": "Part delete sucesfully"}