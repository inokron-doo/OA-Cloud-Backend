from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Literal
from datetime import datetime



class UserLogin(BaseModel):
    username: str = Field(examples=["alice"], description="Username or email address")
    password: str = Field(examples=["s3cr3t-passw0rd"])

class UserOut(BaseModel):
    id: int
    username: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    created_at: datetime
    is_admin: bool = False

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserOut

class TokenRefresh(BaseModel):
    refresh_token: str = Field(examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."])

class TokenValidate(BaseModel):
    token: str = Field(examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."])

class CalendarActivityCreate(BaseModel):
    title: str = Field(examples=["Morning feeding (25 kg)"])
    start_datetime: datetime = Field(examples=["2026-06-18T07:00:00Z"])
    end_datetime: datetime = Field(examples=["2026-06-18T08:00:00Z"])
    details: Optional[str] = Field(None, examples=["Silage mix, north trough"])
    responsible_agent: Optional[str] = Field(None, examples=["alice"])
    activity_type_id: str = Field(examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"])
    parent_activity_id: Optional[str] = Field(None, examples=[None])
    parcel_id: Optional[str] = Field(None, examples=[None])

class CalendarActivityResponse(BaseModel):
    id: str
    title: str
    start_datetime: datetime
    end_datetime: datetime
    details: Optional[str] = None
    responsible_agent: Optional[str] = None
    activity_type_id: str
    parent_activity_id: Optional[str] = None
    parcel_id: Optional[str] = None

class CalendarActivitiesBulkCreate(BaseModel):
    activities: List[CalendarActivityCreate]

class FeedingLocationCreate(BaseModel):
    name: str = Field(examples=["North trough"])

class FeedingLocationUpdate(BaseModel):
    name: Optional[str] = Field(None, examples=["North trough"])
    is_hidden: Optional[bool] = Field(None, examples=[False])

class FeedingScheduleCreate(BaseModel):
    barn_id: str = Field(examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"])
    feeding_location_id: str = Field(examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"])
    schedule_name: str = Field(examples=["Weekday morning feed"])
    days_of_week: List[int] = Field(
        examples=[[0, 1, 2, 3, 4]],
        description="Days of week, Monday=0 ... Sunday=6",
    )
    time_start: str = Field(
        examples=["06:30"],
        description="Start of the expected feeding window, 24-hour HH:MM",
    )
    time_end: str = Field(
        examples=["08:30"],
        description=(
            "End of the expected feeding window, 24-hour HH:MM. If earlier than "
            "time_start the window crosses midnight."
        ),
    )
    quantity_kg: Optional[float] = Field(None, examples=[25.0])
    notes: Optional[str] = Field(None, examples=["Silage mix"])

class FeedingScheduleUpdate(BaseModel):
    schedule_name: Optional[str] = Field(None, examples=["Weekday morning feed"])
    days_of_week: Optional[List[int]] = Field(None, examples=[[0, 1, 2, 3, 4]])
    time_start: Optional[str] = Field(None, examples=["06:30"])
    time_end: Optional[str] = Field(None, examples=["08:30"])
    quantity_kg: Optional[float] = Field(None, examples=[25.0])
    notes: Optional[str] = Field(None, examples=["Silage mix"])
    is_active: Optional[bool] = Field(None, examples=[True])

class FeedingScheduleResponse(BaseModel):
    id: str
    barn_id: str
    feeding_location_id: str
    schedule_name: str
    days_of_week: List[int]
    time_start: str
    time_end: str
    quantity_kg: Optional[float] = None
    notes: Optional[str] = None
    is_active: bool
    location_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ThresholdsUpdate(BaseModel):
    thresholds: Dict[str, Any] = Field(
        examples=[{"low_feed_percent": 20, "spoilage_feed_percent": 70}],
        description="Map of threshold key -> value. Only included keys are changed.",
    )


class OneTimeFeedingCreate(BaseModel):
    barn_id: str = Field(examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"])
    feeding_location_id: str = Field(examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"])
    start_datetime: datetime = Field(examples=["2026-06-18T07:00:00Z"])
    end_datetime: Optional[datetime] = Field(None, examples=["2026-06-18T08:00:00Z"])
    quantity_kg: Optional[float] = Field(None, examples=[25.0])
    notes: Optional[str] = Field(None, examples=["Extra feed before heat wave"])
    title: Optional[str] = Field(None, examples=["One-time Feeding"])


class DeviceLinkRequest(BaseModel):
    device_eui: str = Field(examples=["A1B2C3D4E5F60718"])
    barn_id: str = Field(examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"])
    display_name: Optional[str] = Field(None, examples=["Feed silo sensor 1"])


class DeviceLocationMappingRequest(BaseModel):
    device_eui: str = Field(examples=["A1B2C3D4E5F60718"])
    barn_id: str = Field(examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"])
    incoming_feeding_location_name: str = Field(examples=["trough_north"])
    feeding_location_id: str = Field(examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"])


class DeviceBarnMappingRequest(BaseModel):
    device_eui: str = Field(examples=["A1B2C3D4E5F60718"])
    incoming_barn_name: str = Field(examples=["barn_1"])
    barn_id: str = Field(examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"])


class AnimalCreate(BaseModel):
    animal_name: str = Field(examples=["Bessie"])
    barn_id: str = Field(examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"])
    moohero_collar_unique_id: Optional[str] = Field(None, examples=["COLLAR-001"])
    feeding_location_id: Optional[str] = Field(None, examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"])
    animal_type: Optional[str] = Field(None, examples=["dairy_cow"])


class ActivityTypeCreate(BaseModel):
    name: str = Field(examples=["Vaccination"])
    description: str = Field("", examples=["Routine herd vaccination"])
    background_color: str = Field("#4CAF50", examples=["#4CAF50"])
    border_color: str = Field("#388E3C", examples=["#388E3C"])
    text_color: str = Field("#FFFFFF", examples=["#FFFFFF"])
    category: str = Field("farming", examples=["farming"])


class FeedLevelPredictRequest(BaseModel):
    barn_id: str = Field(examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"])
    feeding_location_id: Optional[str] = Field(
        None,
        examples=["7c9e6679-7425-40de-944b-e07fc1f90ae7"],
        description="Required in practice; a 400 is returned if omitted.",
    )
    horizon_hours: int = Field(24, ge=1, le=240, examples=[24])
    start_time: Optional[str] = Field(None, examples=["2026-06-17T06:00:00Z"])
    freq_minutes: Optional[int] = Field(None, examples=[60])
