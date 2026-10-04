from decimal import Decimal
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    MaintenanceRecordCreate,
    MaintenanceRecordResponse,
    MaintenanceRecordUpdate,
    MaintenanceRecordPut,
    MaintenanceRecordStatusUpdate,
)
from app.models.maintenance_record import MaintenanceRecord
from app.models.vehicle import Vehicle
from app.core.dependencies import get_access_user, require_mechanic
from app.core.query_params import get_sort_params, SortOrder
from app.core.rate_limit import limiter
from app.models import User
from app.services.maintenance_price import (
    calculate_maintenance_total,
    calculate_maintenance_totals,
)


class MaintenanceSearchField(str, Enum):
    service_type = "service_type"
    description = "description"


router = APIRouter(
    prefix="/maintenance-records",
    tags=["Maintenance Records"]
)


@router.post("/", response_model=MaintenanceRecordResponse)
@limiter.limit("20/minute")
def create_maintenance_record(
    request: Request,
    maintenance: MaintenanceRecordCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_mechanic),
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

    if not vehicle.verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle must be verified before creating maintenance records"
        )

    if current_user.role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Mechanics can only create maintenance records for customer vehicles"
            )

    last_maintenance = (
        db.query(MaintenanceRecord)
        .filter(
            MaintenanceRecord.vehicle_id == maintenance.vehicle_id,
            MaintenanceRecord.service_date < maintenance.service_date,
        )
        .order_by(desc(MaintenanceRecord.service_date))
        .first()
    )

    if last_maintenance and maintenance.mileage < last_maintenance.mileage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maintenance mileage cannot be lower than the previous maintenance mileage"
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

    total_cost = calculate_maintenance_total(
        db=db,
        maintenance_record_id=new_maintenance.id,
        labor_cost=new_maintenance.labor_cost,
    )

    return {
        "id": new_maintenance.id,
        "vehicle_id": new_maintenance.vehicle_id,
        "service_type": new_maintenance.service_type,
        "description": new_maintenance.description,
        "mileage": new_maintenance.mileage,
        "service_date": new_maintenance.service_date,
        "labor_cost": new_maintenance.labor_cost,
        "total_cost": total_cost,
        "status": new_maintenance.status,
        "notes": new_maintenance.notes,
        "created_at": new_maintenance.created_at,
    }

@router.patch(
    "/{maintenance_record_id}/status",
    response_model=MaintenanceRecordResponse,
)
@limiter.limit("20/minute")
def update_maintenance_status(
    request: Request,
    maintenance_record_id: int,
    status_data: MaintenanceRecordStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_mechanic),
):
    maintenance_record = (
        db.query(MaintenanceRecord)
        .filter(MaintenanceRecord.id == maintenance_record_id)
        .first()
    )

    if maintenance_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance record not found",
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record.vehicle_id)
        .first()
    )

    if current_user.role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Mechanics can only update customer maintenance records",
            )

    if maintenance_record.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only maintenance records in progress can be marked as ready",
        )

    if status_data.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maintenance status can only be changed to ready",
        )

    maintenance_record.status = "ready"

    db.commit()
    db.refresh(maintenance_record)

    total_cost = calculate_maintenance_total(
        db=db,
        maintenance_record_id=maintenance_record.id,
        labor_cost=maintenance_record.labor_cost,
    )

    return {
        "id": maintenance_record.id,
        "vehicle_id": maintenance_record.vehicle_id,
        "service_type": maintenance_record.service_type,
        "description": maintenance_record.description,
        "mileage": maintenance_record.mileage,
        "service_date": maintenance_record.service_date,
        "labor_cost": maintenance_record.labor_cost,
        "total_cost": total_cost,
        "status": maintenance_record.status,
        "notes": maintenance_record.notes,
        "created_at": maintenance_record.created_at,
    }

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
    if access["user"].role == "customer":
        query = query.filter(
            Vehicle.user_id == access["user"].id
        )

    elif access["user"].role == "mechanic":
        query = query.join(User).filter(
            User.role == "customer"
        )

# admin → no filter

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
    maintenance_records = query.offset(offset).limit(limit).all()

    maintenance_record_ids = [
        record.id for record in maintenance_records
    ]

    part_totals = calculate_maintenance_totals(
        db=db,
        maintenance_record_ids=maintenance_record_ids,
    )

    return [
        {
            "id": record.id,
            "vehicle_id": record.vehicle_id,
            "service_type": record.service_type,
            "description": record.description,
            "mileage": record.mileage,
            "service_date": record.service_date,
            "labor_cost": record.labor_cost,
            "total_cost": record.labor_cost + part_totals.get(
                record.id,
                Decimal("0"),
            ),
            "status": record.status,
            "notes": record.notes,
            "created_at": record.created_at,
        }
        for record in maintenance_records
    ]


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

    if access["user"].role == "customer":
        if vehicle.user_id != access["user"].id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this maintenance record"
            )

    elif access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this maintenance record"
            )

