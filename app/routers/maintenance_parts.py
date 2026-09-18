from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db

from app.schemas import MaintenancePartCreate, MaintenancePartResponse, MaintenancePartUpdate
from app.models.maintenance_part import MaintenancePart
from app.models.maintenance_record import MaintenanceRecord
from app.models.part import Part


router = APIRouter(
    prefix="/maintenance-part",
    tags=["Maintenance Part"],
)


@router.post("/", response_model=MaintenancePartResponse)
def create_maintenance_part(
    maintenance_part: MaintenancePartCreate,
    db: Session = Depends(get_db),
):
    maintenance_record = (
        db.query(MaintenanceRecord)
        .filter(MaintenanceRecord.id == maintenance_part.maintenance_record_id)
        .first()
    )

    if maintenance_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance record not found"
        )
    
    part = db.query(Part).filter(Part.id == maintenance_part.part_id).first()

    if part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Part not found"
        )

    new_maintenance_part = MaintenancePart(
        maintenance_record_id=maintenance_part.maintenance_record_id,
        part_id=maintenance_part.part_id,
        quantity=maintenance_part.quantity,
        unit_cost=maintenance_part.unit_cost,
    )

    db.add(new_maintenance_part)
    db.commit()
    db.refresh(new_maintenance_part)

    return new_maintenance_part

@router.get("/", response_model=list[MaintenancePartResponse])
def get_maintenace_part(
    db: Session = Depends(get_db)
):
    maintenace_part = db.query(MaintenancePart).all()

    return maintenace_part

@router.get("/{maintenance_part_id}", response_model=MaintenancePartResponse)
def get_maintenance_part(
    maintenance_part_id: int,
    db: Session = Depends(get_db)
):
    maintenance_part = db.query(MaintenancePart).filter(MaintenancePart.id == maintenance_part_id).first()

    if maintenance_part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance part not found"
        )

    return maintenance_part

@router.patch("/{maintenance_part_id}", response_model=MaintenancePartResponse)
def update_maintenance_part(
    maintenance_part_id: int,
    maintenance_part: MaintenancePartUpdate,
    db: Session = Depends(get_db)
):
    maintenance_part_db = db.query(MaintenancePart).filter(MaintenancePart.id == maintenance_part_id).first()

    if maintenance_part_db is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance part not found"
        )

    update_data = maintenance_part.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(maintenance_part_db, field, value)

    db.commit()
    db.refresh(maintenance_part_db)

    return maintenance_part_db

@router.delete("/{maintenance_part_id}")
def delete_maintenance_part(
    maintenance_part_id: int,
    db: Session = Depends(get_db),
):
    maintenance_part = db.query(MaintenancePart).filter(MaintenancePart.id == maintenance_part_id).first()

    if maintenance_part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance part not found"
        )

    db.delete(maintenance_part)
    db.commit()

    return {"message": "Maintenance Part deleted successfully"}
    