from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ComponentRole(StrEnum):
    REACTANT = "REACTANT"
    PRODUCT = "PRODUCT"
    CONDITION = "CONDITION"


class ValidationMode(StrEnum):
    FULL = "FULL"
    REPEAT_UNIT = "REPEAT_UNIT"
    LOCAL = "LOCAL"
    LIMITED = "LIMITED"


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    NOT_EVALUABLE = "NOT_EVALUABLE"
    INFO = "INFO"


class ComponentDraft(BaseModel):
    role: ComponentRole
    structure: str = Field(min_length=1, description="SMILES or a retained editor/local structure representation")
    coefficient: str = "1"
    display_name: str | None = Field(default=None, max_length=300)

    @field_validator("coefficient", mode="before")
    @classmethod
    def normalize_coefficient(cls, value: object) -> str:
        text = str(value).strip()
        if text.lower() == "n":
            return "n"
        try:
            if float(text) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("coefficient must be a positive number or the single symbol n")
        return text


class ReactionDraft(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    reaction_smiles: str | None = None
    editor_structure_data: str | None = None
    components: list[ComponentDraft] = Field(min_length=1)
    reagents_text: str = ""
    process_text: str = ""
    notes: str = ""
    warning_reason: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        result: list[str] = []
        for tag in tags:
            clean = tag.strip()
            if not clean or len(clean) > 100:
                raise ValueError("tag must contain 1-100 characters")
            if clean not in result:
                result.append(clean)
        return result


class ParseRequest(BaseModel):
    content: str = Field(min_length=1)
    format: str = Field(default="auto", pattern="^(auto|reaction_smiles|rxn)$")


class ParseResponse(BaseModel):
    draft: ReactionDraft
    parse_warnings: list[str] = Field(default_factory=list)


class ValidationResponse(BaseModel):
    validation_mode: ValidationMode
    representation_status: CheckStatus
    structure_status: CheckStatus
    element_balance_status: CheckStatus
    charge_balance_status: CheckStatus
    mapping_status: CheckStatus
    bond_change_status: CheckStatus
    bond_change_summary: str
    element_difference: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    validator_version: str
    validated_at: datetime
    scope_note: str = "Mechanical validation does not guarantee that a reaction is chemically feasible."
    duplicate_reaction_ids: list[int] = Field(default_factory=list)


class ReactionResponse(ReactionDraft):
    model_config = ConfigDict(from_attributes=True)
    id: int
    validation_mode: ValidationMode
    validation: ValidationResponse | None = None
    created_at: datetime
    updated_at: datetime


class ReactionListResponse(BaseModel):
    items: list[ReactionResponse]
    total: int


class SearchRequest(BaseModel):
    query: str | None = None
    reagent: str | None = None
    tag: str | None = None
    reactant: str | None = None
    product: str | None = None
    validation_status: CheckStatus | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class SubstructureSearchRequest(BaseModel):
    structure: str = Field(min_length=1, description="SMILES or SMARTS generated from a structure editor")
    target: str = Field(default="BOTH", pattern="^(REACTANT|PRODUCT|BOTH)$")


class AICopyResponse(BaseModel):
    text: str


class BackupResponse(BaseModel):
    backup_token: str
    filename: str
    schema_version: str


class RestoreRequest(BaseModel):
    backup_token: str | None = Field(default=None, min_length=20, description="Token returned by /api/backup")
    backup_base64: str | None = Field(default=None, description="Base64-encoded downloaded SQLite backup")
    confirmation_token: str = Field(description="Must exactly be RESTORE_LIBRARY")

    @model_validator(mode="after")
    def require_backup_source(self) -> "RestoreRequest":
        if bool(self.backup_token) == bool(self.backup_base64):
            raise ValueError("provide exactly one of backup_token or backup_base64")
        return self

    @field_validator("confirmation_token")
    @classmethod
    def check_confirmation(cls, value: str) -> str:
        if value != "RESTORE_LIBRARY":
            raise ValueError("confirmation_token must exactly be RESTORE_LIBRARY")
        return value


class RestoreResponse(BaseModel):
    restored: bool
    schema_version: str


class SchemaVersionResponse(BaseModel):
    schema_version: str


class ErrorDetail(BaseModel):
    detail: str
