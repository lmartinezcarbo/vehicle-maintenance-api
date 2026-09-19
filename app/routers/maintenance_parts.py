"""
Maintenance Part Router

This module contains all the API endpoints related to maintenance parts.
It handles CRUD operations for maintenance parts associated with maintenance records.
"""

from fastapi import APIRouter, Depends, HTTPException, status
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

router = APIRouter(
    prefix="/maintenance-part",
    tags=["Maintenance Part"],
)

@router.post("/", response_model=MaintenancePartResponse)
def create_maintenance_part(
    maintenance_part: MaintenancePartCreate,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Create a new maintenance part record.

    This endpoint creates a new maintenance part associated with a maintenance record.
    The user must have access to the maintenance record's vehicle (either as admin or owner).

    Parameters:
        maintenance_part: MaintenancePartCreate - Data for the new maintenance part
        db: Session - Database session
        access: dict - User access information

    Returns:
        MaintenancePartResponse - The created maintenance part

    Raises:
        HTTPException: If maintenance record, part, or vehicle is not found,
                      or if user is not authorized
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
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Retrieve a list of all maintenance parts.

    This endpoint returns all maintenance parts in the system.
    For non-admin users, it only returns maintenance parts associated with their vehicles.

    Parameters:
        db: Session - Database session
        access: dict - User access information

    Returns:
        List[MaintenancePartResponse] - List of maintenance parts
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
    )

    if not access["is_admin"]:
        query = query.filter(
            Vehicle.user_id == access["user"].id
        )

    maintenance_parts = query.all()

    return maintenance_parts

@router.get(
    "/{maintenance_part_id}",
    response_model=MaintenancePartResponse
)
def get_maintenance_part_by_id(
    maintenance_part_id: int,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Retrieve a specific maintenance part by its ID.

    This endpoint returns details of a single maintenance part.
    Access is restricted to admin users or the owner of the vehicle associated with the maintenance part.

    Parameters:
        maintenance_part_id: int - ID of the maintenance part to retrieve
        db: Session - Database session
        access: dict - User access information

    Returns:
        MaintenancePartResponse - The requested maintenance part

    Raises:
        HTTPException: If maintenance part is not found or user is not authorized
    """
    maintenance_part = (
        db.query(MaintenancePart)
        .filter(MaintenancePart.id == maintenance_part_id)
        .first()
    )

    if maintenance_part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance part not found"
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
    access = Depends(get_access_user),
):
    """
    Update an existing maintenance part.

    This endpoint updates a maintenance part's details.
    The user must have access to the maintenance part's vehicle (either as admin or owner).

    Parameters:
        maintenance_part_id: int - ID of the maintenance part to update
        maintenance_part: MaintenancePartUpdate - Updated data for the maintenance part
        db: Session - Database session
        access: dict - User access information

    Returns:
        MaintenancePartResponse - The updated maintenance part

    Raises:
        HTTPException: If maintenance part is not found or user is not authorized
    """
    maintenance_part_db = (
        db.query(MaintenancePart)
        .filter(MaintenancePart.id == maintenance_part_id)
        .first()
    )

    if maintenance_part_db is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance part not found"
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
    access = Depends(get_access_user),
):
    """
    Delete a maintenance part.

    This endpoint deletes a maintenance part record.
    The user must have access to the maintenance part's vehicle (either as admin or owner).

    Parameters:
        maintenance_part_id: int - ID of the maintenance part to delete
        db: Session - Database session
        access: dict - User access information

    Returns:
        dict - Success message

    Raises:
        HTTPException: If maintenance part is not found or user is not authorized
    """
    maintenance_part = (
        db.query(MaintenancePart)
        .filter(MaintenancePart.id == maintenance_part_id)
        .first()
    )

    if maintenance_part is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance part not found"
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