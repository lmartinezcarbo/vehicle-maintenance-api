from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class MaintenanceRecordCreate(BaseModel):
    vehicle_id: int
    service_type: str
    description: str
    mileage: int
    service_date: datetime
    labor_cost: Decimal
    notes: str | None = None

class MaintenanceRecordResponse(BaseModel):
    id: int
    vehicle_id: int
    service_type: str
    description: str
    mileage: int
    service_date: datetime
    labor_cost: Decimal
    notes: str | None
    created_at: datetime

class MaintenanceRecordUpdate(BaseModel):
    service_type: str | None = None
    description: str | None = None
    mileage: int | None = None
    service_date: datetime | None = None
    labor_cost: Decimal | None = None
    notes: str | None = None