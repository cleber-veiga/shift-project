"""
Pydantic schemas para InputModel (modelos de entrada).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ─── Enums ────────────────────────────────────────────────────────────────────

class ColumnType(str, Enum):
    text = "text"
    number = "number"
    integer = "integer"
    date = "date"
    datetime = "datetime"
    boolean = "boolean"


class FileType(str, Enum):
    excel = "excel"
    csv = "csv"
    data = "data"  # Tabela interna — sem arquivo, apenas dados cadastrados manualmente


# ─── Schema definition (JSONB) ───────────────────────────────────────────────

class ColumnDef(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: ColumnType = ColumnType.text
    required: bool = False


class SheetDef(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    columns: list[ColumnDef] = Field(..., min_length=1)


class InputModelSchema(BaseModel):
    sheets: list[SheetDef] = Field(..., min_length=1)


# ─── Create / Update / Response ──────────────────────────────────────────────

class InputModelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    file_type: FileType
    schema_def: InputModelSchema

    @model_validator(mode="after")
    def validate_csv_single_sheet(self) -> "InputModelCreate":
        if self.file_type in (FileType.csv, FileType.data) and len(self.schema_def.sheets) != 1:
            raise ValueError("Modelos CSV e Dados devem ter exatamente uma aba.")
        return self


class InputModelUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    file_type: FileType | None = None
    schema_def: InputModelSchema | None = None

    @model_validator(mode="after")
    def validate_csv_single_sheet(self) -> "InputModelUpdate":
        if (
            self.file_type in (FileType.csv, FileType.data)
            and self.schema_def is not None
            and len(self.schema_def.sheets) != 1
        ):
            raise ValueError("Modelos CSV e Dados devem ter exatamente uma aba.")
        return self


class InputModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    description: str | None
    file_type: str
    schema_def: dict
    created_by_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = []


# ─── Row data (tabela interna) ──────────────────────────────────────────────

class InputModelRowCreate(BaseModel):
    data: dict


class InputModelRowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    input_model_id: UUID
    row_order: int
    data: dict
    created_at: datetime


class InputModelRowBulkCreate(BaseModel):
    rows: list[dict] = Field(..., min_length=1)


class InputModelRowsResponse(BaseModel):
    total: int
    rows: list[InputModelRowResponse]
