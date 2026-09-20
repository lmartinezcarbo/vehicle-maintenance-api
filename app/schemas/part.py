from pydantic import BaseModel


class PartCreate(BaseModel):
    name: str
    manufacturer: str
    part_number: str
    description: str | None = None


class PartResponse(BaseModel):
    id: int
    name: str
    manufacturer: str
    part_number: str
    description: str | None


class PartUpdate(BaseModel):
    name: str | None = None
    manufacturer: str | None = None
    part_number: str | None = None
    description: str | None = None

class PartPut(BaseModel):
    name: str
    manufacturer: str
    part_number: str
    description: str | None = None