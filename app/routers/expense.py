import logging
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.schemas import ExpenseCreate, ExpenseResponse, ExpenseUpdate, ExpensePut
from app.models.expense import Expense
from app.models.vehicle import Vehicle
from app.models.maintenance_record import MaintenanceRecord
from app.core.dependencies import get_access_user, require_mechanic
from app.core.query_params import get_sort_params, SortOrder
from app.core.rate_limit import limiter
from app.models import User

logger = logging.getLogger(__name__)


class ExpenseSearchField(str, Enum):
    category = "category"
    description = "description"


router = APIRouter(
    prefix="/expenses",
    tags=["Expenses"],
)


@router.post(
    "/",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/minute")
def create_expense(
    request: Request,
    expense: ExpenseCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_mechanic),
):
    """
    Create a new expense for a vehicle.

    Permissions:
    - Admin users can create expenses for any vehicle.
    - Regular users can only create expenses for their own vehicles.
    """

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == expense.vehicle_id)
        .first()
    )

    if vehicle is None:
        logger.warning(
            "create expense denied: vehicle %s does not exist (user %s)",
            expense.vehicle_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create an expense for this vehicle",
        )

    # Authorization before state: whoever may not use this vehicle gets
    # the same 403 whether it is unverified or owned by nobody.
    if current_user.role == "mechanic":
        owner = (
            db.query(User)
            .filter(User.id == vehicle.user_id)
            .first()
        )

        if owner is None or owner.role != "customer":
            logger.warning(
                "create expense denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                expense.vehicle_id,
                current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to create an expense for this vehicle",
            )

    if not vehicle.verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle must be verified before creating expenses",
        )

    # Validate maintenance record if provided
    if expense.maintenance_record_id is not None:
        maintenance_record = (
            db.query(MaintenanceRecord)
            .filter(
                MaintenanceRecord.id == expense.maintenance_record_id
            )
            .first()
        )

        if maintenance_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Maintenance record not found",
            )

        # The maintenance record must belong to the same vehicle
        if maintenance_record.vehicle_id != expense.vehicle_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maintenance record does not belong to this vehicle",
            )

        # Expenses do not enter the amount Stripe charges (that is labor
        # plus parts), but a record that left "in_progress" is closed for
        # new work: it must stop changing as a whole.
        if maintenance_record.status != "in_progress":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only records in progress can be modified",
            )

    new_expense = Expense(
        vehicle_id=expense.vehicle_id,
        maintenance_record_id=expense.maintenance_record_id,
        category=expense.category,
        amount=expense.amount,
        description=expense.description,
        expense_date=expense.expense_date,
    )

    db.add(new_expense)
    db.commit()
    db.refresh(new_expense)

    return new_expense