# admin → puede acceder a cualquier registro

    total_cost = calculate_maintenance_total(
        db=db,
        maintenance_record_id=maintenance_record.id,
        labor_cost=maintenance_record.labor_cost,
    )

    return {
        "id": maintenance_record.id,
        "vehicle_id": maintenance_record.vehicle_id,
        "service_type": maintenance_record.service_type,
        "description": maintenance_record.description,
        "mileage": maintenance_record.mileage,
        "service_date": maintenance_record.service_date,
        "labor_cost": maintenance_record.labor_cost,
        "total_cost": total_cost,
        "status": maintenance_record.status,
        "notes": maintenance_record.notes,
        "created_at": maintenance_record.created_at,
    }


@router.patch(
    "/{maintenance_record_id}",
    response_model=MaintenanceRecordResponse
)
@limiter.limit("20/minute")
def update_maintenance_record(
    request: Request,
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

    if maintenance_record_db.status == "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ready maintenance records cannot be modified",
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record_db.vehicle_id)
        .first()
    )

    if access["user"].role == "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customers cannot modify maintenance records"
        )

    if access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Mechanics can only modify customer maintenance records"
            )

    update_data = maintenance_data.model_dump(exclude_unset=True)

    effective_service_date = update_data.get(
        "service_date",
        maintenance_record_db.service_date,
    )

    effective_mileage = update_data.get(
        "mileage",
        maintenance_record_db.mileage,
    )

    previous_maintenance = (
        db.query(MaintenanceRecord)
        .filter(
            MaintenanceRecord.vehicle_id == maintenance_record_db.vehicle_id,
            MaintenanceRecord.id != maintenance_record_db.id,
            MaintenanceRecord.service_date < effective_service_date,
        )
        .order_by(desc(MaintenanceRecord.service_date))
        .first()
    )

    if previous_maintenance and effective_mileage < previous_maintenance.mileage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maintenance mileage cannot be lower than the previous maintenance mileage"
        )

    for field, value in update_data.items():
        setattr(maintenance_record_db, field, value)

    db.commit()
    db.refresh(maintenance_record_db)

    total_cost = calculate_maintenance_total(
        db=db,
        maintenance_record_id=maintenance_record_db.id,
        labor_cost=maintenance_record_db.labor_cost,
    )

    return {
        "id": maintenance_record_db.id,
        "vehicle_id": maintenance_record_db.vehicle_id,
        "service_type": maintenance_record_db.service_type,
        "description": maintenance_record_db.description,
        "mileage": maintenance_record_db.mileage,
        "service_date": maintenance_record_db.service_date,
        "labor_cost": maintenance_record_db.labor_cost,
        "total_cost": total_cost,
        "status": maintenance_record_db.status,
        "notes": maintenance_record_db.notes,
        "created_at": maintenance_record_db.created_at,
    }


@router.put("/{record_id}", response_model=MaintenanceRecordResponse)
@limiter.limit("20/minute")
def replace_maintenance_record(
    request: Request,
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

    if record_db.status == "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ready maintenance records cannot be replaced",
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == record_db.vehicle_id)
        .first()
    )

    if access["user"].role == "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customers cannot modify maintenance records"
        )

    if access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Mechanics can only modify customer maintenance records"
            )

    previous_maintenance = (
        db.query(MaintenanceRecord)
        .filter(
            MaintenanceRecord.vehicle_id == record_db.vehicle_id,
            MaintenanceRecord.id != record_db.id,
            MaintenanceRecord.service_date < record_data.service_date,
        )
        .order_by(desc(MaintenanceRecord.service_date))
        .first()
    )

    if previous_maintenance and record_data.mileage < previous_maintenance.mileage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maintenance mileage cannot be lower than the previous maintenance mileage"
        )

    record_db.service_type = record_data.service_type
    record_db.description = record_data.description
    record_db.mileage = record_data.mileage
    record_db.service_date = record_data.service_date
    record_db.labor_cost = record_data.labor_cost
    record_db.notes = record_data.notes

    db.commit()
    db.refresh(record_db)

    total_cost = calculate_maintenance_total(
        db=db,
        maintenance_record_id=record_db.id,
        labor_cost=record_db.labor_cost,
    )

    return {
        "id": record_db.id,
        "vehicle_id": record_db.vehicle_id,
        "service_type": record_db.service_type,
        "description": record_db.description,
        "mileage": record_db.mileage,
        "service_date": record_db.service_date,
        "labor_cost": record_db.labor_cost,
        "total_cost": total_cost,
        "status": record_db.status,
        "notes": record_db.notes,
        "created_at": record_db.created_at,
    }

@router.delete("/{maintenance_record_id}")
@limiter.limit("20/minute")
def delete_maintenance_record(
    request: Request,
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

    if maintenance_record.status == "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ready maintenance records cannot be deleted",
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record.vehicle_id)
        .first()
    )

    if access["user"].role == "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customers cannot delete maintenance records"
        )

    if access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Mechanics can only delete customer maintenance records"
            )

# admin → puede eliminar cualquier registro

    db.delete(maintenance_record)
    db.commit()

    return {"message": "Maintenance record deleted successfully"}
