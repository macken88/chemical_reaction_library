from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, Table, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import Base

reaction_tags = Table(
    "reaction_tags",
    Base.metadata,
    Column("reaction_id", ForeignKey("reactions.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Reaction(Base):
    __tablename__ = "reactions"
    __table_args__ = (CheckConstraint("validation_mode IN ('FULL', 'REPEAT_UNIT', 'LOCAL', 'LIMITED')", name="ck_reaction_validation_mode"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reaction_smiles: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    editor_structure_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_mode: Mapped[str] = mapped_column(String(20), default="LIMITED")
    reagents_text: Mapped[str] = mapped_column(Text, default="")
    process_text: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    warning_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    components: Mapped[list["Component"]] = relationship(back_populates="reaction", cascade="all, delete-orphan")
    tags: Mapped[list["Tag"]] = relationship(secondary=reaction_tags, back_populates="reactions")
    validation_result: Mapped["ValidationResult | None"] = relationship(back_populates="reaction", cascade="all, delete-orphan", uselist=False)


class Component(Base):
    __tablename__ = "components"
    __table_args__ = (
        CheckConstraint("role IN ('REACTANT', 'PRODUCT', 'CONDITION')", name="ck_component_role"),
        CheckConstraint("coefficient = 'n' OR CAST(coefficient AS REAL) > 0", name="ck_component_coefficient"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reaction_id: Mapped[int] = mapped_column(ForeignKey("reactions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(12), index=True)
    coefficient: Mapped[str] = mapped_column(String(30), default="1")
    structure: Mapped[str] = mapped_column(Text)
    canonical_smiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    reaction: Mapped[Reaction] = relationship(back_populates="components")


class ValidationResult(Base):
    __tablename__ = "validation_results"
    __table_args__ = (
        CheckConstraint("validation_mode IN ('FULL', 'REPEAT_UNIT', 'LOCAL', 'LIMITED')", name="ck_result_validation_mode"),
        CheckConstraint("representation_status IN ('PASS', 'WARNING', 'FAIL', 'NOT_EVALUABLE', 'INFO')", name="ck_result_representation_status"),
        CheckConstraint("structure_status IN ('PASS', 'WARNING', 'FAIL', 'NOT_EVALUABLE', 'INFO')", name="ck_result_structure_status"),
        CheckConstraint("element_balance_status IN ('PASS', 'WARNING', 'FAIL', 'NOT_EVALUABLE', 'INFO')", name="ck_result_element_status"),
        CheckConstraint("charge_balance_status IN ('PASS', 'WARNING', 'FAIL', 'NOT_EVALUABLE', 'INFO')", name="ck_result_charge_status"),
        CheckConstraint("mapping_status IN ('PASS', 'WARNING', 'FAIL', 'NOT_EVALUABLE', 'INFO')", name="ck_result_mapping_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reaction_id: Mapped[int] = mapped_column(ForeignKey("reactions.id", ondelete="CASCADE"), unique=True)
    validation_mode: Mapped[str] = mapped_column(String(20))
    representation_status: Mapped[str] = mapped_column(String(20))
    structure_status: Mapped[str] = mapped_column(String(20))
    element_balance_status: Mapped[str] = mapped_column(String(20))
    charge_balance_status: Mapped[str] = mapped_column(String(20))
    mapping_status: Mapped[str] = mapped_column(String(20))
    bond_change_summary: Mapped[str] = mapped_column(Text, default="")
    element_difference_json: Mapped[str] = mapped_column(Text, default="{}")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    validator_version: Mapped[str] = mapped_column(String(30))
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reaction: Mapped[Reaction] = relationship(back_populates="validation_result")


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("name", name="uq_tag_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    reactions: Mapped[list[Reaction]] = relationship(secondary=reaction_tags, back_populates="tags")


class SchemaMetadata(Base):
    __tablename__ = "schema_metadata"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(100))
