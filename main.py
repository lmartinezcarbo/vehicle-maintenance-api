from fastapi import FastAPI


app = FastAPI( title="Vehicle Maintenance API",
               description="REST API for managing vehicle maintenance records",
               version="0.1.0",
               contact={
                "name": "Luis Gamal Martinez Carbo",
                "email": "lmartinezcarbo1994@example.com",
                },
            )

@app.get("/")
async def root():
    return {"message": "Welcome to the Vehicle Maintenance API!"}


