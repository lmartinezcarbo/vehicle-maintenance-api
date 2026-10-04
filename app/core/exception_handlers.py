import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError, IntegrityError

logger = logging.getLogger(__name__)

# Postgres SQLSTATE classes:
# https://www.postgresql.org/docs/current/errcodes-appendix.html
FOREIGN_KEY_VIOLATION = "23503"
UNIQUE_VIOLATION = "23505"
CHECK_VIOLATION = "23514"
NOT_NULL_VIOLATION = "23502"


def _sqlstate(exc):
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


async def database_error_handler(
    request: Request,
    exc: IntegrityError | DataError,
) -> JSONResponse:
    """Constraint violations are answers, not crashes.

    A foreign key or unique conflict means the world is not in the state
    the request assumed: 409. A CHECK violation or a value the column
    cannot hold means the payload could never be stored: 422. Anything
    else keeps the honest 500, with the real error in the log.
    """
    sqlstate = _sqlstate(exc)

    if sqlstate in (FOREIGN_KEY_VIOLATION, UNIQUE_VIOLATION):
        logger.warning(
            "%s %s -> 409 (%s): %s",
            request.method,
            request.url.path,
            sqlstate,
            exc.orig,
        )
        detail = (
            "The resource is still referenced by other data"
            if sqlstate == FOREIGN_KEY_VIOLATION
            else "That resource already exists"
        )
        return JSONResponse(status_code=409, content={"detail": detail})

    if isinstance(exc, IntegrityError) and sqlstate not in (
        CHECK_VIOLATION,
        NOT_NULL_VIOLATION,
    ):
        logger.error(
            "%s %s -> 500, unrecognized integrity error: %s",
            request.method,
            request.url.path,
            exc.orig,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    logger.warning(
        "%s %s -> 422 (%s): %s",
        request.method,
        request.url.path,
        sqlstate or type(exc).__name__,
        exc.orig if hasattr(exc, "orig") else exc,
    )
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Some of the submitted values are out of range"
        },
    )


async def general_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception(
        "Unhandled exception: %s %s",
        request.method,
        request.url.path,
    )

    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )