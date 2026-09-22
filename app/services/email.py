import brevo
import logging

from app.core.config import settings


client = brevo.Brevo(
    api_key=settings.brevo_api_key
)

logger = logging.getLogger(__name__)

def send_email(
    to_email: str,
    subject: str,
    html_content: str,
) -> None:
    sender = brevo.SendTransacEmailRequestSender(
        email=settings.email_from
    )

    recipient = brevo.SendTransacEmailRequestToItem(
        email=to_email
    )

    try:
        client.transactional_emails.send_transac_email(
            sender=sender,
            to=[recipient],
            subject=subject,
            html_content=html_content,
        )
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        raise