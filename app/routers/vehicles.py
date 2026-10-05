import logging
import uuid
from enum import Enum
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.schemas import VehicleCreate, VehicleResponse, VehicleUpdate, VehiclePut
from app.models import User
from app.models.vehicle import Vehicle
from app.core.dependencies import get_access_user, require_mechanic
from app.core.query_filters import filter_by_user_access
from app.core.query_params import get_sort_params, SortOrder
from app.core.rate_limit import limiter

logger = logging.getLogger(__name__)

# One photo per vehicle, optional. 5 MB: current phone cameras land
# between 1 and 4 MB, and the cap is what stops a single request from
# deciding how much memory the process spends.
MAX_PHOTO_BYTES = 5 * 1024 * 1024

PHOTO_MEDIA_TYPES = {
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def detect_image_type(data: bytes) -> str | None:
    """
    Return the extension of an accepted image, or None.
    The check runs on the magic bytes, never on the Content-Type the
    client declares: that header is user input and it lies.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    # WEBP is "RIFF" + size + "WEBP"; RIFF alone also covers WAV.
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"

    return None


def remove_photo_file(filename: str) -> None:
    """
    Best effort: an undeletable file is a log line, never a 500.
    """
    # .name even on our own value: a column never becomes a path.
    target = Path(settings.uploads_dir) / Path(filename).name

    try:
        target.unlink(missing_ok=True)
    except OSError:
        logger.warning("photo file %s could not be removed", filename)


class VehicleSearchField(str, Enum):
    make = "make"
    model = "model"
    vin = "vin"


router = APIRouter(
    prefix="/vehicles",
    tags=["Vehicles"],
)


@router.post(
    "/",
    response_model=VehicleResponse,
    status_code=status.HTTP_201_CREATED
)
@limiter.limit("20/minute")
def create_vehicle(
    request: Request,
    vehicle: VehicleCreate,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Create a new vehicle.
    - Regular users can only create vehicles for themselves
    - Admins can create vehicles for any user
    """
    if access["user"].role == "customer":
        user_id = access["user"].id
        verified = False

    elif access["user"].role in ("mechanic", "admin"):
        if vehicle.user_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_id is required"
            )

        user_id = vehicle.user_id

        user = db.query(User).filter(User.id == user_id).first()

        if access["user"].role == "mechanic":
            if user is None or user.role != "customer":
                logger.warning(
                    "create vehicle denied: user %s does not exist or is "
                    "not a customer (mechanic %s)",
                    user_id,
                    access["user"].id,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to create this vehicle",
                )
        elif user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        verified = True

    new_vehicle = Vehicle(
        user_id=user_id,
        make=vehicle.make,
        model=vehicle.model,
        year=vehicle.year,
        vin=vehicle.vin,
        mileage=vehicle.mileage,
        verified=verified,
    )

    db.add(new_vehicle)
    db.commit()
    db.refresh(new_vehicle)

    return new_vehicle


