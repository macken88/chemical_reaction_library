import pytest
from pydantic import ValidationError
from rdkit.Chem import rdChemReactions

from backend.chemistry import parse_reaction, validate_draft
from backend.schemas import CheckStatus, ComponentDraft, ComponentRole, ReactionDraft, ValidationMode


def draft(*components: ComponentDraft, editor_structure_data: str | None = None) -> ReactionDraft:
    return ReactionDraft(components=list(components), editor_structure_data=editor_structure_data)


def test_parse_reaction_smiles_and_full_mapped_validation() -> None:
    parsed = parse_reaction("[CH3:1][CH3:2]>>[CH3:1][CH3:2]")
    result = validate_draft(parsed.draft)
    assert result.validation_mode is ValidationMode.FULL
    assert result.element_balance_status is CheckStatus.PASS
    assert result.charge_balance_status is CheckStatus.PASS
    assert result.mapping_status is CheckStatus.PASS


def test_parse_rxn_into_the_same_draft_flow() -> None:
    rxn = rdChemReactions.ReactionFromSmarts("CC>>CC")
    assert rxn is not None
    parsed = parse_reaction(rdChemReactions.ReactionToRxnBlock(rxn), "rxn")
    assert [component.role for component in parsed.draft.components] == [ComponentRole.REACTANT, ComponentRole.PRODUCT]
    # Query-RXN exports use an unspecified bond; coverage must remain LIMITED
    # rather than incorrectly certifying it as a finite FULL reaction.
    assert validate_draft(parsed.draft).validation_mode is ValidationMode.LIMITED


def test_unbalanced_and_charge_mismatch_are_warnings() -> None:
    result = validate_draft(draft(
        ComponentDraft(role=ComponentRole.REACTANT, structure="[Na+].[Cl-]"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="[Na+]"),
    ))
    assert result.element_balance_status is CheckStatus.WARNING
    assert result.charge_balance_status is CheckStatus.WARNING
    assert "Cl" in result.element_difference
    assert "charge" in result.element_difference


def test_conditions_do_not_affect_balances() -> None:
    result = validate_draft(draft(
        ComponentDraft(role=ComponentRole.REACTANT, structure="[CH3:1][CH3:2]"),
        ComponentDraft(role=ComponentRole.CONDITION, structure="O"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="[CH3:1][CH3:2]"),
    ))
    assert result.element_balance_status is CheckStatus.PASS


def test_unmapped_and_polymer_modes() -> None:
    unmapped = validate_draft(draft(
        ComponentDraft(role=ComponentRole.REACTANT, structure="CC"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="CC"),
    ))
    assert unmapped.mapping_status is CheckStatus.WARNING
    repeat = validate_draft(draft(
        ComponentDraft(role=ComponentRole.REACTANT, structure="C=C", coefficient="n"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="[*]CC[*]", coefficient="n"),
    ))
    assert repeat.validation_mode is ValidationMode.REPEAT_UNIT
    local = validate_draft(draft(
        ComponentDraft(role=ComponentRole.REACTANT, structure="[*]C"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="[*]CO"),
    ))
    assert local.validation_mode is ValidationMode.LOCAL
    assert local.element_balance_status is CheckStatus.NOT_EVALUABLE


def test_limited_retains_non_rdkit_structure_and_edge_structures() -> None:
    limited = validate_draft(draft(
        ComponentDraft(role=ComponentRole.REACTANT, structure="editor-only-polymer-sgroup"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="editor-only-polymer-sgroup"),
        editor_structure_data="retained Ketcher editor payload",
    ))
    assert limited.validation_mode is ValidationMode.LIMITED
    assert limited.structure_status is CheckStatus.NOT_EVALUABLE
    edge = validate_draft(draft(
        ComponentDraft(role=ComponentRole.REACTANT, structure="[2H]c1cc([NH3+])ccc1.[Cl-]"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="[2H]c1cc([NH3+])ccc1.[Cl-]"),
    ))
    assert edge.element_balance_status is CheckStatus.PASS


