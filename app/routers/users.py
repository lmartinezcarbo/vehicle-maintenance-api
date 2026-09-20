from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from enum import Enum
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.security import hash_password, verify_password, create_access_token
from app.schemas.user import UserCreate, UserResponse, UserUpdate, UserPut, RefreshTokenRequest
from app.database import get_db
from app.models.user import User
from app.core.dependencies import get_access_user
from app.core.query_params import get_sort_params, SortOrder
from app.models.refresh_token import RefreshToken
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    verify_password,
    verify_refresh_token,
)
from app.core.rate_limit import limiter

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


class UserSearchField(str, Enum):
    name = "name"
    email = "email"

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def create_user(
    request: Request,
    user: UserCreate,
    db: Session = Depends(get_db)
):
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

@router.get("/me", response_model=UserResponse)
def get_current_user_profile(
    access=Depends(get_access_user)
):
    return access["user"]

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
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this user"
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
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user"
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

@router.put("/{user_id}", response_model=UserResponse)
def replace_user(
    user_id: int,
    user_data: UserPut,
    db: Session = Depends(get_db),
    access=Depends(get_access_user),
):
    user_db = db.query(User).filter(User.id == user_id).first()

    if user_db is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to replace this user"
        )

    if not access["is_admin"] and user_db.id != access["user"].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to replace this user"
        )

    user_db.name = user_data.name
    user_db.email = user_data.email
    user_db.password_hash = hash_password(user_data.password)

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
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this user"
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
@limiter.limit("5/minute")
def login(
    request: Request,
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

    refresh_token = create_refresh_token()
    refresh_token_hash = hash_refresh_token(refresh_token)

    refresh_token_record = RefreshToken(
        user_id=user.id,
        token_hash=refresh_token_hash,
        family_id=uuid4(),
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )

    db.add(refresh_token_record)
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.post("/refresh")
@limiter.limit("10/minute")
def refresh_token(
    request: Request,
    data: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    refresh_tokens = db.query(RefreshToken).all()

    refresh_token_record = None

    for token_record in refresh_tokens:
        if verify_refresh_token(
            data.refresh_token,
            token_record.token_hash,
        ):
            refresh_token_record = token_record
            break

    if (
        refresh_token_record is not None
        and refresh_token_record.revoked
        and refresh_token_record.revoked_reason == "rotation"
    ):
        db.query(RefreshToken).filter(
            RefreshToken.family_id == refresh_token_record.family_id
        ).update(
            {
                RefreshToken.revoked: True,
                RefreshToken.revoked_reason: "reuse",
            },
            synchronize_session=False,
        )

        db.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token reuse detected",
        )

    if (
        refresh_token_record is not None
        and refresh_token_record.revoked
        and refresh_token_record.revoked_reason == "logout"
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked",
        )

    if refresh_token_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if refresh_token_record.expires_at <= datetime.now(timezone.utc):
        refresh_token_record.revoked = True
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )

    refresh_token_record.revoked = True
    refresh_token_record.revoked_reason = "rotation"
    db.commit()

    new_refresh_token = create_refresh_token()
    new_refresh_token_hash = hash_refresh_token(new_refresh_token)

    new_refresh_token_record = RefreshToken(
        user_id=refresh_token_record.user_id,
        token_hash=new_refresh_token_hash,
        family_id=refresh_token_record.family_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )

    db.add(new_refresh_token_record)
    db.commit()

    access_token = create_access_token({
        "sub": str(refresh_token_record.user_id),
    })

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }

@router.post("/logout")
@limiter.limit("10/minute")
def logout(
    request: Request,
    data: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    refresh_tokens = db.query(RefreshToken).all()

    refresh_token_record = None

    for token_record in refresh_tokens:
        if verify_refresh_token(
            data.refresh_token,
            token_record.token_hash,
        ):
            refresh_token_record = token_record
            break

    if refresh_token_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    refresh_token_record.revoked = True
    refresh_token_record.revoked_reason = "logout"
    db.commit()

    return {
        "message": "Logout successful"
    }