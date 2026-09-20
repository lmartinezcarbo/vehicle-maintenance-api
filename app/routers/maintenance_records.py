from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    MaintenanceRecordCreate,
    MaintenanceRecordResponse,
    MaintenanceRecordUpdate,
    MaintenanceRecordPut,
)
from app.models.maintenance_record import MaintenanceRecord
from app.models.vehicle import Vehicle
from app.core.dependencies import get_access_user
from app.core.query_params import get_sort_params, SortOrder


class MaintenanceSearchField(str, Enum):
    service_type = "service_type"
    description = "description"


router = APIRouter(
    prefix="/maintenance-records",
    tags=["Maintenance Records"]
)


@router.post("/", response_model=MaintenanceRecordResponse)
def create_maintenance_record(
    maintenance: MaintenanceRecordCreate,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
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
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this vehicle"
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
    vehicle_id: int | None = None,
    service_type: str | None = None,
    search: str | None = None,
    search_by: MaintenanceSearchField = MaintenanceSearchField.service_type,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_params=Depends(get_sort_params),
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Get maintenance records.
    - Admins see all records
    - Regular users see only records for their vehicles
    - Supports filtering, searching, pagination and sorting
    """

    query = (
        db.query(MaintenanceRecord)
        .join(
            Vehicle,
            MaintenanceRecord.vehicle_id == Vehicle.id
        )
    )

    # Ownership / access filter
    if not access["is_admin"]:
        query = query.filter(
            Vehicle.user_id == access["user"].id
        )

    # Exact filters
    if vehicle_id is not None:
        query = query.filter(
            MaintenanceRecord.vehicle_id == vehicle_id
        )

    if service_type is not None:
        query = query.filter(
            MaintenanceRecord.service_type == service_type
        )

    # Search
    if search:
        if search_by == MaintenanceSearchField.service_type:
            query = query.filter(
                MaintenanceRecord.service_type.ilike(f"%{search}%")
            )
        else:
            query = query.filter(
                MaintenanceRecord.description.ilike(f"%{search}%")
            )

    # Sorting
    sort_columns = {
        "service_date": MaintenanceRecord.service_date,
        "mileage": MaintenanceRecord.mileage,
        "labor_cost": MaintenanceRecord.labor_cost,
        "service_type": MaintenanceRecord.service_type,
        "created_at": MaintenanceRecord.created_at,
    }

    sort_by = sort_params["sort_by"]
    order = sort_params["order"]

    if sort_by:
        sort_column = sort_columns.get(sort_by)

        if sort_column is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid sort field"
            )

        if order == SortOrder.asc:
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

    # Pagination
    return query.offset(offset).limit(limit).all()


@router.get(
    "/{maintenance_record_id}",
    response_model=MaintenanceRecordResponse
)
def get_maintenance_record(
    maintenance_record_id: int,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
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
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this maintenance record"
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
    access=Depends(get_access_user),
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
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this maintenance record"
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

@router.put("/{record_id}", response_model=MaintenanceRecordResponse)
def replace_maintenance_record(
    record_id: int,
    record_data: MaintenanceRecordPut,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    record_db = (
        db.query(MaintenanceRecord)
        .filter(MaintenanceRecord.id == record_id)
        .first()
    )

    if record_db is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to replace this maintenance record"
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == record_db.vehicle_id)
        .first()
    )

    if not access["is_admin"] and vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to replace this maintenance record"
        )

    record_db.service_type = record_data.service_type
    record_db.description = record_data.description
    record_db.mileage = record_data.mileage
    record_db.service_date = record_data.service_date
    record_db.labor_cost = record_data.labor_cost
    record_db.notes = record_data.notes

    db.commit()
    db.refresh(record_db)

    return record_db

@router.delete("/{maintenance_record_id}")
def delete_maintenance_record(
    maintenance_record_id: int,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
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
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this maintenance record"
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