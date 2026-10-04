from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import logging

from app.routers.users import router as users_router
from app.routers.vehicles import router as vehicles_router
from app.routers.maintenance_records import router as maintenance_records_router
from app.routers.part import router as part_router
from app.routers.maintenance_parts import router as maintenance_part_router
from app.routers.expense import router as expense_router
from app.core.exception_handlers import general_exception_handler
from app.routers.health import router as health_router
from app.core.rate_limit import limiter
from app.core.config import settings
from app.routers.payments import router as payments_router



app = FastAPI( title="Vehicle Maintenance API",
               description="REST API for managing vehicle maintenance records",
               version="0.1.0",
               contact={
                "name": "Luis Gamal Martinez Carbo",
                "email": "lmartinezcarbo1994@example.com",
                },
            )

app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    _rate_limit_exceeded_handler,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(users_router)
app.include_router(vehicles_router)
app.include_router(maintenance_records_router)
app.include_router(part_router)
app.include_router(maintenance_part_router)
app.include_router(expense_router)
app.add_exception_handler(Exception, general_exception_handler)
app.include_router(health_router)
app.include_router(payments_router)

logger = logging.getLogger(__name__)

logger.info("Application started")


@app.get("/")
async def root():
    return {"message": "Welcome to the Vehicle Maintenance API!"}


