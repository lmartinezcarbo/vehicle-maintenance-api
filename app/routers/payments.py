import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from stripe import SignatureVerificationError

from app.database import get_db
from app.schemas import PaymentCreate, PaymentResponse, PaymentDetailResponse
from app.models import Payment, MaintenanceRecord, Vehicle
from app.core.dependencies import get_current_user
from app.core.rate_limit import limiter
from app.services.maintenance_price import calculate_maintenance_total
from app.services.stripe_service import (
    create_checkout_session,
    construct_event,
    get_checkout_url,
)

logger = logging.getLogger(__name__)

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

    already_paid = (
        db.query(Payment)
        .filter(
            Payment.maintenance_record_id == maintenance_record.id,
            Payment.status == "paid",
        )
        .first()
    )

    if already_paid is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Maintenance record has already been paid",
        )

    open_checkout = (
        db.query(Payment)
        .filter(
            Payment.maintenance_record_id == maintenance_record.id,
            Payment.status == "pending",
        )
        .first()
    )

    # A committed pending payment always carries a Stripe session id: the row
    # only survives the commit when session creation succeeded. Handing the
    # same checkout back makes POST /payments/ idempotent, so a retry can
    # never start a second charge for one record.
    if open_checkout is not None:
        return {
            "id": open_checkout.id,
            "maintenance_record_id": open_checkout.maintenance_record_id,
            "amount": open_checkout.amount,
            "currency": open_checkout.currency,
            "status": open_checkout.status,
            "stripe_checkout_session_id": open_checkout.stripe_checkout_session_id,
            "checkout_url": get_checkout_url(
                open_checkout.stripe_checkout_session_id
            ),
            "created_at": open_checkout.created_at,
            "paid_at": open_checkout.paid_at,
        }

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


@router.get("/{payment_id}", response_model=PaymentDetailResponse)
def get_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Read the current state of a payment.

    The frontend polls this after coming back from Stripe until the webhook
    has flipped the status to "paid".
    """
    payment = (
        db.query(Payment)
        .filter(Payment.id == payment_id)
        .first()
    )

    # Same policy as vehicles: a payment that does not exist and one owned by
    # somebody else must be indistinguishable, so ids cannot be probed.
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this payment",
        )

    vehicle = payment.maintenance_record.vehicle

    if vehicle.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this payment",
        )

    return payment


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Stripe sends this request. It is authenticated by signature, not JWT.
    """
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")

    try:
        event = construct_event(payload, signature)
    except SignatureVerificationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        )

    event_data = event.to_dict()
    event_type = event_data.get("type")

    if event_type not in (
        "checkout.session.completed",
        "checkout.session.async_payment_failed",
        "checkout.session.expired",
    ):
        return {"received": True}

    session = (event_data.get("data") or {}).get("object") or {}
    metadata = session.get("metadata") or {}

    payment_id = str(metadata.get("payment_id", ""))
    if not payment_id.isdigit():
        logger.error("Webhook event %s without a valid payment_id", event_data.get("id"))
        return {"received": True}

    payment = (
        db.query(Payment)
        .filter(Payment.id == int(payment_id))
        .first()
    )

    if payment is None or payment.status != "pending":
        return {"received": True}

    # The price we froze must match what Stripe actually charged.
    amount_total = session.get("amount_total")
    if amount_total is None or int(payment.amount * 100) != amount_total:
        logger.error(
            "Webhook amount mismatch for payment %s: expected %s, got %s",
            payment.id,
            payment.amount,
            amount_total,
        )
        return {"received": True}

    if event_type == "checkout.session.completed":
        if session.get("payment_status") != "paid":
            return {"received": True}
        payment.status = "paid"
        payment.paid_at = datetime.now(timezone.utc)
        if session.get("payment_intent"):
            payment.stripe_payment_intent_id = session["payment_intent"]
    elif event_type == "checkout.session.async_payment_failed":
        payment.status = "failed"
    else:
        payment.status = "expired"

    db.commit()

    return {"received": True}