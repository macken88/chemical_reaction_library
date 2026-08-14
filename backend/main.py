from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from backend.chemistry import canonical_smiles, component_matches_substructure, is_valid_substructure_query, parse_reaction, reaction_svg, validate_draft
from backend.db import Database, SCHEMA_REVISION, SCHEMA_VERSION, SchemaContractError, validate_sqlite_schema
from backend.models import Component, Reaction, SchemaMetadata, Tag, ValidationResult
from backend.schemas import (
    AICopyResponse,
    BackupResponse,
    CheckStatus,
    ComponentDraft,
    ParseRequest,
    ParseResponse,
    ReactionDraft,
    ReactionListResponse,
    ReactionResponse,
    RestoreRequest,
    RestoreResponse,
    SchemaVersionResponse,
    SearchRequest,
    SubstructureSearchRequest,
    ValidationResponse,
)

RESTORE_UPLOAD_MAX_BYTES = int(os.environ.get("REACTION_LIBRARY_RESTORE_UPLOAD_MAX_BYTES", str(64 * 1024 * 1024)))


def _draft_from_model(reaction: Reaction) -> ReactionDraft:
    return ReactionDraft(
        name=reaction.name,
        reaction_smiles=reaction.reaction_smiles,
        editor_structure_data=reaction.editor_structure_data,
        components=[
            ComponentDraft(role=component.role, structure=component.structure, coefficient=component.coefficient, display_name=component.display_name)
            for component in reaction.components
        ],
        reagents_text=reaction.reagents_text,
        process_text=reaction.process_text,
        notes=reaction.notes,
        warning_reason=reaction.warning_reason,
        tags=[tag.name for tag in reaction.tags],
    )


def _validation_from_model(result: ValidationResult | None) -> ValidationResponse | None:
    if result is None:
        return None
    raw = json.loads(result.element_difference_json)
    # The persisted form has only one status for extracted bond changes.  It is
    # INFO when mapping succeeded, otherwise NOT_EVALUABLE.
    bond_status = CheckStatus.INFO if result.mapping_status == CheckStatus.PASS else CheckStatus.NOT_EVALUABLE
    return ValidationResponse(
        validation_mode=result.validation_mode,
        representation_status=result.representation_status,
        structure_status=result.structure_status,
        element_balance_status=result.element_balance_status,
        charge_balance_status=result.charge_balance_status,
        mapping_status=result.mapping_status,
        bond_change_status=bond_status,
        bond_change_summary=result.bond_change_summary,
        element_difference=raw,
        warnings=json.loads(result.warnings_json),
        validator_version=result.validator_version,
        validated_at=result.validated_at,
    )


def _response_from_model(reaction: Reaction) -> ReactionResponse:
    draft = _draft_from_model(reaction)
    return ReactionResponse(
        **draft.model_dump(),
        id=reaction.id,
        validation_mode=reaction.validation_mode,
        validation=_validation_from_model(reaction.validation_result),
        created_at=reaction.created_at,
        updated_at=reaction.updated_at,
    )


def _set_tags(session: Session, reaction: Reaction, names: list[str]) -> None:
    tags: list[Tag] = []
    for name in names:
        tag = session.scalar(select(Tag).where(Tag.name == name))
        if tag is None:
            tag = Tag(name=name)
            session.add(tag)
        tags.append(tag)
    reaction.tags = tags


def _apply_draft(session: Session, reaction: Reaction, draft: ReactionDraft) -> None:
    reaction.name = draft.name
    reaction.reaction_smiles = draft.reaction_smiles
    reaction.editor_structure_data = draft.editor_structure_data
    reaction.reagents_text = draft.reagents_text
    reaction.process_text = draft.process_text
    reaction.notes = draft.notes
    reaction.warning_reason = draft.warning_reason
    reaction.components.clear()
    reaction.components.extend(
        Component(
            role=component.role.value,
            coefficient=component.coefficient,
            structure=component.structure,
            canonical_smiles=canonical_smiles(component.structure),
            display_name=component.display_name,
        )
        for component in draft.components
    )
    _set_tags(session, reaction, draft.tags)


