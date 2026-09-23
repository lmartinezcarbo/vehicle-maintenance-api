from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from enum import Enum
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from slowapi import Limiter
from slowapi.util import get_remote_address

import logging

from app.database import get_db
from app.models.user import User
from app.core.dependencies import get_access_user, require_admin, get_current_user
from app.core.query_params import get_sort_params, SortOrder
from app.models.refresh_token import RefreshToken
from app.core.rate_limit import limiter
from app.services.email import send_email
from app.services.one_time_code import create_one_time_code, verify_one_time_code
from app.schemas.user import (
    UserCreate, UserResponse,
    UserUpdate, UserPut,
    RefreshTokenRequest,
    EmailVerificationRequest,
    TwoFactorVerificationRequest,
    ResendTwoFactorRequest,
    ResendVerificationRequest,
    UserRoleUpdate,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    verify_password,
    verify_refresh_token,
    hash_password,
)


router = APIRouter(
    prefix="/users",
    tags=["Users"],
)

logger = logging.getLogger(__name__)

class UserSearchField(str, Enum):
    name = "name"
    email = "email"

class UserRole(str, Enum):
    customer = "customer"
    mechanic = "mechanic"
    admin = "admin"

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

    verification_code = create_one_time_code(
    db=db,
    user_id=new_user.id,
    purpose="email_verification",
)

    try:
        send_email(
            to_email=new_user.email,
            subject="Verify your email",
            html_content=f"""
                <h1>Verify your email</h1>
                <p>Hello {new_user.name},</p>
                <p>Your verification code is:</p>
                <h2>{verification_code}</h2>
                <p>This code expires in 10 minutes.</p>
            """,
        )
    except Exception:
        logger.exception(
            "User created successfully, but verification email could not be sent to %s",
            new_user.email,
        )

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

@router.patch("/{user_id}/role", response_model=UserResponse)
def update_user_role(
    role_data: UserRoleUpdate,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if user.id == current_user.id and role_data.role != UserRole.admin.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin cannot remove their own admin role"
        )

    user.role = role_data.role

    db.commit()
    db.refresh(user)

    return user

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
    Update a user's profile.
    - Admins can update any user
    - Regular users can only update their own profile
    - Password changes are handled by a dedicated endpoint
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

    """
    Replace a user's profile.
    - Admins can replace any user
    - Regular users can only replace their own profile
    - Password changes are handled by a dedicated endpoint
    """
    
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

    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email must be verified before login"
        )

    two_factor_code = create_one_time_code(
        db=db,
        user_id=user.id,
        purpose="two_factor",
    )

    try:
        send_email(
            to_email=user.email,
            subject="Your 2FA verification code",
            html_content=f"""
                <h1>Two-factor authentication</h1>
                <p>Hello {user.name},</p>
                <p>Your verification code is:</p>
                <h2>{two_factor_code}</h2>
                <p>This code expires in 10 minutes.</p>
            """,
        )
    except Exception:
        logger.exception(
            "2FA code generated, but email could not be sent to %s",
            user.email,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to send verification code",
        )

    return {
        "message": "Two-factor authentication code sent",
        "requires_2fa": True,
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

@router.post("/forgot-password")
@limiter.limit("3/minute")
def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    """
    Generate and send a password reset code.
    """

    user = db.query(User).filter(User.email == data.email).first()

    if user is None:
        return {
            "message": (
                "If the account exists, "
                "a password reset code has been sent"
            )
        }

    reset_code = create_one_time_code(
        db=db,
        user_id=user.id,
        purpose="password_reset",
    )

    try:
        send_email(
            to_email=user.email,
            subject="Reset your password",
            html_content=f"""
                <h1>Password reset</h1>
                <p>Hello {user.name},</p>
                <p>Your password reset code is:</p>
                <h2>{reset_code}</h2>
                <p>This code expires in 10 minutes.</p>
            """,
        )
    except Exception:
        logger.exception(
            "Password reset email could not be sent to %s",
            user.email,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to send password reset code",
        )

    return {
        "message": (
            "If the account exists, "
            "a password reset code has been sent"
        )
    }

@router.post("/reset-password")
@limiter.limit("5/minute")
def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """
    Reset a user's password using a one-time code.
    """

    user = db.query(User).filter(User.email == data.email).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid password reset request",
        )

    code_valid = verify_one_time_code(
        db=db,
        user_id=user.id,
        purpose="password_reset",
        code=data.code,
    )

    if not code_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset code",
        )

    user.password_hash = hash_password(data.new_password)

    db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked.is_(False),
    ).update(
        {
            RefreshToken.revoked: True,
            RefreshToken.revoked_reason: "password_reset",
        },
        synchronize_session=False,
    )

    db.commit()

    return {
        "message": "Password reset successful"
    }

