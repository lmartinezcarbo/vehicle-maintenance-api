from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    MaintenanceRecordCreate,
    MaintenanceRecordResponse,
    MaintenanceRecordUpdate,
)
from app.models.maintenance_record import MaintenanceRecord
from app.models.vehicle import Vehicle
from app.core.dependencies import get_access_user

router = APIRouter(
    prefix="/maintenance-records",
    tags=["Maintenance Records"]
)

@router.post("/", response_model=MaintenanceRecordResponse)
def create_maintenance_record(
    maintenance: MaintenanceRecordCreate,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Create a new maintenance record for a vehicle.
    - Verifies that the vehicle exists
    - Verifies that the user has access to the vehicle
    - Creates the maintenance record
    """
    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance.vehicle_id)
        .first()
    )

    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found"
        )

    if not access["is_admin"] and vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this vehicle"
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
    access = Depends(get_access_user),
):
    """
    Get all maintenance records.
    - Admins see all records
    - Regular users see only records for their vehicles
    """
    query = (
        db.query(MaintenanceRecord)
        .join(Vehicle, MaintenanceRecord.vehicle_id == Vehicle.id)
    )

    if not access["is_admin"]:
        query = query.filter(
            Vehicle.user_id == access["user"].id
        )

    maintenance_records = query.all()

    return maintenance_records

@router.get(
    "/{maintenance_record_id}",
    response_model=MaintenanceRecordResponse
)
def get_maintenance_record(
    maintenance_record_id: int,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Get a specific maintenance record by ID.
    - Verifies that the record exists
    - Verifies that the user has access to the associated vehicle
    - Returns the maintenance record
    """
    maintenance_record = (
        db.query(MaintenanceRecord)
        .filter(MaintenanceRecord.id == maintenance_record_id)
        .first()
    )

    if maintenance_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance record not found"
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record.vehicle_id)
        .first()
    )

    if not access["is_admin"] and vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this maintenance record"
        )

    return maintenance_record

@router.patch(
    "/{maintenance_record_id}",
    response_model=MaintenanceRecordResponse
)
def update_maintenance_record(
    maintenance_record_id: int,
    maintenance_data: MaintenanceRecordUpdate,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Update a maintenance record.
    - Verifies that the record exists
    - Verifies that the user has access to the associated vehicle
    - Updates the maintenance record fields
    """
    maintenance_record_db = (
        db.query(MaintenanceRecord)
        .filter(MaintenanceRecord.id == maintenance_record_id)
        .first()
    )

    if maintenance_record_db is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance record not found"
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record_db.vehicle_id)
        .first()
    )

    if not access["is_admin"] and vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this maintenance record"
        )

    update_data = maintenance_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(maintenance_record_db, field, value)

    db.commit()
    db.refresh(maintenance_record_db)

    return maintenance_record_db

@router.delete("/{maintenance_record_id}")
def delete_maintenance_record(
    maintenance_record_id: int,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Delete a maintenance record.
    - Verifies that the record exists
    - Verifies that the user has access to the associated vehicle
    - Deletes the maintenance record
    """
    maintenance_record = (
        db.query(MaintenanceRecord)
        .filter(MaintenanceRecord.id == maintenance_record_id)
        .first()
    )

    if maintenance_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance record not found"
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record.vehicle_id)
        .first()
    )

    if not access["is_admin"] and vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this maintenance record"
        )

    db.delete(maintenance_record)
    db.commit()

    return {"message": "Maintenance record deleted successfully"}