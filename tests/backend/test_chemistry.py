from rdkit.Chem import rdChemReactions

from backend.chemistry import parse_reaction, validate_draft
from backend.schemas import CheckStatus, ComponentDraft, ComponentRole, ReactionDraft, ValidationMode


def draft(*components: ComponentDraft) -> ReactionDraft:
    return ReactionDraft(components=list(components))


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
    assert validate_draft(parsed.draft).validation_mode is ValidationMode.FULL


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
    ))
    assert limited.validation_mode is ValidationMode.LIMITED
    assert limited.structure_status is CheckStatus.NOT_EVALUABLE
    edge = validate_draft(draft(
        ComponentDraft(role=ComponentRole.REACTANT, structure="[2H]c1cc([NH3+])ccc1.[Cl-]"),
        ComponentDraft(role=ComponentRole.PRODUCT, structure="[2H]c1cc([NH3+])ccc1.[Cl-]"),
    ))
    assert edge.element_balance_status is CheckStatus.PASS
