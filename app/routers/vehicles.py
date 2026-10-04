import logging
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import VehicleCreate, VehicleResponse, VehicleUpdate, VehiclePut
from app.models import User
from app.models.vehicle import Vehicle
from app.core.dependencies import get_access_user, require_mechanic
from app.core.query_filters import filter_by_user_access
from app.core.query_params import get_sort_params, SortOrder
from app.core.rate_limit import limiter

logger = logging.getLogger(__name__)


class VehicleSearchField(str, Enum):
    make = "make"
    model = "model"
    vin = "vin"


router = APIRouter(
    prefix="/vehicles",
    tags=["Vehicles"],
)


@router.post(
    "/",
    response_model=VehicleResponse,
    status_code=status.HTTP_201_CREATED
)
@limiter.limit("20/minute")
def create_vehicle(
    request: Request,
    vehicle: VehicleCreate,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Create a new vehicle.
    - Regular users can only create vehicles for themselves
    - Admins can create vehicles for any user
    """
    if access["user"].role == "customer":
        user_id = access["user"].id
        verified = False

    elif access["user"].role in ("mechanic", "admin"):
        if vehicle.user_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_id is required"
            )

        user_id = vehicle.user_id

        user = db.query(User).filter(User.id == user_id).first()

        if access["user"].role == "mechanic":
            if user is None or user.role != "customer":
                logger.warning(
                    "create vehicle denied: user %s does not exist or is "
                    "not a customer (mechanic %s)",
                    user_id,
                    access["user"].id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to create this vehicle",
                )
        elif user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        verified = True

    new_vehicle = Vehicle(
        user_id=user_id,
        make=vehicle.make,
        model=vehicle.model,
        year=vehicle.year,
        vin=vehicle.vin,
        mileage=vehicle.mileage,
        verified=verified,
    )

    db.add(new_vehicle)
    db.commit()
    db.refresh(new_vehicle)

    return new_vehicle


@router.get("/", response_model=list[VehicleResponse])
def get_vehicles(
    make: str | None = None,
    model: str | None = None,
    year: int | None = None,
    search: str | None = None,
    search_by: VehicleSearchField = VehicleSearchField.make,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_params=Depends(get_sort_params),
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Get vehicles.
    - Regular users see only their vehicles
    - Admins see all vehicles
    - Supports filtering, searching, pagination and sorting
    """

    query = db.query(Vehicle)

    if access["user"].role == "customer":
        query = query.filter(
            Vehicle.user_id == access["user"].id
        )

    elif access["user"].role == "mechanic":
        query = query.join(User).filter(
            User.role == "customer"
        )

# admin → no filtro, puede ver todos

    # Exact filters
    if make is not None:
        query = query.filter(Vehicle.make == make)

    if model is not None:
        query = query.filter(Vehicle.model == model)

    if year is not None:
        query = query.filter(Vehicle.year == year)

    # Search
    if search:
        if search_by == VehicleSearchField.make:
            query = query.filter(
                Vehicle.make.ilike(f"%{search}%")
            )

        elif search_by == VehicleSearchField.model:
            query = query.filter(
                Vehicle.model.ilike(f"%{search}%")
            )

        else:
            query = query.filter(
                Vehicle.vin.ilike(f"%{search}%")
            )

    # Sorting
    sort_columns = {
        "make": Vehicle.make,
        "model": Vehicle.model,
        "year": Vehicle.year,
        "mileage": Vehicle.mileage,
        "vin": Vehicle.vin,
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


@router.get("/{vehicle_id}", response_model=VehicleResponse)
def get_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    access=Depends(get_access_user)
):
    """
    Get a specific vehicle by ID.
    - Regular users can only access their vehicles
    - Admins can access any vehicle
    """
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle is None:
        logger.warning(
            "access denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this vehicle"
        )

    if access["user"].role == "customer":
        if vehicle.user_id != access["user"].id:
            logger.warning(
                "access denied: vehicle %s belongs to user %s (user %s)",
                vehicle_id,
                vehicle.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this vehicle"
            )

    elif access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "access denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this vehicle"
            )

