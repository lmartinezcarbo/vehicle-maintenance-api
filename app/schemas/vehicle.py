from pydantic import BaseModel, Field

from datetime import datetime


class VehicleCreate(BaseModel):
    user_id: int | None = None
    make: str
    model: str
    year: int
    vin: str
    mileage: int = Field(..., ge=0)

class VehicleResponse(BaseModel):
    id: int
    user_id: int
    make: str
    model: str
    year: int
    vin: str
    mileage: int
    created_at: datetime

class VehicleUpdate(BaseModel):
    make: str | None = None
    model: str | None = None
    year: int | None = None
    vin: str | None = None
    mileage: int | None = Field(default=None, ge=0)
