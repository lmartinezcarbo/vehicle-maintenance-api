from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Session


from app.database import get_db
from app.schemas import VehicleCreate, VehicleResponse, VehicleUpdate
from app.models import User
from app.models.vehicle import Vehicle


router = APIRouter(
    prefix="/vehicles",
    tags=["Vehicles"],
)

@router.post("/", response_model=VehicleResponse)
def create_vehicle(
    user_id: int,
    vehicle: VehicleCreate,
    db: Session = Depends(get_db),
):
    
    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    new_vehicle = Vehicle(
        user_id=user_id,
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
):
    vehicles = db.query(Vehicle).all()

    return vehicles

@router.get("/{vehicles_id}", response_model=VehicleResponse)
def get_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found"
        )

    return vehicle

@router.patch("/{vehicles_id}", response_model=VehicleResponse)
def update_vehicle(
    vehicle_id: int,
    vehicle: VehicleUpdate,
    db: Session = Depends(get_db),
):
    vehicle_db = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle_db is None:
       raise HTTPException(
           status_code=status.HTTP_404_NOT_FOUND,
           detail="vehicle not found"
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
):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="vehicle not found"
        )

    db.delete(vehicle)

    db.commit

    return {"message": "Vehicle delete sucesfully"}