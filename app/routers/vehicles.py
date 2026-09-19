from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Session


from app.database import get_db
from app.schemas import VehicleCreate, VehicleResponse, VehicleUpdate
from app.models import User
from app.models.vehicle import Vehicle
from app.core.dependencies import get_current_user


router = APIRouter(
    prefix="/vehicles",
    tags=["Vehicles"],
)

@router.post("/", response_model=VehicleResponse)
def create_vehicle(
    vehicle: VehicleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    
    new_vehicle = Vehicle(
        user_id=current_user.id,
        make=vehicle.make,
        model=vehicle.model,
        year=vehicle.year,
        vin=vehicle.vin,
        mileage=vehicle.mileage,
    )

    db.add(new_vehicle)
    db.commit ()
    db.refresh(new_vehicle)

    return new_vehicle

@router.get("/", response_model=list[VehicleResponse])
def get_vehicles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicles = db.query(Vehicle).filter(
        Vehicle.user_id == current_user.id
    ).all()

    return vehicles

@router.get("/{vehicles_id}", response_model=VehicleResponse)
def get_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found"
        )

    if vehicle.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this vehicle"
        )

    return vehicle

@router.patch("/{vehicles_id}", response_model=VehicleResponse)
def update_vehicle(
    vehicle_id: int,
    vehicle: VehicleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicle_db = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle_db is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found"
        )

    if vehicle_db.user_id != current_user.id:
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
    current_user: User = Depends(get_current_user),
):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found"
        )

    if vehicle.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this vehicle"
        )

    db.delete(vehicle)
    db.commit()

    return {"message": "Vehicle deleted successfully"}