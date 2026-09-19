from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import VehicleCreate, VehicleResponse, VehicleUpdate
from app.models import User
from app.models.vehicle import Vehicle
from app.core.dependencies import get_current_user, get_access_user
from app.core.query_filters import filter_by_user_access

router = APIRouter(
    prefix="/vehicles",
    tags=["Vehicles"],
)

@router.post("/", response_model=VehicleResponse)
def create_vehicle(
    vehicle: VehicleCreate,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Create a new vehicle.
    - Regular users can only create vehicles for themselves
    - Admins can create vehicles for any user
    """
    if access["is_admin"]:
        if vehicle.user_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin must specify a user_id"
            )
        user_id = vehicle.user_id
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
    else:
        user_id = access["user"].id

    new_vehicle = Vehicle(
        user_id=user_id,
        make=vehicle.make,
        model=vehicle.model,
        year=vehicle.year,
        vin=vehicle.vin,
        mileage=vehicle.mileage,
    )

    db.add(new_vehicle)
    db.commit()
    db.refresh(new_vehicle)

    return new_vehicle

@router.get("/", response_model=list[VehicleResponse])
def get_vehicles(
    make: str | None = None,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Get all vehicles.
    - Regular users see only their vehicles
    - Admins see all vehicles
    """
    query = db.query(Vehicle)
    query = filter_by_user_access(
        query,
        access["user"],
        Vehicle.user_id
    )

    if make is not None:
        query = query.filter(Vehicle.make == make)

    return query.all()

@router.get("/{vehicle_id}", response_model=VehicleResponse)
def get_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    access = Depends(get_access_user)
):
    """
    Get a specific vehicle by ID.
    - Regular users can only access their vehicles
    - Admins can access any vehicle
    """
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

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

    return vehicle

@router.patch("/{vehicle_id}", response_model=VehicleResponse)
def update_vehicle(
    vehicle_id: int,
    vehicle: VehicleUpdate,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Update a vehicle.
    - Regular users can only update their vehicles
    - Admins can update any vehicle
    """
    vehicle_db = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle_db is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found"
        )

    if not access["is_admin"] and vehicle_db.user_id != access["user"].id:
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

@router.delete("/{vehicle_id}")
def delete_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Delete a vehicle.
    - Regular users can only delete their vehicles
    - Admins can delete any vehicle
    """
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found"
        )

    if not access["is_admin"] and vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this vehicle"
        )

    db.delete(vehicle)
    db.commit()

    return {"message": "Vehicle deleted successfully"}