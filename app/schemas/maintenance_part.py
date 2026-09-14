from decimal import Decimal

from pydantic import BaseModel


class MaintenancePartCreate(BaseModel):
    maintenance_record_id: int
    part_id: int
    quantity: int
    unit_cost: Decimal


class MaintenancePartResponse(BaseModel):
    id: int
    maintenance_record_id: int
    part_id: int
    quantity: int
    unit_cost: Decimal


class MaintenancePartUpdate(BaseModel):
    quantity: int | None = None
    unit_cost: Decimal | None = None

