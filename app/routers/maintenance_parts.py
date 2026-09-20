"""
Maintenance Part Router

This module contains all the API endpoints related to maintenance parts.
It handles CRUD operations for maintenance parts associated with maintenance records.
"""

from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    MaintenancePartCreate,
    MaintenancePartResponse,
    MaintenancePartUpdate,
)
from app.models.maintenance_part import MaintenancePart
from app.models.maintenance_record import MaintenanceRecord
from app.models.part import Part
from app.models.vehicle import Vehicle
from app.core.dependencies import get_access_user
from app.core.query_params import get_sort_params, SortOrder


class MaintenancePartSearchField(str, Enum):
    part_number = "part_number"
    manufacturer = "manufacturer"


router = APIRouter(
    prefix="/maintenance-part",
    tags=["Maintenance Part"],
)


@router.post("/", response_model=MaintenancePartResponse)
def create_maintenance_part(
    maintenance_part: MaintenancePartCreate,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Create a new maintenance part record.
    """
    maintenance_record = (
        db.query(MaintenanceRecord)
        .filter(
            MaintenanceRecord.id == maintenance_part.maintenance_record_id
        )
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

    part = (
        db.query(Part)
        .filter(Part.id == maintenance_part.part_id)
        .first()
    )

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
def get_maintenance_parts(
    maintenance_record_id: int | None = None,
    part_id: int | None = None,
    search: str | None = None,
    search_by: MaintenancePartSearchField = (
        MaintenancePartSearchField.part_number
    ),
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_params=Depends(get_sort_params),
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Retrieve maintenance parts.
    - Admins see all maintenance parts
    - Regular users see only maintenance parts for their vehicles
    - Supports filtering, searching, pagination and sorting
    """

    query = (
        db.query(MaintenancePart)
        .join(
            MaintenanceRecord,
            MaintenancePart.maintenance_record_id == MaintenanceRecord.id
        )
        .join(
            Vehicle,
            MaintenanceRecord.vehicle_id == Vehicle.id
        )
        .join(
            Part,
            MaintenancePart.part_id == Part.id
        )
    )

    # Ownership / access filter
    if not access["is_admin"]:
        query = query.filter(
            Vehicle.user_id == access["user"].id
        )

    # Exact filters
    if maintenance_record_id is not None:
        query = query.filter(
            MaintenancePart.maintenance_record_id == maintenance_record_id
        )

    if part_id is not None:
        query = query.filter(
            MaintenancePart.part_id == part_id
        )

    # Search
    if search:
        if search_by == MaintenancePartSearchField.part_number:
            query = query.filter(
                Part.part_number.ilike(f"%{search}%")
            )
        else:
            query = query.filter(
                Part.manufacturer.ilike(f"%{search}%")
            )

    # Sorting
    sort_columns = {
        "quantity": MaintenancePart.quantity,
        "unit_cost": MaintenancePart.unit_cost,
        "maintenance_record_id": MaintenancePart.maintenance_record_id,
        "part_id": MaintenancePart.part_id,
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
    "/{maintenance_part_id}",
    response_model=MaintenancePartResponse
)
def get_maintenance_part_by_id(
    maintenance_part_id: int,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Retrieve a specific maintenance part by its ID.
    """
    maintenance_part = (
        db.query(MaintenancePart)
        .filter(MaintenancePart.id == maintenance_part_id)
        .first()
    )

    if maintenance_part is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this maintenance part"
        )

    maintenance_record = (
        db.query(MaintenanceRecord)
        .filter(
            MaintenanceRecord.id == maintenance_part.maintenance_record_id
        )
        .first()
    )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record.vehicle_id)
        .first()
    )

    if not access["is_admin"] and vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this maintenance part"
        )

    return maintenance_part


@router.patch(
    "/{maintenance_part_id}",
    response_model=MaintenancePartResponse
)
def update_maintenance_part(
    maintenance_part_id: int,
    maintenance_part: MaintenancePartUpdate,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Update an existing maintenance part.
    """
    maintenance_part_db = (
        db.query(MaintenancePart)
        .filter(MaintenancePart.id == maintenance_part_id)
        .first()
    )

    if maintenance_part_db is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this maintenance part"
        )

    maintenance_record = (
        db.query(MaintenanceRecord)
        .filter(
            MaintenanceRecord.id == maintenance_part_db.maintenance_record_id
        )
        .first()
    )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record.vehicle_id)
        .first()
    )

    if not access["is_admin"] and vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this maintenance part"
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
    access=Depends(get_access_user),
):
    """
    Delete a maintenance part.
    """
    maintenance_part = (
        db.query(MaintenancePart)
        .filter(MaintenancePart.id == maintenance_part_id)
        .first()
    )

    if maintenance_part is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this maintenance part"
        )

    maintenance_record = (
        db.query(MaintenanceRecord)
        .filter(
            MaintenanceRecord.id == maintenance_part.maintenance_record_id
        )
        .first()
    )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record.vehicle_id)
        .first()
    )

    if not access["is_admin"] and vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this maintenance part"
        )

    db.delete(maintenance_part)
    db.commit()

    return {"message": "Maintenance part deleted successfully"}