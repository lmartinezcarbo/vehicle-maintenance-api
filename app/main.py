from fastapi import FastAPI

from app.routers.users import router as users_router
from app.routers.vehicles import router as vehicles_router
from app.routers.maintenance_records import router as maintenance_records_router
from app.routers.part import router as part_router
from app.routers.maintenance_parts import router as maintenance_part_router
from app.routers.expense import router as expense_router



app = FastAPI( title="Vehicle Maintenance API",
               description="REST API for managing vehicle maintenance records",
               version="0.1.0",
               contact={
                "name": "Luis Gamal Martinez Carbo",
                "email": "lmartinezcarbo1994@example.com",
                },
            )

app.include_router(users_router)
app.include_router(vehicles_router)
app.include_router(maintenance_records_router)
app.include_router(part_router)
app.include_router(maintenance_part_router)
app.include_router(expense_router)


@app.get("/")
async def root():
    return {"message": "Welcome to the Vehicle Maintenance API!"}


