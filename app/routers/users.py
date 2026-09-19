from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from enum import Enum

from app.core.security import hash_password, verify_password, create_access_token
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.database import get_db
from app.models.user import User
from app.core.dependencies import get_access_user
from app.core.query_params import get_sort_params, SortOrder

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


class UserSearchField(str, Enum):
    name = "name"
    email = "email"

@router.post("/", response_model=UserResponse)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    """
    Create a new user.
    - Anyone can create a new user
    - Email must be unique
    - Password is automatically hashed
    """
    existing_user = db.query(User).filter(User.email == user.email).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists"
        )

    new_user = User(
        name=user.name,
        email=user.email,
        password_hash=hash_password(user.password)
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


@router.get("/", response_model=list[UserResponse])
def get_users(
    name: str | None = None,
    search: str | None = None,
    search_by: UserSearchField = UserSearchField.name,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort_params = Depends(get_sort_params),
    db: Session = Depends(get_db),
    access = Depends(get_access_user)
):
    """
    Get users.
    - Admins can filter, paginate, and limit results
    - Regular users see only their own profile
    """
    if access["is_admin"]:
        query = db.query(User)

        if search:
            if search_by == UserSearchField.name:
                query = query.filter(
                    User.name.ilike(f"%{search}%")
                )
            else:
                query = query.filter(
                    User.email.ilike(f"%{search}%")
                )

        sort_columns = {
            "name": User.name,
            "email": User.email,
            "created_at": User.created_at,
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

        if name:
            query = query.filter(User.name == name)

        return query.offset(offset).limit(limit).all()

    return [access["user"]]

@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    access = Depends(get_access_user)
):
    """
    Get a specific user by ID.
    - Admins can access any user
    - Regular users can only access their own profile
    """
    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if not access["is_admin"] and access["user"].id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this user"
        )

    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user: UserUpdate,
    db: Session = Depends(get_db),
    access = Depends(get_access_user)
):
    """
    Update a user.
    - Admins can update any user
    - Regular users can only update their own profile
    - Password is automatically hashed if provided
    """
    user_db = db.query(User).filter(User.id == user_id).first()

    if user_db is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if not access["is_admin"] and access["user"].id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user"
        )

    update_data = user.model_dump(exclude_unset=True)

    if "password" in update_data:
        update_data["password_hash"] = hash_password(
            update_data.pop("password")
        )

    for field, value in update_data.items():
        setattr(user_db, field, value)

    db.commit()
    db.refresh(user_db)

    return user_db


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    access = Depends(get_access_user)
):
    """
    Delete a user.
    - Admins can delete any user
    - Regular users can only delete their own profile
    """
    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if not access["is_admin"] and access["user"].id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this user"
        )

    db.delete(user)
    db.commit()

    return


@router.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Authenticate a user and return an access token.
    - Email and password are required
    - Returns JWT token with user information
    """
    user = db.query(User).filter(User.email == form_data.username).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    access_token = create_access_token({
        "sub": str(user.id),
        "role": user.role,
    })

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }