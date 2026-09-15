from fastapi import FastAPI
from app.routers.users import router as users_router



app = FastAPI( title="Vehicle Maintenance API",
               description="REST API for managing vehicle maintenance records",
               version="0.1.0",
               contact={
                "name": "Luis Gamal Martinez Carbo",
                "email": "lmartinezcarbo1994@example.com",
                },
            )

app.include_router(users_router)

@app.get("/")
async def root():
    return {"message": "Welcome to the Vehicle Maintenance API!"}


