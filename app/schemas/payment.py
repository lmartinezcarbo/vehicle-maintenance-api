from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal


class PaymentCreate(BaseModel):
    maintenance_record_id: int

class PaymentResponse(BaseModel):
    id: int
    maintenance_record_id: int
    amount: Decimal
    currency: str
    status: str
    stripe_checkout_session_id: str | None
    created_at: datetime
    paid_at: datetime | None
    checkout_url: str


class PaymentDetailResponse(BaseModel):
    """Reading a payment never carries a checkout_url: that link only exists
    at creation time, and fetching it back would mean calling Stripe on read.
    """
    id: int
    maintenance_record_id: int
    amount: Decimal
    currency: str
    status: str
    stripe_checkout_session_id: str | None
    created_at: datetime
    paid_at: datetime | None
    