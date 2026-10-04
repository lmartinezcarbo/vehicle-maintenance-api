import stripe

from app.core.config import settings


stripe.api_key = settings.stripe_secret_key

def create_checkout_session(
    amount: int,
    currency: str,
    maintenance_record_id: int,
    payment_id: int
):
    return stripe.checkout.Session.create(
        success_url=settings.stripe_success_url,
        cancel_url=settings.stripe_cancel_url,
        
        mode="payment",
        line_items=[
            {
                "price_data": {
                    "currency": currency,
                    "product_data": {
                        "name": f"Vehicle maintenance #{maintenance_record_id}",
                    },
                    "unit_amount": amount,
                },
                "quantity": 1,
            }
        ],
        metadata={
            "maintenance_record_id": str(maintenance_record_id),
            "payment_id": str(payment_id),
        },
    )