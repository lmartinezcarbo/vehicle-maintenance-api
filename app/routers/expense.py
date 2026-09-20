from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.schemas import ExpenseCreate, ExpenseResponse, ExpenseUpdate
from app.models.expense import Expense
from app.models.vehicle import Vehicle
from app.models.maintenance_record import MaintenanceRecord
from app.core.dependencies import get_access_user
from app.core.query_params import get_sort_params, SortOrder


class ExpenseSearchField(str, Enum):
    category = "category"
    description = "description"


router = APIRouter(
    prefix="/expenses",
    tags=["Expenses"],
)


@router.post("/", response_model=ExpenseResponse)
def create_expense(
    expense: ExpenseCreate,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create an expense for this vehicle",
        )

    # Authorization: regular users can only use their own vehicle
    if not access["is_admin"] and vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create an expense for this vehicle",
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
    if not access["is_admin"]:
        query = query.filter(
            Vehicle.user_id == access["user"].id
        )

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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this expense",
        )

    # Authorization
    if not access["is_admin"] and expense.vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this expense",
        )

    return expense


@router.patch("/{expense_id}", response_model=ExpenseResponse)
def update_expense(
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this expense",
        )

    # ---------------------------------------------------------
    # AUTHORIZATION OF CURRENT EXPENSE
    # ---------------------------------------------------------

    if not access["is_admin"] and expense_db.vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this expense",
        )

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
    # APPLY UPDATE
    # ---------------------------------------------------------

    for field, value in update_data.items():
        setattr(expense_db, field, value)

    db.commit()
    db.refresh(expense_db)

    return expense_db


@router.delete("/{expense_id}")
def delete_expense(
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this expense",
        )

    # Authorization
    if not access["is_admin"] and expense.vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this expense",
        )

    db.delete(expense)
    db.commit()

    return {"message": "Expense deleted successfully"}