# admin → puede acceder a cualquier vehículo

    return vehicle

@router.patch("/{vehicle_id}/verify", response_model=VehicleResponse)
@limiter.limit("20/minute")
def verify_vehicle(
    request: Request,
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_mechanic),
):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle is None:
        logger.warning(
            "verify denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to verify this vehicle"
        )

    if current_user.role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "verify denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                vehicle_id,
                current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to verify this vehicle"
            )

    # State only after authorization: whoever may not verify gets 403 with
    # the same body whether the vehicle is missing or already verified.
    if vehicle.verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle is already verified"
        )

    vehicle.verified = True

    db.commit()
    db.refresh(vehicle)

    return vehicle

@router.patch("/{vehicle_id}", response_model=VehicleResponse)
@limiter.limit("20/minute")
def update_vehicle(
    request: Request,
    vehicle_id: int,
    vehicle: VehicleUpdate,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Update a vehicle.
    - Regular users can only update their vehicles
    - Admins can update any vehicle
    """
    vehicle_db = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle_db is None:
        logger.warning(
            "update denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this vehicle"
        )

    if access["user"].role == "customer":
        if vehicle_db.user_id != access["user"].id:
            logger.warning(
                "update denied: vehicle %s belongs to user %s "
                "(user %s)",
                vehicle_id,
                vehicle_db.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this vehicle"
            )

        # The owner already knows their own vehicle, so this state hint
        # reveals nothing to anyone else.
        if vehicle_db.verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only modify unverified vehicles"
            )

    if access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle_db.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "update denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this vehicle"
            )

    update_data = vehicle.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(vehicle_db, field, value)

    db.commit()
    db.refresh(vehicle_db)

    return vehicle_db


@router.put("/{vehicle_id}", response_model=VehicleResponse)
@limiter.limit("20/minute")
def replace_vehicle(
    request: Request,
    vehicle_id: int,
    vehicle_data: VehiclePut,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    vehicle_db = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle_db is None:
        logger.warning(
            "replace denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to replace this vehicle"
        )

    if access["user"].role == "customer":
        if vehicle_db.user_id != access["user"].id:
            logger.warning(
                "replace denied: vehicle %s belongs to user %s "
                "(user %s)",
                vehicle_id,
                vehicle_db.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to replace this vehicle"
            )

        # The owner already knows their own vehicle, so this state hint
        # reveals nothing to anyone else.
        if vehicle_db.verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only modify unverified vehicles"
            )

    if access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle_db.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "replace denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to replace this vehicle"
            )

    vehicle_db.make = vehicle_data.make
    vehicle_db.model = vehicle_data.model
    vehicle_db.year = vehicle_data.year
    vehicle_db.vin = vehicle_data.vin
    vehicle_db.mileage = vehicle_data.mileage

    db.commit()
    db.refresh(vehicle_db)

    return vehicle_db


@router.delete("/{vehicle_id}")
@limiter.limit("20/minute")
def delete_vehicle(
    request: Request,
    vehicle_id: int,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Delete a vehicle.
    - Regular users can only delete their vehicles
    - Admins can delete any vehicle
    """
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle is None:
        logger.warning(
            "delete denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this vehicle"
        )

    if access["user"].role == "customer":
        if vehicle.user_id != access["user"].id:
            logger.warning(
                "delete denied: vehicle %s belongs to user %s (user %s)",
                vehicle_id,
                vehicle.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this vehicle"
            )

        # The owner already knows their own vehicle, so this state hint
        # reveals nothing to anyone else.
        if vehicle.verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only delete unverified vehicles"
            )

    elif access["user"].role == "mechanic":
        logger.warning(
            "delete denied: mechanics cannot delete vehicles "
            "(mechanic %s, vehicle %s)",
            access["user"].id,
            vehicle_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this vehicle"
        )

# admin → puede eliminar cualquier vehículo

    db.delete(vehicle)
    db.commit()

    return {"message": "Vehicle deleted successfully"}