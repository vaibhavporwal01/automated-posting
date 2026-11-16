"""Request and response models for the posting API."""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app.validation import MAX_MESSAGE_LENGTH, MessageValidationError, extract_links, validate_message


class PostRequest(BaseModel):
    """Body of POST /posting. Platforms are chosen by the server, so only the message is accepted."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "message": "Check out our latest business platform and grow your online visibility. https://example.com"
                }
            ]
        },
    )

    message: str = Field(
        ...,
        description=f"Text to publish. At most {MAX_MESSAGE_LENGTH} characters with exactly one http(s) link.",
    )

    @field_validator("message", mode="before")
    @classmethod
    def check_message(cls, value: object) -> str:
        if not isinstance(value, str):
            raise PydanticCustomError("invalid_type", "The message must be a string.")
        try:
            return validate_message(value)
        except MessageValidationError as exc:
            raise PydanticCustomError(exc.code, exc.message) from None

    @property
    def cta_link(self) -> str:
        return extract_links(self.message)[0]


class PlatformResult(BaseModel):
    platform: str = Field(..., description="Platform name")
    status: Literal["success", "failed"]
    posted_url: Optional[str] = Field(None, description="URL of the published content")
    public_access: bool = Field(False, description="True when the URL loads without logging in")
    date: Optional[str] = Field(None, description="Posting date, YYYY-MM-DD")
    time: Optional[str] = Field(None, description="Posting time, HH:MM:SS")
    error: Optional[str] = Field(None, description="Why the post failed, if it did")


class SkippedPlatform(BaseModel):
    platform: str
    reason: str


class PostingSummary(BaseModel):
    total: int
    succeeded: int
    failed: int
    duration_ms: int


class PostingResponse(BaseModel):
    success: bool = Field(..., description="True when at least one platform published the message")
    run_id: str = Field(..., description="Identifier that also appears in the server logs")
    timezone: str
    summary: PostingSummary
    results: List[PlatformResult]
    skipped: List[SkippedPlatform] = Field(
        default_factory=list, description="Platforms left out because their credentials are not set"
    )


class ErrorDetail(BaseModel):
    field: str
    code: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: List[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorBody


class PlatformInfo(BaseModel):
    key: str
    name: str
    configured: bool
    missing: List[str]
    docs_url: str
    enabled: bool