@router.get("/", response_model=list[VehicleResponse])
def get_vehicles(
    make: str | None = None,
    model: str | None = None,
    year: int | None = None,
    search: str | None = None,
    search_by: VehicleSearchField = VehicleSearchField.make,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_params=Depends(get_sort_params),
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Get vehicles.
    - Regular users see only their vehicles
    - Admins see all vehicles
    - Supports filtering, searching, pagination and sorting
    """

    query = db.query(Vehicle)

    if access["user"].role == "customer":
        query = query.filter(
            Vehicle.user_id == access["user"].id
        )

    elif access["user"].role == "mechanic":
        query = query.join(User).filter(
            User.role == "customer"
        )

# admin → no filtro, puede ver todos

    # Exact filters
    if make is not None:
        query = query.filter(Vehicle.make == make)

    if model is not None:
        query = query.filter(Vehicle.model == model)

    if year is not None:
        query = query.filter(Vehicle.year == year)

    # Search
    if search:
        if search_by == VehicleSearchField.make:
            query = query.filter(
                Vehicle.make.ilike(f"%{search}%")
            )

        elif search_by == VehicleSearchField.model:
            query = query.filter(
                Vehicle.model.ilike(f"%{search}%")
            )

        else:
            query = query.filter(
                Vehicle.vin.ilike(f"%{search}%")
            )

    # Sorting
    sort_columns = {
        "make": Vehicle.make,
        "model": Vehicle.model,
        "year": Vehicle.year,
        "mileage": Vehicle.mileage,
        "vin": Vehicle.vin,
    }

    sort_by = sort_params["sort_by"]
    order = sort_params["order"]

    if sort_by:
        sort_column = sort_columns.get(sort_by)

        if sort_column is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid sort field"
            )

        if order == SortOrder.asc:
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

    # Pagination
    return query.offset(offset).limit(limit).all()


@router.get("/{vehicle_id}", response_model=VehicleResponse)
def get_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    access=Depends(get_access_user)
):
    """
    Get a specific vehicle by ID.
    - Regular users can only access their vehicles
    - Admins can access any vehicle
    """
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle is None:
        logger.warning(
            "access denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this vehicle"
        )

    if access["user"].role == "customer":
        if vehicle.user_id != access["user"].id:
            logger.warning(
                "access denied: vehicle %s belongs to user %s (user %s)",
                vehicle_id,
                vehicle.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this vehicle"
            )

    elif access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "access denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this vehicle"
            )

# admin → puede acceder a cualquier vehículo

    return vehicle

@router.patch("/{vehicle_id}/verify", response_model=VehicleResponse)
@limiter.limit("20/minute")
def verify_vehicle(
    request: Request,
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_mechanic),
):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle is None:
        logger.warning(
            "verify denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to verify this vehicle"
        )

    if current_user.role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "verify denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                vehicle_id,
                current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to verify this vehicle"
            )

    # State only after authorization: whoever may not verify gets 403 with
    # the same body whether the vehicle is missing or already verified.
    if vehicle.verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle is already verified"
        )

    vehicle.verified = True

    db.commit()
    db.refresh(vehicle)

    return vehicle

@router.patch("/{vehicle_id}", response_model=VehicleResponse)
@limiter.limit("20/minute")
def update_vehicle(
    request: Request,
    vehicle_id: int,
    vehicle: VehicleUpdate,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Update a vehicle.
    - Regular users can only update their vehicles
    - Admins can update any vehicle
    """
    vehicle_db = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle_db is None:
        logger.warning(
            "update denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this vehicle"
        )

    if access["user"].role == "customer":
        if vehicle_db.user_id != access["user"].id:
            logger.warning(
                "update denied: vehicle %s belongs to user %s "
                "(user %s)",
                vehicle_id,
                vehicle_db.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this vehicle"
            )

        # The owner already knows their own vehicle, so this state hint
        # reveals nothing to anyone else.
        if vehicle_db.verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only modify unverified vehicles"
            )

    if access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle_db.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "update denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this vehicle"
            )

    update_data = vehicle.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(vehicle_db, field, value)

    db.commit()
    db.refresh(vehicle_db)

    return vehicle_db


@router.put("/{vehicle_id}", response_model=VehicleResponse)
@limiter.limit("20/minute")
def replace_vehicle(
    request: Request,
    vehicle_id: int,
    vehicle_data: VehiclePut,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    vehicle_db = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle_db is None:
        logger.warning(
            "replace denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to replace this vehicle"
        )

    if access["user"].role == "customer":
        if vehicle_db.user_id != access["user"].id:
            logger.warning(
                "replace denied: vehicle %s belongs to user %s "
                "(user %s)",
                vehicle_id,
                vehicle_db.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to replace this vehicle"
            )

        # The owner already knows their own vehicle, so this state hint
        # reveals nothing to anyone else.
        if vehicle_db.verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only modify unverified vehicles"
            )

    if access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle_db.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "replace denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to replace this vehicle"
            )

    vehicle_db.make = vehicle_data.make
    vehicle_db.model = vehicle_data.model
    vehicle_db.year = vehicle_data.year
    vehicle_db.vin = vehicle_data.vin
    vehicle_db.mileage = vehicle_data.mileage

    db.commit()
    db.refresh(vehicle_db)

    return vehicle_db


