from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.routers.users import router as users_router
from app.routers.vehicles import router as vehicles_router
from app.routers.maintenance_records import router as maintenance_records_router
from app.routers.part import router as part_router
from app.routers.maintenance_parts import router as maintenance_part_router
from app.routers.expense import router as expense_router
from app.core.exception_handlers import general_exception_handler
from app.routers.health import router as health_router



app = FastAPI( title="Vehicle Maintenance API",
               description="REST API for managing vehicle maintenance records",
               version="0.1.0",
               contact={
                "name": "Luis Gamal Martinez Carbo",
                "email": "lmartinezcarbo1994@example.com",
                },
            )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users_router)
app.include_router(vehicles_router)
app.include_router(maintenance_records_router)
app.include_router(part_router)
app.include_router(maintenance_part_router)
app.include_router(expense_router)
app.add_exception_handler(Exception, general_exception_handler)
app.include_router(health_router)

logger = logging.getLogger(__name__)

logger.info("Application started")


@app.get("/")
async def root():
    return {"message": "Welcome to the Vehicle Maintenance API!"}