@router.post("/verify-email")
@limiter.limit("5/minute")
def verify_email(
    request: Request,
    data: EmailVerificationRequest,
    db: Session = Depends(get_db),
):
    """
    Verify a user's email address using a one-time verification code.
    """

    user = db.query(User).filter(User.email == data.email).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification request",
        )

    if user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already verified",
        )

    valid = verify_one_time_code(
        db=db,
        user_id=user.id,
        purpose="email_verification",
        code=data.code,
    )

    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code",
        )

    user.email_verified = True
    db.commit()

    return {
        "message": "Email verified successfully"
    }

@router.post("/verify-2fa")
@limiter.limit("5/minute")
def verify_2fa(
    request: Request,
    data: TwoFactorVerificationRequest,
    db: Session = Depends(get_db),
):
    """
    Verify a two-factor authentication code and issue access tokens.
    """

    user = db.query(User).filter(User.email == data.email).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification request",
        )

    valid = verify_one_time_code(
        db=db,
        user_id=user.id,
        purpose="two_factor",
        code=data.code,
    )

    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code",
        )

    access_token = create_access_token({
        "sub": str(user.id),
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
        "token_type": "bearer",
    }

@router.post("/resend-2fa")
@limiter.limit("3/minute")
def resend_2fa(
    request: Request,
    data: ResendTwoFactorRequest,
    db: Session = Depends(get_db),
):
    """
    Generate and send a new two-factor authentication code.
    """

    user = db.query(User).filter(User.email == data.email).first()

    if user is None or not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to resend verification code",
        )

    two_factor_code = create_one_time_code(
        db=db,
        user_id=user.id,
        purpose="two_factor",
    )

    try:
        send_email(
            to_email=user.email,
            subject="Your new 2FA verification code",
            html_content=f"""
                <h1>Two-factor authentication</h1>
                <p>Hello {user.name},</p>
                <p>Your new verification code is:</p>
                <h2>{two_factor_code}</h2>
                <p>This code expires in 10 minutes.</p>
            """,
        )
    except Exception:
        logger.exception(
            "2FA resend email could not be sent to %s",
            user.email,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to send verification code",
        )

    return {
        "message": "Two-factor authentication code sent",
        "requires_2fa": True,
    }

@router.post("/resend-verification")
@limiter.limit("3/minute")
def resend_verification(
    request: Request,
    data: ResendVerificationRequest,
    db: Session = Depends(get_db),
):
    """
    Generate and send a new email verification code.
    """

    user = db.query(User).filter(User.email == data.email).first()

    if user is None or user.email_verified:
        return {
            "message": (
                "If the account exists and is not verified, "
                "a verification code has been sent"
            )
        }

    verification_code = create_one_time_code(
        db=db,
        user_id=user.id,
        purpose="email_verification",
    )

    try:
        send_email(
            to_email=user.email,
            subject="Verify your email",
            html_content=f"""
                <h1>Verify your email</h1>
                <p>Hello {user.name},</p>
                <p>Your new verification code is:</p>
                <h2>{verification_code}</h2>
                <p>This code expires in 10 minutes.</p>
            """,
        )
    except Exception:
        logger.exception(
            "Verification email could not be sent to %s",
            user.email,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to send verification code",
        )

    return {
        "message": (
            "If the account exists and is not verified, "
            "a verification code has been sent"
        )
    }

@router.patch("/me/password")
@limiter.limit("5/minute")
def change_password(
    request: Request,
    data: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Change the authenticated user's password.
    """

    if not verify_password(
        data.current_password,
        current_user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if data.current_password == data.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password",
        )

    current_user.password_hash = hash_password(
        data.new_password
    )

    db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id,
        RefreshToken.revoked.is_(False),
    ).update(
        {
            RefreshToken.revoked: True,
            RefreshToken.revoked_reason: "password_change",
        },
        synchronize_session=False,
    )

    db.commit()

    return {
        "message": "Password changed successfully"
    }