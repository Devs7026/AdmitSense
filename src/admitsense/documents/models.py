from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

ExtractionStatus = Literal[
    "pending",
    "extracted",
    "partial",
    "unreadable",
    "error",
]


class ExtractedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(gt=0, description="1-based physical PDF page number")
    text: str = Field(description="Extracted raw text with normalized whitespace")
    is_blank: bool = Field(default=False, description="True if page contains no readable text")
    character_count: int = Field(default=0, ge=0, description="Number of text characters on page")

    @model_validator(mode="before")
    @classmethod
    def set_defaults(cls, data: Any) -> Any:
        if isinstance(data, dict):
            text = data.get("text", "")
            if "character_count" not in data or data.get("character_count") is None:
                data["character_count"] = len(text)
            if "is_blank" not in data or data.get("is_blank") is None:
                data["is_blank"] = len(text.strip()) == 0
        return data


class DocumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    version: str = Field(default="v1", pattern=r"^v\d+$")
    sha256: str = Field(min_length=64, max_length=64)
    evidence_type: str = Field(default="other")
    uploaded_at: str
    extraction_status: ExtractionStatus = "pending"
    total_pages: int = Field(default=0, ge=0)
    file_path: str = ""
    pages: list[ExtractedPage] = Field(default_factory=list)
    error_message: str | None = None


class UploadValidationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_file_size_bytes: int = 10 * 1024 * 1024  # 10 MB limit
    max_pages: int = 50  # 50 pages limit
    allowed_extensions: tuple[str, ...] = (".pdf",)
