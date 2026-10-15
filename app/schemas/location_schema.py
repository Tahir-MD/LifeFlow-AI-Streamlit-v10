from typing import Optional

from pydantic import BaseModel, field_validator

from app.utils.validators import validate_place_text


class LocationIn(BaseModel):
    """Where someone lives / where a hospital is, in plain words. Coordinates are optional: the map
    fills them in automatically, and the server looks them up from the words if they are missing."""
    village: Optional[str] = None
    area: str
    city: str
    state: Optional[str] = None
    country: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("village", "state")
    @classmethod
    def _optional_place(cls, v, info):
        return validate_place_text(v, info.field_name.capitalize(), required=False)

    @field_validator("area", "city", "country")
    @classmethod
    def _required_place(cls, v, info):
        return validate_place_text(v, info.field_name.capitalize(), required=True)

    @field_validator("latitude")
    @classmethod
    def _lat(cls, v):
        if v is not None and not -90 <= v <= 90:
            raise ValueError("Map position is not valid.")
        return v

    @field_validator("longitude")
    @classmethod
    def _lng(cls, v):
        if v is not None and not -180 <= v <= 180:
            raise ValueError("Map position is not valid.")
        return v


class LocationOut(BaseModel):
    village: Optional[str] = None
    area: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
