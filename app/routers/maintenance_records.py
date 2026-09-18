from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import MaintenanceRecordCreate, MaintenanceRecordResponse, MaintenanceRecordUpdate
from app.models.maintenance_record import MaintenanceRecord
from app.models.vehicle import Vehicle

router = APIRouter(
    prefix="/maintenance-records", 
    tags=["Maintenance Records"]
)

@router.post("/", response_model=MaintenanceRecordResponse)
def create_maintenance_record(
    maintenance: MaintenanceRecordCreate,
    db: Session = Depends(get_db)
):
    vehicle = db.query(Vehicle).filter(Vehicle.id == maintenance.vehicle_id).first()

    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found"
        )

    new_maintenance = MaintenanceRecord(
        vehicle_id=maintenance.vehicle_id,
        service_type=maintenance.service_type,
        description=maintenance.description,
        mileage=maintenance.mileage,
        service_date=maintenance.service_date,
        labor_cost=maintenance.labor_cost,
        notes=maintenance.notes,
    )

    db.add(new_maintenance)
    db.commit()

    db.refresh(new_maintenance)

    return new_maintenance

@router.get("/", response_model=list[MaintenanceRecordResponse])
def get_maintenance_records(
    db: Session = Depends(get_db),
):
    maintenance_records = db.query(MaintenanceRecord).all()

    return maintenance_records

@router.get("/{maintenance_record_id}", response_model=MaintenanceRecordResponse)
def get_maintenance_record(
    maintenance_record_id: int,
    db: Session = Depends(get_db),
):
    maintenance_record = db.query(MaintenanceRecord).filter(MaintenanceRecord.id == maintenance_record_id).first()

    if maintenance_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="maintenance record not found"
        )

    return maintenance_record

@router.patch("/{maintenance_record_id}", response_model=MaintenanceRecordResponse)
def update_maintenance_record(
    maintenance_record_id: int,
    maintenance_record: MaintenanceRecordUpdate,
    db: Session = Depends(get_db),
):
    maintenance_record_db = db.query(MaintenanceRecord).filter(MaintenanceRecord.id == maintenance_record_id).first()

    if maintenance_record_db is None:
       raise HTTPException(
           status_code=status.HTTP_404_NOT_FOUND,
           detail="maintenance record not found"
       ) 

    update_data = maintenance_record.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(maintenance_record_db, field, value)

    db.commit()
    db.refresh(maintenance_record_db)

    return maintenance_record_db

@router.delete("/{maintenance_record_id}")
def delete_maintenance_record(
    maintenance_record_id: int,
    db: Session = Depends(get_db),
):
    maintenance_record = db.query(MaintenanceRecord).filter(MaintenanceRecord.id == maintenance_record_id).first()

    if maintenance_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="maintenance record not found"
        )

    db.delete(maintenance_record)

    db.commit()

    return {"message": "Maintenance Record delete sucesfully"}