@router.delete("/{vehicle_id}")
@limiter.limit("20/minute")
def delete_vehicle(
    request: Request,
    vehicle_id: int,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Delete a vehicle.
    - Regular users can only delete their vehicles
    - Admins can delete any vehicle
    """
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle is None:
        logger.warning(
            "delete denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this vehicle"
        )

    if access["user"].role == "customer":
        if vehicle.user_id != access["user"].id:
            logger.warning(
                "delete denied: vehicle %s belongs to user %s (user %s)",
                vehicle_id,
                vehicle.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this vehicle"
            )

        # The owner already knows their own vehicle, so this state hint
        # reveals nothing to anyone else.
        if vehicle.verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only delete unverified vehicles"
            )

    elif access["user"].role == "mechanic":
        logger.warning(
            "delete denied: mechanics cannot delete vehicles "
            "(mechanic %s, vehicle %s)",
            access["user"].id,
            vehicle_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this vehicle"
        )

# admin → puede eliminar cualquier vehículo

    # Captured before the delete: the instance is expired afterwards.
    photo_file = vehicle.photo_file

    db.delete(vehicle)
    db.commit()

    if photo_file is not None:
        remove_photo_file(photo_file)

    logger.info(
        "vehicle %s deleted (user %s)", vehicle_id, access["user"].id
    )

    return {"message": "Vehicle deleted successfully"}


@router.post("/{vehicle_id}/photo")
@limiter.limit("20/minute")
async def upload_vehicle_photo(
    request: Request,
    vehicle_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Upload the vehicle's photo, replacing any previous one.
    - Same rules as updating the vehicle: owners of unverified vehicles,
      mechanics over customer-owned vehicles, admins over everything
    """
    vehicle_db = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle_db is None:
        logger.warning(
            "photo upload denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to upload a photo to this vehicle",
        )

    if access["user"].role == "customer":
        if vehicle_db.user_id != access["user"].id:
            logger.warning(
                "photo upload denied: vehicle %s belongs to user %s "
                "(user %s)",
                vehicle_id,
                vehicle_db.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to upload a photo to this vehicle",
            )

        # The owner already knows their own vehicle, so this state hint
        # reveals nothing to anyone else.
        if vehicle_db.verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only modify unverified vehicles",
            )

    if access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle_db.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "photo upload denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to upload a photo to this vehicle",
            )

    # One byte past the limit: enough to know it is too big, without
    # letting the request decide how much memory we spend.
    content = await file.read(MAX_PHOTO_BYTES + 1)

    if len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Photo exceeds the 5 MB limit",
        )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The photo file is empty",
        )

    extension = detect_image_type(content)

    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only JPEG, PNG and WEBP images are accepted",
        )

    uploads = Path(settings.uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)

    # uuid, never the client's filename: "../../etc/passwd" is exactly
    # what path traversal looks like on the way in.
    filename = f"{uuid.uuid4().hex}.{extension}"
    previous = vehicle_db.photo_file

    try:
        (uploads / filename).write_bytes(content)
        vehicle_db.photo_file = filename
        db.commit()
    except Exception:
        # The row is the source of truth: when it cannot be written the
        # file must not stay behind as an orphan.
        (uploads / filename).unlink(missing_ok=True)
        raise

    if previous is not None:
        # Post-commit and best effort: the photo that answers from now on
        # is already the new one, a leftover file is only a log line.
        remove_photo_file(previous)

    logger.info(
        "vehicle %s photo uploaded (user %s)",
        vehicle_id,
        access["user"].id,
    )

    if previous is not None:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "Vehicle photo replaced"},
        )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"message": "Vehicle photo uploaded"},
    )


@router.get("/{vehicle_id}/photo")
@limiter.limit("20/minute")
def get_vehicle_photo(
    request: Request,
    vehicle_id: int,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Serve the vehicle's photo.
    - Same readers as GET /vehicles/{id}
    """
    vehicle_db = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle_db is None:
        logger.warning(
            "photo access denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this vehicle",
        )

    if access["user"].role == "customer":
        if vehicle_db.user_id != access["user"].id:
            logger.warning(
                "photo access denied: vehicle %s belongs to user %s "
                "(user %s)",
                vehicle_id,
                vehicle_db.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this vehicle",
            )

    elif access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle_db.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "photo access denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this vehicle",
            )

    if vehicle_db.photo_file is None:
        # Only now that authorization passed: the caller already knows
        # the vehicle exists and nobody else learns anything.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle has no photo",
        )

    path = Path(settings.uploads_dir) / Path(vehicle_db.photo_file).name

    if not path.is_file():
        # The row is the source of truth for existence; there is simply
        # nothing to serve. Never a silent 200.
        logger.warning(
            "photo file missing for vehicle %s (%s)",
            vehicle_id,
            vehicle_db.photo_file,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle has no photo",
        )

    media_type = PHOTO_MEDIA_TYPES.get(
        path.suffix.lstrip("."),
        "application/octet-stream",
    )

    return Response(
        content=path.read_bytes(),
        media_type=media_type,
        # private: no shared cache keeps somebody's car photo around.
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.delete("/{vehicle_id}/photo", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
def delete_vehicle_photo(
    request: Request,
    vehicle_id: int,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Remove the vehicle's photo. The vehicle itself is untouched.
    - Same rules as updating the vehicle
    """
    vehicle_db = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()

    if vehicle_db is None:
        logger.warning(
            "photo removal denied: vehicle %s does not exist (user %s)",
            vehicle_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to remove a photo from this vehicle",
        )

    if access["user"].role == "customer":
        if vehicle_db.user_id != access["user"].id:
            logger.warning(
                "photo removal denied: vehicle %s belongs to user %s "
                "(user %s)",
                vehicle_id,
                vehicle_db.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to remove a photo from this vehicle",
            )

        # The owner already knows their own vehicle, so this state hint
        # reveals nothing to anyone else.
        if vehicle_db.verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers can only modify unverified vehicles",
            )

    if access["user"].role == "mechanic":
        owner = db.query(User).filter(
            User.id == vehicle_db.user_id
        ).first()

        if owner is None or owner.role != "customer":
            logger.warning(
                "photo removal denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to remove a photo from this vehicle",
            )

    if vehicle_db.photo_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle has no photo",
        )

    filename = vehicle_db.photo_file
    vehicle_db.photo_file = None
    db.commit()

    remove_photo_file(filename)

    logger.info(
        "vehicle %s photo removed (user %s)",
        vehicle_id,
        access["user"].id,
    )

    return