def _persist_validation(reaction: Reaction, validation: ValidationResponse) -> None:
    reaction.validation_mode = validation.validation_mode.value
    result = reaction.validation_result
    if result is None:
        result = ValidationResult(reaction=reaction)
    result.validation_mode = validation.validation_mode.value
    result.representation_status = validation.representation_status.value
    result.structure_status = validation.structure_status.value
    result.element_balance_status = validation.element_balance_status.value
    result.charge_balance_status = validation.charge_balance_status.value
    result.mapping_status = validation.mapping_status.value
    result.bond_change_summary = validation.bond_change_summary
    result.element_difference_json = json.dumps(validation.element_difference, ensure_ascii=False, sort_keys=True)
    result.warnings_json = json.dumps(validation.warnings, ensure_ascii=False)
    result.validator_version = validation.validator_version
    result.validated_at = validation.validated_at


def _duplicate_ids(session: Session, reaction_smiles: str | None, excluded_id: int | None = None) -> list[int]:
    if not reaction_smiles:
        return []
    statement = select(Reaction.id).where(Reaction.reaction_smiles == reaction_smiles)
    if excluded_id is not None:
        statement = statement.where(Reaction.id != excluded_id)
    return list(session.scalars(statement))


def _validate_with_duplicates(session: Session, draft: ReactionDraft, excluded_id: int | None = None) -> ValidationResponse:
    result = validate_draft(draft)
    result.duplicate_reaction_ids = _duplicate_ids(session, draft.reaction_smiles, excluded_id)
    if result.duplicate_reaction_ids:
        result.warnings.append("An exact Reaction SMILES duplicate is already registered.")
    return result


def _load_reaction(session: Session, reaction_id: int) -> Reaction:
    statement = (
        select(Reaction)
        .where(Reaction.id == reaction_id)
        .options(selectinload(Reaction.components), selectinload(Reaction.tags), selectinload(Reaction.validation_result))
    )
    reaction = session.scalar(statement)
    if reaction is None:
        raise HTTPException(status_code=404, detail="Reaction not found")
    return reaction