def test_draft_invariants_canonical_reaction_and_finite_coefficients() -> None:
    generated = ReactionDraft(components=[
        ComponentDraft(role=ComponentRole.REACTANT, structure="C(C)", coefficient="01.00"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="CC"),
    ])
    assert generated.reaction_smiles == "CC>>CC"
    assert generated.components[0].coefficient == "1"
    with pytest.raises(ValidationError, match="REACTANT"):
        ReactionDraft(components=[ComponentDraft(role=ComponentRole.PRODUCT, structure="CC")])
    with pytest.raises(ValidationError, match="LIMITED"):
        ReactionDraft(components=[
            ComponentDraft(role=ComponentRole.REACTANT, structure="editor-only"),
            ComponentDraft(role=ComponentRole.PRODUCT, structure="editor-only"),
        ])
    with pytest.raises(ValidationError, match="does not match"):
        ReactionDraft(reaction_smiles="CC>>CO", components=[
            ComponentDraft(role=ComponentRole.REACTANT, structure="CC"),
            ComponentDraft(role=ComponentRole.PRODUCT, structure="CC"),
        ])
    for invalid in ("NaN", "Infinity", "-1", "0"):
        with pytest.raises(ValidationError):
            ComponentDraft(role=ComponentRole.REACTANT, structure="CC", coefficient=invalid)


def test_coverage_uses_reactive_features_only_and_local_mapping_bonds() -> None:
    condition_only = ReactionDraft(editor_structure_data="CC>C~C>CC", components=[
        ComponentDraft(role=ComponentRole.REACTANT, structure="CC"),
        ComponentDraft(role=ComponentRole.CONDITION, structure="C~C"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="CC"),
    ])
    assert validate_draft(condition_only).validation_mode is ValidationMode.FULL
    condition_json = ReactionDraft(editor_structure_data='{"components":[{"role":"CONDITION","structure":"SRU"}]}', components=[
        ComponentDraft(role=ComponentRole.REACTANT, structure="CC"),
        ComponentDraft(role=ComponentRole.CONDITION, structure="CC"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="CC"),
    ])
    assert validate_draft(condition_json).validation_mode is ValidationMode.FULL
    ambiguous = ReactionDraft(editor_structure_data="C~C>>CC", components=[
        ComponentDraft(role=ComponentRole.REACTANT, structure="C~C"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="CC"),
    ])
    assert validate_draft(ambiguous).validation_mode is ValidationMode.LIMITED
    multiple_n = ReactionDraft(editor_structure_data="repeat", components=[
        ComponentDraft(role=ComponentRole.REACTANT, structure="[*]C", coefficient="n"),
        ComponentDraft(role=ComponentRole.REACTANT, structure="[*]C", coefficient="n"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="[*]CC[*]", coefficient="n"),
    ])
    assert validate_draft(multiple_n).validation_mode is ValidationMode.LIMITED
    local = ReactionDraft(components=[
        ComponentDraft(role=ComponentRole.REACTANT, structure="[*:9][CH2:1].[OH:2]"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="[*:9][CH2:1][OH:2]"),
    ])
    result = validate_draft(local)
    assert result.validation_mode is ValidationMode.LOCAL
    assert result.mapping_status is CheckStatus.PASS
    assert result.bond_change_status is CheckStatus.INFO
    assert "1-2" in result.bond_change_summary


def test_mapping_checks_atom_identity_and_disables_bond_changes_on_error() -> None:
    mismatch = validate_draft(ReactionDraft(components=[
        ComponentDraft(role=ComponentRole.REACTANT, structure="[13CH3:1][CH3:2]"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="[CH3:1][CH3:2]"),
    ]))
    assert mismatch.mapping_status is CheckStatus.WARNING
    assert mismatch.bond_change_status is CheckStatus.NOT_EVALUABLE


@pytest.mark.parametrize("unit", ["[*]CC", "[*]C([*])[*]"])
def test_repeat_unit_requires_two_linear_connection_points(unit: str) -> None:
    result = validate_draft(ReactionDraft(components=[
        ComponentDraft(role=ComponentRole.REACTANT, structure="C=C", coefficient="n"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure=unit, coefficient="n"),
    ], editor_structure_data="repeat unit"))
    assert result.validation_mode is ValidationMode.LIMITED


def test_sru_sidechain_is_repeat_unit_and_normalizes_single_n() -> None:
    draft_with_sru = ReactionDraft(editor_structure_data='{"sgroups":[{"type":"SRU"}]}', components=[
        ComponentDraft(role=ComponentRole.REACTANT, structure="C=C(C)"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="[*]CC(C)[*]"),
    ])
    assert draft_with_sru.components[1].coefficient == "n"
    assert validate_draft(draft_with_sru).validation_mode is ValidationMode.REPEAT_UNIT
