"""
Maintenance Part Router

This module contains all the API endpoints related to maintenance parts.
It handles CRUD operations for maintenance parts associated with maintenance records.
"""

import logging
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.maintenance_part import (
    MaintenancePartCreate,
    MaintenancePartResponse,
    MaintenancePartUpdate,
    MaintenancePartPut,
)
from app.models.maintenance_part import MaintenancePart
from app.models.maintenance_record import MaintenanceRecord
from app.models.part import Part
from app.models.vehicle import Vehicle
from app.core.dependencies import get_access_user, require_mechanic
from app.core.query_params import get_sort_params, SortOrder
from app.core.rate_limit import limiter
from app.models import User

logger = logging.getLogger(__name__)


class MaintenancePartSearchField(str, Enum):
    part_number = "part_number"
    manufacturer = "manufacturer"


router = APIRouter(
    prefix="/maintenance-part",
    tags=["Maintenance Part"],
)


@router.post(
    "/",
    response_model=MaintenancePartResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/minute")
def create_maintenance_part(
    request: Request,
    maintenance_part: MaintenancePartCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_mechanic),
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
        logger.warning(
            "create part denied: record %s does not exist (user %s)",
            maintenance_part.maintenance_record_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create this maintenance part"
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record.vehicle_id)
        .first()
    )

    if vehicle is None:
        logger.warning(
            "create part denied: record %s has no vehicle",
            maintenance_record.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create this maintenance part"
        )

    if current_user.role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "create part denied: record %s has no customer owner "
                "(mechanic %s)",
                maintenance_record.id,
                current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to create this maintenance part"
            )

    # State only after authorization: whoever may not add parts gets the
    # same 403 whether the record is missing, foreign or already frozen.
    if maintenance_record.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only records in progress can be modified",
        )

    if not vehicle.verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle must be verified before adding maintenance parts"
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
        logger.warning(
            "access denied: maintenance part %s does not exist (user %s)",
            maintenance_part_id,
            access["user"].id,
        )
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

    vehicle = None

    if maintenance_record is not None:
        vehicle = (
            db.query(Vehicle)
            .filter(Vehicle.id == maintenance_record.vehicle_id)
            .first()
        )

    if vehicle is None:
        logger.warning(
            "access denied: maintenance part %s has no vehicle",
            maintenance_part_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this maintenance part"
        )

    if access["user"].role == "customer":
        if vehicle.user_id != access["user"].id:
            logger.warning(
                "access denied: vehicle %s belongs to user %s (user %s)",
                vehicle.id,
                vehicle.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this maintenance part"
            )

    elif access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "access denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                vehicle.id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this maintenance part"
            )

# admin → can access any maintenance part

    return maintenance_part


@router.patch(
    "/{maintenance_part_id}",
    response_model=MaintenancePartResponse
)
@limiter.limit("20/minute")
def update_maintenance_part(
    request: Request,
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
        logger.warning(
            "update part denied: maintenance part %s does not exist "
            "(user %s)",
            maintenance_part_id,
            access["user"].id,
        )
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

    if maintenance_record is None:
        logger.warning(
            "update part denied: maintenance part %s has no record",
            maintenance_part_db.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this maintenance part"
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record.vehicle_id)
        .first()
    )

    if vehicle is None:
        logger.warning(
            "update part denied: record %s has no vehicle",
            maintenance_record.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this maintenance part"
        )

    if access["user"].role == "customer":
        logger.warning(
            "update part denied: user %s is a customer (part %s)",
            access["user"].id,
            maintenance_part_db.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this maintenance part"
        )

    if access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "update part denied: record %s has no customer owner "
                "(mechanic %s)",
                maintenance_record.id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this maintenance part"
            )

    # State only after authorization: whoever may not touch this part gets
    # the same 403 whether it exists or is already frozen.
    if maintenance_record.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only records in progress can be modified",
        )

# admin → can modify any maintenance part

    update_data = maintenance_part.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(maintenance_part_db, field, value)

    db.commit()
    db.refresh(maintenance_part_db)

    return maintenance_part_db

@router.put("/{maintenance_part_id}", response_model=MaintenancePartResponse)
@limiter.limit("20/minute")
def replace_maintenance_part(
    request: Request,
    maintenance_part_id: int,
    part_data: MaintenancePartPut,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    maintenance_part_db = (
        db.query(MaintenancePart)
        .filter(MaintenancePart.id == maintenance_part_id)
        .first()
    )

    if maintenance_part_db is None:
        logger.warning(
            "replace part denied: maintenance part %s does not exist "
            "(user %s)",
            maintenance_part_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to replace this maintenance part"
        )

    record = (
        db.query(MaintenanceRecord)
        .filter(
            MaintenanceRecord.id
            == maintenance_part_db.maintenance_record_id
        )
        .first()
    )

    vehicle = None

    if record is not None:
        vehicle = (
            db.query(Vehicle)
            .filter(Vehicle.id == record.vehicle_id)
            .first()
        )

    if vehicle is None:
        logger.warning(
            "replace part denied: maintenance part %s has no vehicle",
            maintenance_part_db.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to replace this maintenance part"
        )

    if access["user"].role == "customer":
        logger.warning(
            "replace part denied: user %s is a customer (part %s)",
            access["user"].id,
            maintenance_part_db.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to replace this maintenance part"
        )

    if access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "replace part denied: record %s has no customer owner "
                "(mechanic %s)",
                record.id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to replace this maintenance part"
            )

    # State only after authorization: whoever may not touch this part gets
    # the same 403 whether it exists or is already frozen.
    if record.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only records in progress can be modified",
        )

# admin → can modify any maintenance part

    maintenance_part_db.quantity = part_data.quantity
    maintenance_part_db.unit_cost = part_data.unit_cost

    db.commit()
    db.refresh(maintenance_part_db)

    return maintenance_part_db

@router.delete("/{maintenance_part_id}")
@limiter.limit("20/minute")
def delete_maintenance_part(
    request: Request,
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
        logger.warning(
            "delete part denied: maintenance part %s does not exist "
            "(user %s)",
            maintenance_part_id,
            access["user"].id,
        )
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

    if maintenance_record is None:
        logger.warning(
            "delete part denied: maintenance part %s has no record",
            maintenance_part.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this maintenance part"
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record.vehicle_id)
        .first()
    )

    if vehicle is None:
        logger.warning(
            "delete part denied: record %s has no vehicle",
            maintenance_record.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this maintenance part"
        )

    if access["user"].role == "customer":
        logger.warning(
            "delete part denied: user %s is a customer (part %s)",
            access["user"].id,
            maintenance_part.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this maintenance part"
        )

    if access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "delete part denied: record %s has no customer owner "
                "(mechanic %s)",
                maintenance_record.id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this maintenance part"
            )

    # State only after authorization: whoever may not touch this part gets
    # the same 403 whether it exists or is already frozen.
    if maintenance_record.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only records in progress can be modified",
        )

# admin → can delete any maintenance part

    db.delete(maintenance_part)
    db.commit()

    logger.info(
        "maintenance part %s deleted (user %s)",
        maintenance_part_id,
        access["user"].id,
    )

    return {"message": "Maintenance part deleted successfully"}