def create_app(database_url: str | None = None, *, initialize: bool = True) -> FastAPI:
    database = Database(database_url)
    if initialize:
        database.create_all()
    app = FastAPI(title="Chemical Reaction Library API", version="0.1.0")
    app.state.database = database
    app.state.backups: dict[str, Path] = {}

    if not initialize:
        @app.on_event("startup")
        def initialize_default_database() -> None:
            database.create_all()

    def get_session():
        yield from database.session()

    @app.get("/api/schema-version", response_model=SchemaVersionResponse)
    def schema_version(session: Session = Depends(get_session)) -> SchemaVersionResponse:
        value = session.get(SchemaMetadata, "schema_revision")
        if value is None or value.value != SCHEMA_REVISION:
            raise HTTPException(status_code=503, detail="Database schema contract is not current")
        return SchemaVersionResponse(schema_version=value.value)

    @app.post("/api/reactions/parse", response_model=ParseResponse)
    def parse(request: ParseRequest) -> ParseResponse:
        try:
            return parse_reaction(request.content, request.format)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/reactions/validate", response_model=ValidationResponse)
    def validate(draft: ReactionDraft, session: Session = Depends(get_session)) -> ValidationResponse:
        return _validate_with_duplicates(session, draft)

    @app.post("/api/reactions", response_model=ReactionResponse, status_code=status.HTTP_201_CREATED)
    def create_reaction(draft: ReactionDraft, session: Session = Depends(get_session)) -> ReactionResponse:
        validation = _validate_with_duplicates(session, draft)
        if validation.representation_status is CheckStatus.FAIL:
            raise HTTPException(status_code=422, detail="Reaction has no storable structural representation")
        reaction = Reaction()
        _apply_draft(session, reaction, draft)
        _persist_validation(reaction, validation)
        session.add(reaction)
        session.commit()
        return _response_from_model(_load_reaction(session, reaction.id))

    @app.get("/api/reactions", response_model=ReactionListResponse)
    def list_reactions(session: Session = Depends(get_session), offset: int = 0, limit: int = 100) -> ReactionListResponse:
        statement = select(Reaction).options(selectinload(Reaction.components), selectinload(Reaction.tags), selectinload(Reaction.validation_result)).order_by(Reaction.updated_at.desc())
        reactions = list(session.scalars(statement.offset(max(offset, 0)).limit(min(max(limit, 1), 500))))
        total = len(list(session.scalars(select(Reaction.id))))
        return ReactionListResponse(items=[_response_from_model(item) for item in reactions], total=total)

    @app.post("/api/reactions/search", response_model=ReactionListResponse)
    def search(request: SearchRequest, session: Session = Depends(get_session)) -> ReactionListResponse:
        statement = select(Reaction).options(selectinload(Reaction.components), selectinload(Reaction.tags), selectinload(Reaction.validation_result))
        if request.tag:
            statement = statement.join(Reaction.tags).where(Tag.name == request.tag)
        if request.query:
            token = f"%{request.query}%"
            statement = statement.where(or_(Reaction.name.ilike(token), Reaction.reagents_text.ilike(token), Reaction.process_text.ilike(token), Reaction.notes.ilike(token)))
        if request.reagent:
            token = f"%{request.reagent}%"
            statement = statement.where(or_(Reaction.reagents_text.ilike(token), Reaction.components.any(Component.display_name.ilike(token))))
        if request.reactant or request.product:
            if request.reactant:
                canonical = canonical_smiles(request.reactant)
                if canonical is None:
                    raise HTTPException(status_code=422, detail="reactant must be valid SMILES")
                statement = statement.where(Reaction.components.any((Component.role == "REACTANT") & (Component.canonical_smiles == canonical)))
            if request.product:
                canonical = canonical_smiles(request.product)
                if canonical is None:
                    raise HTTPException(status_code=422, detail="product must be valid SMILES")
                statement = statement.where(Reaction.components.any((Component.role == "PRODUCT") & (Component.canonical_smiles == canonical)))
        if request.validation_status:
            value = request.validation_status.value
            statement = statement.join(Reaction.validation_result).where(
                or_(ValidationResult.structure_status == value, ValidationResult.element_balance_status == value, ValidationResult.charge_balance_status == value, ValidationResult.mapping_status == value)
            )
        items = list(session.scalars(statement.distinct().order_by(Reaction.updated_at.desc())))
        total = len(items)
        items = items[request.offset : request.offset + request.limit]
        return ReactionListResponse(items=[_response_from_model(item) for item in items], total=total)

    @app.post("/api/search/substructure", response_model=ReactionListResponse)
    def substructure_search(request: SubstructureSearchRequest, session: Session = Depends(get_session)) -> ReactionListResponse:
        if not is_valid_substructure_query(request.structure):
            raise HTTPException(status_code=422, detail="Search structure is not valid SMILES or SMARTS")
        statement = select(Reaction).options(selectinload(Reaction.components), selectinload(Reaction.tags), selectinload(Reaction.validation_result))
        matched: list[Reaction] = []
        allowed = {"REACTANT", "PRODUCT"} if request.target == "BOTH" else {request.target}
        for reaction in session.scalars(statement):
            if any(component.role in allowed and component_matches_substructure(component.structure, request.structure) for component in reaction.components):
                matched.append(reaction)
        return ReactionListResponse(items=[_response_from_model(item) for item in matched], total=len(matched))

    @app.post("/api/reactions/revalidate-all", response_model=ReactionListResponse)
    def revalidate_all(session: Session = Depends(get_session)) -> ReactionListResponse:
        statement = select(Reaction).options(selectinload(Reaction.components), selectinload(Reaction.tags), selectinload(Reaction.validation_result))
        reactions = list(session.scalars(statement))
        for reaction in reactions:
            _persist_validation(reaction, _validate_with_duplicates(session, _draft_from_model(reaction), reaction.id))
        session.commit()
        return ReactionListResponse(items=[_response_from_model(item) for item in reactions], total=len(reactions))

    @app.get("/api/reactions/{reaction_id}", response_model=ReactionResponse)
    def get_reaction(reaction_id: int, session: Session = Depends(get_session)) -> ReactionResponse:
        return _response_from_model(_load_reaction(session, reaction_id))

    @app.put("/api/reactions/{reaction_id}", response_model=ReactionResponse)
    def update_reaction(reaction_id: int, draft: ReactionDraft, session: Session = Depends(get_session)) -> ReactionResponse:
        reaction = _load_reaction(session, reaction_id)
        validation = _validate_with_duplicates(session, draft, reaction_id)
        if validation.representation_status is CheckStatus.FAIL:
            raise HTTPException(status_code=422, detail="Reaction has no storable structural representation")
        _apply_draft(session, reaction, draft)
        _persist_validation(reaction, validation)
        session.commit()
        return _response_from_model(_load_reaction(session, reaction_id))

    @app.delete("/api/reactions/{reaction_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_reaction(reaction_id: int, session: Session = Depends(get_session)) -> Response:
        session.delete(_load_reaction(session, reaction_id))
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/reactions/{reaction_id}/revalidate", response_model=ReactionResponse)
    def revalidate_one(reaction_id: int, session: Session = Depends(get_session)) -> ReactionResponse:
        reaction = _load_reaction(session, reaction_id)
        _persist_validation(reaction, _validate_with_duplicates(session, _draft_from_model(reaction), reaction_id))
        session.commit()
        return _response_from_model(_load_reaction(session, reaction_id))

    @app.get("/api/reactions/{reaction_id}/ai-copy", response_model=AICopyResponse)
    def ai_copy(reaction_id: int, session: Session = Depends(get_session)) -> AICopyResponse:
        reaction = _load_reaction(session, reaction_id)
        validation = _validation_from_model(reaction.validation_result)
        if reaction.reaction_smiles and validation and validation.representation_status is CheckStatus.PASS:
            representation = reaction.reaction_smiles
        else:
            reason = "; ".join(validation.warnings) if validation and validation.warnings else "Reaction SMILES cannot be generated from this retained representation."
            representation = f"Reaction SMILES unavailable: {reason}\nEditor structure data:\n{reaction.editor_structure_data or 'Unavailable'}"
        validation_lines = "Not yet run" if validation is None else "\n".join([
            f"- Coverage: {validation.validation_mode.value}",
            f"- Structure: {validation.structure_status.value}",
            f"- Element balance: {validation.element_balance_status.value}",
            f"- Charge balance: {validation.charge_balance_status.value}",
            f"- Atom mapping: {validation.mapping_status.value}",
            f"- Warnings: {'; '.join(validation.warnings) or 'None'}",
        ])
        return AICopyResponse(text=f"Reaction:\n{representation}\n\nReagents / Catalysts / Conditions:\n{reaction.reagents_text}\n\nProcess:\n{reaction.process_text}\n\nNotes:\n{reaction.notes}\n\nValidation:\n{validation_lines}")

    @app.get("/api/reactions/{reaction_id}/structure.svg", response_class=Response)
    def structure_svg(reaction_id: int, session: Session = Depends(get_session)) -> Response:
        reaction = _load_reaction(session, reaction_id)
        if not reaction.reaction_smiles:
            raise HTTPException(status_code=422, detail="This reaction has no verified Reaction SMILES; use retained editor structure data instead.")
        try:
            svg = reaction_svg(reaction.reaction_smiles)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Structure preview cannot be generated: {exc}") from exc
        return Response(content=svg, media_type="image/svg+xml")

    @app.post("/api/backup", response_model=BackupResponse)
    def backup() -> BackupResponse:
        with database.maintenance():
            backup_dir = database.file_path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            token = secrets.token_urlsafe(32)
            path = backup_dir / f"reaction-library-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{token[:8]}.sqlite3"
            database._backup_to(path)
            try:
                validate_sqlite_schema(path)
            except SchemaContractError as exc:
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=503, detail=f"Database backup health check failed: {exc}") from exc
        app.state.backups[token] = path
        return BackupResponse(backup_token=token, filename=path.name, schema_version=SCHEMA_VERSION)

    @app.get("/api/backup/{backup_token}", response_class=FileResponse)
    def download_backup(backup_token: str) -> FileResponse:
        source = app.state.backups.get(backup_token)
        if source is None or not source.is_file():
            raise HTTPException(status_code=404, detail="Unknown or unavailable backup token")
        return FileResponse(source, media_type="application/vnd.sqlite3", filename=source.name)

    @app.post("/api/restore", response_model=RestoreResponse)
    def restore(request: RestoreRequest) -> RestoreResponse:
        uploaded_source = False
        if request.backup_token:
            source = app.state.backups.get(request.backup_token)
            if source is None or not source.is_file():
                raise HTTPException(status_code=404, detail="Unknown or unavailable backup token")
        else:
            uploaded_source = True
            staging_dir = database.file_path.parent / ".restore-staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            source = staging_dir / f"restore-json-{secrets.token_hex(12)}.sqlite3"
            try:
                source.write_bytes(base64.b64decode(request.backup_base64 or "", validate=True))
            except (ValueError, OSError) as exc:
                source.unlink(missing_ok=True)
                raise HTTPException(status_code=422, detail="backup_base64 is not valid base64 data") from exc
        return _restore_from_file(source, uploaded_source)

    def _restore_from_file(source: Path, uploaded_source: bool) -> RestoreResponse:
        destination = database.file_path
        staging_dir = destination.parent / ".restore-staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        candidate = staging_dir / f"{destination.name}.restore-{secrets.token_hex(8)}.candidate"
        rollback = staging_dir / f"{destination.name}.restore-{secrets.token_hex(8)}.rollback"
        # A full copy is made before any engine is disposed or database path is
        # replaced.  The candidate itself is schema-validated in replace_with.
        try:
            shutil.copyfile(source, candidate)
        except OSError as exc:
            candidate.unlink(missing_ok=True)
            if uploaded_source:
                source.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail=f"Could not stage restore candidate: {exc}") from exc
        rollback_failed = False
        try:
            schema_version = database.replace_with(candidate, rollback)
        except (OSError, SchemaContractError) as exc:
            candidate.unlink(missing_ok=True)
            rollback_failed = "rollback failed" in str(exc)
            if uploaded_source:
                source.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=f"Restore rejected or rolled back: {exc}") from exc
        finally:
            if not rollback_failed:
                rollback.unlink(missing_ok=True)
        if uploaded_source:
            source.unlink(missing_ok=True)
        return RestoreResponse(restored=True, schema_version=schema_version)

    @app.post("/api/restore/upload", response_model=RestoreResponse)
    async def restore_upload(
        backup_file: UploadFile = File(...),
        confirmation_token: str = Form(...),
    ) -> RestoreResponse:
        if confirmation_token != "RESTORE_LIBRARY":
            raise HTTPException(status_code=422, detail="confirmation_token must exactly be RESTORE_LIBRARY")
        staging_dir = database.file_path.parent / ".restore-staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        source = staging_dir / f"restore-upload-{secrets.token_hex(12)}.sqlite3"
        written = 0
        try:
            with source.open("wb") as stream:
                while chunk := await backup_file.read(1024 * 1024):
                    written += len(chunk)
                    if written > RESTORE_UPLOAD_MAX_BYTES:
                        raise HTTPException(status_code=413, detail=f"Uploaded backup exceeds {RESTORE_UPLOAD_MAX_BYTES} bytes")
                    stream.write(chunk)
        except HTTPException:
            source.unlink(missing_ok=True)
            raise
        except OSError as exc:
            source.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail=f"Could not stage uploaded backup: {exc}") from exc
        finally:
            await backup_file.close()
        return await run_in_threadpool(_restore_from_file, source, True)

    return app


app = create_app(initialize=False)
