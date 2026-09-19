from enum import Enum

from fastapi import Query


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


def get_sort_params(
    sort_by: str | None = Query(default=None),
    order: SortOrder = Query(default=SortOrder.asc),
):
    return {
        "sort_by": sort_by,
        "order": order,
    }