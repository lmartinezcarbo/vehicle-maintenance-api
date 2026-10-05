"""
Photo storage on Cloudinary - the seam between our API and the CDN.

Everything that talks to the outside world lives here, and only here, so
tests can replace the whole module (the exact trick used for Brevo in
app/services/email.py). The API never learns Cloudinary's SDK details.

Why photos do not live on disk: Render's free instances lose their local
filesystem on every redeploy, restart and idle spin-down, so bytes stored
on disk would silently disappear.
"""
import io
import logging
import uuid
import urllib.error
import urllib.request

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    import cloudinary
    import cloudinary.api
    import cloudinary.uploader
except ImportError:  # pragma: no cover - dependency is in requirements.txt
    cloudinary = None


class PhotoStorageError(Exception):
    """The photo provider could not be reached or refused the request."""


def _configure() -> None:
    if cloudinary is None:
        raise PhotoStorageError("cloudinary SDK is not installed")

    if not (
        settings.cloudinary_cloud_name
        and settings.cloudinary_api_key
        and settings.cloudinary_api_secret
    ):
        raise PhotoStorageError("Cloudinary credentials are not configured")

    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )


def upload_photo(
    vehicle_id: int,
    content: bytes,
    extension: str,
) -> tuple[str, str]:
    """
    Store the image and return (public_id, secure_url).

    The public_id is ours, not Cloudinary's: a name we control is what a
    later delete can point at without parsing anything.
    """
    _configure()

    public_id = f"vehicles/{vehicle_id}/{uuid.uuid4().hex}"

    try:
        result = cloudinary.uploader.upload(
            io.BytesIO(content),
            public_id=public_id,
            format=extension,
            resource_type="image",
        )
    except Exception as exc:
        logger.warning(
            "cloudinary upload failed for vehicle %s: %s", vehicle_id, exc
        )
        raise PhotoStorageError("upload failed") from exc

    secure_url = result.get("secure_url")

    if not secure_url:
        logger.warning(
            "cloudinary returned no url for vehicle %s", vehicle_id
        )
        raise PhotoStorageError("upload returned no url")

    return result.get("public_id", public_id), secure_url


def fetch_photo(url: str) -> bytes:
    """
    Download the stored image so the API stays the only gate in front of
    it. Upstream failure is reported, never guessed at.
    """
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("photo fetch failed for %s: %s", url, exc)
        raise PhotoStorageError("fetch failed") from exc


def delete_photo(public_id: str) -> None:
    """
    Best effort: a provider that will not delete leaves a log line, never
    a 500 on an operation the caller already saw succeed.
    """
    try:
        _configure()
        cloudinary.uploader.destroy(public_id, resource_type="image")
    except Exception as exc:
        logger.warning(
            "cloudinary destroy failed for %s: %s", public_id, exc
        )