@router.get("/", response_model=list[ExpenseResponse])
def get_expenses(
    vehicle_id: int | None = None,
    maintenance_record_id: int | None = None,
    category: str | None = None,
    search: str | None = None,
    search_by: ExpenseSearchField = ExpenseSearchField.category,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_params=Depends(get_sort_params),
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Get expenses with filtering, searching, sorting and pagination.

    Permissions:
    - Admin users can see all expenses.
    - Regular users can only see expenses for their own vehicles.
    """

    query = (
        db.query(Expense)
        .options(joinedload(Expense.vehicle))
        .join(Vehicle)
    )

    # ---------------------------------------------------------
    # AUTHORIZATION
    # ---------------------------------------------------------
    # This is applied BEFORE returning any results.
    # Regular users only see expenses belonging to their vehicles.
    if access["user"].role == "customer":
        query = query.filter(
            Vehicle.user_id == access["user"].id
        )

    elif access["user"].role == "mechanic":
        query = query.join(User).filter(
            User.role == "customer"
        )

# admin → no filter

    # ---------------------------------------------------------
    # EXACT FILTERS
    # ---------------------------------------------------------

    if vehicle_id is not None:
        query = query.filter(
            Expense.vehicle_id == vehicle_id
        )

    if maintenance_record_id is not None:
        query = query.filter(
            Expense.maintenance_record_id == maintenance_record_id
        )

    if category is not None:
        query = query.filter(
            Expense.category == category
        )

    # ---------------------------------------------------------
    # SEARCH
    # ---------------------------------------------------------

    if search:
        if search_by == ExpenseSearchField.category:
            query = query.filter(
                Expense.category.ilike(f"%{search}%")
            )
        else:
            query = query.filter(
                Expense.description.ilike(f"%{search}%")
            )

    # ---------------------------------------------------------
    # SORTING
    # ---------------------------------------------------------

    sort_columns = {
        "category": Expense.category,
        "amount": Expense.amount,
        "expense_date": Expense.expense_date,
        "created_at": Expense.created_at,
        "vehicle_id": Expense.vehicle_id,
        "maintenance_record_id": Expense.maintenance_record_id,
    }

    sort_by = sort_params["sort_by"]
    order = sort_params["order"]

    if sort_by:
        sort_column = sort_columns.get(sort_by)

        if sort_column is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid sort field",
            )

        if order == SortOrder.asc:
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

    # ---------------------------------------------------------
    # PAGINATION
    # ---------------------------------------------------------

    return query.offset(offset).limit(limit).all()


@router.get("/{expense_id}", response_model=ExpenseResponse)
def get_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Get a specific expense by ID.

    Permissions:
    - Admin users can access any expense.
    - Regular users can only access expenses for their own vehicles.
    """

    expense = (
        db.query(Expense)
        .options(joinedload(Expense.vehicle))
        .filter(Expense.id == expense_id)
        .first()
    )

    if expense is None:
        logger.warning(
            "access denied: expense %s does not exist (user %s)",
            expense_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this expense",
        )

    if expense.vehicle is None:
        logger.warning(
            "access denied: expense %s has no vehicle", expense_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this expense",
        )

    # Authorization
    if access["user"].role == "customer":
        if expense.vehicle.user_id != access["user"].id:
            logger.warning(
                "access denied: expense %s belongs to vehicle of user %s "
                "(user %s)",
                expense_id,
                expense.vehicle.user_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this expense",
            )

    elif access["user"].role == "mechanic":
        owner = (
            db.query(User)
            .filter(User.id == expense.vehicle.user_id)
            .first()
        )

        if owner is None or owner.role != "customer":
            logger.warning(
                "access denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                expense.vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this expense",
            )

# admin → can access any expense

    return expense


@router.patch("/{expense_id}", response_model=ExpenseResponse)
@limiter.limit("20/minute")
def update_expense(
    request: Request,
    expense_id: int,
    expense: ExpenseUpdate,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Update an existing expense.

    Permissions:
    - Admin users can update any expense.
    - Regular users can only update expenses for their own vehicles.
    """

    expense_db = (
        db.query(Expense)
        .options(joinedload(Expense.vehicle))
        .filter(Expense.id == expense_id)
        .first()
    )

    if expense_db is None:
        logger.warning(
            "update denied: expense %s does not exist (user %s)",
            expense_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this expense",
        )

    # ---------------------------------------------------------
    # AUTHORIZATION OF CURRENT EXPENSE
    # ---------------------------------------------------------

    if expense_db.vehicle is None:
        logger.warning(
            "update denied: expense %s has no vehicle", expense_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this expense",
        )

    if access["user"].role == "customer":
        logger.warning(
            "update denied: user %s is a customer (expense %s)",
            access["user"].id,
            expense_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this expense",
        )

    if access["user"].role == "mechanic":
        owner = (
            db.query(User)
            .filter(User.id == expense_db.vehicle.user_id)
            .first()
        )

        if owner is None or owner.role != "customer":
            logger.warning(
                "update denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                expense_db.vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this expense",
            )

# admin → can modify any expense

    update_data = expense.model_dump(exclude_unset=True)

    # ---------------------------------------------------------
    # VALIDATE NEW VEHICLE
    # ---------------------------------------------------------

    if "vehicle_id" in update_data:
        new_vehicle = (
            db.query(Vehicle)
            .filter(Vehicle.id == update_data["vehicle_id"])
            .first()
        )

        if new_vehicle is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to use this vehicle",
            )

        # A regular user cannot move the expense to another user's vehicle
        if (
            not access["is_admin"]
            and new_vehicle.user_id != access["user"].id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to use this vehicle",
            )

    # ---------------------------------------------------------
    # VALIDATE MAINTENANCE RECORD
    # ---------------------------------------------------------

    if "maintenance_record_id" in update_data:
        new_maintenance_record_id = update_data["maintenance_record_id"]

        if new_maintenance_record_id is not None:
            maintenance_record = (
                db.query(MaintenanceRecord)
                .filter(
                    MaintenanceRecord.id == new_maintenance_record_id
                )
                .first()
            )

            if maintenance_record is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Maintenance record not found",
                )

            # Determine which vehicle the expense will belong to
            new_vehicle_id = update_data.get(
                "vehicle_id",
                expense_db.vehicle_id,
            )

            # Maintenance record must belong to the same vehicle
            if maintenance_record.vehicle_id != new_vehicle_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Maintenance record does not belong to this vehicle",
                )

    # ---------------------------------------------------------
    # FROZEN RECORD
    # ---------------------------------------------------------

    # The expense may neither live on nor move to a record that already
    # left "in_progress": a record stops changing as a whole.
    affected_record_ids = {
        expense_db.maintenance_record_id,
        update_data.get(
            "maintenance_record_id",
            expense_db.maintenance_record_id,
        ),
    }

    for record_id in affected_record_ids:
        if record_id is None:
            continue

        record = (
            db.query(MaintenanceRecord)
            .filter(MaintenanceRecord.id == record_id)
            .first()
        )

        if record is None:
            continue

        if record.status != "in_progress":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only records in progress can be modified",
            )

    # ---------------------------------------------------------
    # APPLY UPDATE
    # ---------------------------------------------------------

    for field, value in update_data.items():
        setattr(expense_db, field, value)

    db.commit()
    db.refresh(expense_db)

    return expense_db

@router.put("/{expense_id}", response_model=ExpenseResponse)
@limiter.limit("20/minute")
def replace_expense(
    request: Request,
    expense_id: int,
    expense_data: ExpensePut,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    expense_db = (
        db.query(Expense)
        .filter(Expense.id == expense_id)
        .first()
    )

    if expense_db is None:
        logger.warning(
            "replace denied: expense %s does not exist (user %s)",
            expense_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to replace this expense"
        )

    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == expense_db.vehicle_id)
        .first()
    )

    if vehicle is None:
        logger.warning(
            "replace denied: expense %s has no vehicle", expense_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to replace this expense"
        )

    if access["user"].role == "customer":
        logger.warning(
            "replace denied: user %s is a customer (expense %s)",
            access["user"].id,
            expense_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to replace this expense"
        )

    if access["user"].role == "mechanic":
        owner = (
            db.query(User)
            .filter(User.id == vehicle.user_id)
            .first()
        )

        if owner is None or owner.role != "customer":
            logger.warning(
                "replace denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                expense_db.vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to replace this expense"
            )

# admin → can modify any expense

    # The expense stops changing once the record it lives on left
    # "in_progress".
    if expense_db.maintenance_record_id is not None:
        record = (
            db.query(MaintenanceRecord)
            .filter(
                MaintenanceRecord.id == expense_db.maintenance_record_id
            )
            .first()
        )

        if record is not None and record.status != "in_progress":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only records in progress can be modified",
            )

    expense_db.category = expense_data.category
    expense_db.amount = expense_data.amount
    expense_db.description = expense_data.description
    expense_db.expense_date = expense_data.expense_date

    db.commit()
    db.refresh(expense_db)

    return expense_db

@router.delete("/{expense_id}")
@limiter.limit("20/minute")
def delete_expense(
    request: Request,
    expense_id: int,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    """
    Delete an expense.

    Permissions:
    - Admin users can delete any expense.
    - Regular users can only delete expenses for their own vehicles.
    """

    expense = (
        db.query(Expense)
        .options(joinedload(Expense.vehicle))
        .filter(Expense.id == expense_id)
        .first()
    )

    if expense is None:
        logger.warning(
            "delete denied: expense %s does not exist (user %s)",
            expense_id,
            access["user"].id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this expense",
        )

    if expense.vehicle is None:
        logger.warning(
            "delete denied: expense %s has no vehicle", expense_id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this expense",
        )

    # Authorization
    if access["user"].role == "customer":
        logger.warning(
            "delete denied: user %s is a customer (expense %s)",
            access["user"].id,
            expense_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this expense",
        )

    if access["user"].role == "mechanic":
        owner = (
            db.query(User)
            .filter(User.id == expense.vehicle.user_id)
            .first()
        )

        if owner is None or owner.role != "customer":
            logger.warning(
                "delete denied: vehicle %s has no customer owner "
                "(mechanic %s)",
                expense.vehicle_id,
                access["user"].id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this expense",
            )

    # The expense stops changing once the record it lives on left
    # "in_progress".
    if expense.maintenance_record_id is not None:
        record = (
            db.query(MaintenanceRecord)
            .filter(
                MaintenanceRecord.id == expense.maintenance_record_id
            )
            .first()
        )

        if record is not None and record.status != "in_progress":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only records in progress can be modified",
            )

# admin → can delete any expense

    db.delete(expense)
    db.commit()

    return {"message": "Expense deleted successfully"}

