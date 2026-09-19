from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.schemas import ExpenseCreate, ExpenseResponse, ExpenseUpdate
from app.models.expense import Expense
from app.models.vehicle import Vehicle
from app.models.maintenance_record import MaintenanceRecord
from app.core.dependencies import get_access_user


router = APIRouter(
    prefix="/expenses",
    tags=["Expenses"],
)


@router.post("/", response_model=ExpenseResponse)
def create_expense(
    expense: ExpenseCreate,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Create a new expense for a vehicle.
    
    - **vehicle_id**: ID of the vehicle the expense belongs to
    - **category**: Category of the expense
    - **amount**: Amount spent (must be positive)
    - **description**: Optional description of the expense
    - **expense_date**: Date when the expense occurred
    - **maintenance_record_id**: Optional ID of associated maintenance record
    
    **Permissions**:
    - Admin users can create expenses for any vehicle
    - Regular users can only create expenses for their own vehicles
    """
    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.id == expense.vehicle_id)
        .first()
    )

    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle not found"
        )

    if not access["is_admin"] and vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to create an expense for this vehicle"
        )

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
                detail="Maintenance record not found"
            )

        if maintenance_record.vehicle_id != expense.vehicle_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maintenance record does not belong to this vehicle"
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
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Get all expenses.
    
    **Permissions**:
    - Admin users can see all expenses
    - Regular users can only see expenses for their own vehicles
    
    Returns:
    - List of expense objects
    """
    query = (
        db.query(Expense)
        .options(joinedload(Expense.vehicle))
    )

    if not access["is_admin"]:
        query = query.join(Vehicle).filter(
            Vehicle.user_id == access["user"].id
        )

    expenses = query.all()

    return expenses


@router.get("/{expense_id}", response_model=ExpenseResponse)
def get_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Get a specific expense by ID.
    
    **Permissions**:
    - Admin users can access any expense
    - Regular users can only access expenses for their own vehicles
    
    Returns:
    - The expense object
    """
    expense = (
        db.query(Expense)
        .options(joinedload(Expense.vehicle))
        .filter(Expense.id == expense_id)
        .first()
    )

    if expense is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found"
        )

    if not access["is_admin"] and expense.vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this expense"
        )

    return expense


@router.patch("/{expense_id}", response_model=ExpenseResponse)
def update_expense(
    expense_id: int,
    expense: ExpenseUpdate,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Update an existing expense.
    
    **Permissions**:
    - Admin users can update any expense
    - Regular users can only update expenses for their own vehicles
    
    Returns:
    - The updated expense object
    """
    expense_db = (
        db.query(Expense)
        .options(joinedload(Expense.vehicle))
        .filter(Expense.id == expense_id)
        .first()
    )

    if expense_db is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found"
        )

    if not access["is_admin"] and expense_db.vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this expense"
        )

    update_data = expense.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(expense_db, field, value)

    db.commit()
    db.refresh(expense_db)

    return expense_db


@router.delete("/{expense_id}")
def delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    access = Depends(get_access_user),
):
    """
    Delete an expense.
    
    **Permissions**:
    - Admin users can delete any expense
    - Regular users can only delete expenses for their own vehicles
    
    Returns:
    - Success message
    """
    expense = (
        db.query(Expense)
        .options(joinedload(Expense.vehicle))
        .filter(Expense.id == expense_id)
        .first()
    )

    if expense is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found"
        )

    if not access["is_admin"] and expense.vehicle.user_id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this expense"
        )

    db.delete(expense)
    db.commit()

    return {"message": "Expense deleted successfully"}