from sqlalchemy.orm import Query
from app.models.user import User
from app.models.vehicle import Vehicle


def filter_by_user_access(
    query: Query,
    current_user: User,
    user_column,
):
    if current_user.role != "admin":
        query = query.filter(user_column == current_user.id)

    return query