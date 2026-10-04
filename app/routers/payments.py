from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import PaymentCreate, PaymentResponse
from app.models import Payment, MaintenanceRecord, Vehicle
from app.core.dependencies import get_current_user
from app.core.rate_limit import limiter
from app.services.maintenance_price import calculate_maintenance_total
from app.services.stripe_service import create_checkout_session

router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)

@router.post(
    "/",
    response_model=PaymentResponse,
)
@limiter.limit("10/minute")
def create_payment(
    request: Request,
    payment_data: PaymentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    maintenance_record = (
        db.query(MaintenanceRecord)
        .filter(
            MaintenanceRecord.id == payment_data.maintenance_record_id
        )
        .first()
    )

    if maintenance_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance record not found",
        )

    if maintenance_record.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maintenance record is not ready for payment",
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == maintenance_record.vehicle_id)
        .first()
    )

    if vehicle is None or vehicle.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to pay for this maintenance record",
        )

    total_cost = calculate_maintenance_total(
        db=db,
        maintenance_record_id=maintenance_record.id,
        labor_cost=maintenance_record.labor_cost,
    )

    currency = "usd"

    if total_cost <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maintenance total must be greater than zero",
        )

    stripe_amount = int(total_cost * 100)

    payment = Payment(
        maintenance_record_id=maintenance_record.id,
        amount=total_cost,
        currency=currency,
        status="pending",
    )

    db.add(payment)
    db.flush()

    try:
        checkout_session = create_checkout_session(
            amount=stripe_amount,
            currency=currency,
            maintenance_record_id=maintenance_record.id,
            payment_id=payment.id,
        )
    except Exception:
        db.rollback()
        raise

    payment.stripe_checkout_session_id = checkout_session.id

    db.commit()
    db.refresh(payment)

    return {
        "id": payment.id,
        "maintenance_record_id": payment.maintenance_record_id,
        "amount": payment.amount,
        "currency": payment.currency,
        "status": payment.status,
        "stripe_checkout_session_id": payment.stripe_checkout_session_id,
        "checkout_url": checkout_session.url,
        "created_at": payment.created_at,
        "paid_at": payment.paid_at,
    }