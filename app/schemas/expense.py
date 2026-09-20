from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class ExpenseCreate(BaseModel):
    vehicle_id: int
    maintenance_record_id: int | None = None
    category: str
    amount: Decimal
    description: str | None = None
    expense_date: datetime


class ExpenseResponse(BaseModel):
    id: int
    vehicle_id: int
    maintenance_record_id: int | None
    category: str
    amount: Decimal
    description: str | None
    expense_date: datetime
    created_at: datetime


class ExpenseUpdate(BaseModel):
    category: str | None = None
    amount: Decimal | None = None
    description: str | None = None
    expense_date: datetime | None = None

class ExpensePut(BaseModel):
    category: str
    amount: Decimal
    description: str | None = None
    expense_date: datetime

