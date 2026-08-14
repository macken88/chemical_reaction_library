"""GUI-independent parsing, validation, and RDKit search primitives."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from fractions import Fraction
from typing import Iterable

from rdkit import Chem
from rdkit.Chem import rdChemReactions

from backend.schemas import (
    CheckStatus,
    ComponentDraft,
    ComponentRole,
    ParseResponse,
    ReactionDraft,
    ValidationMode,
    ValidationResponse,
)

VALIDATOR_VERSION = "1.0"
SCOPE_NOTE = "Mechanical validation checks only representational consistency; it does not guarantee that a reaction is chemically feasible."


def mol_from_structure(structure: str) -> Chem.Mol | None:
    """Parse a SMILES conservatively. Local/editor-only structures return None."""
    try:
        return Chem.MolFromSmiles(structure)
    except Exception:
        return None


def canonical_smiles(structure: str) -> str | None:
    molecule = mol_from_structure(structure)
    return Chem.MolToSmiles(molecule, canonical=True) if molecule is not None else None


def parse_reaction(content: str, input_format: str = "auto") -> ParseResponse:
    stripped = content.strip()
    is_rxn = input_format == "rxn" or (input_format == "auto" and ("$RXN" in stripped or "$MOL" in stripped))
    if is_rxn:
        return _parse_rxn(stripped)
    return _parse_reaction_smiles(stripped)


def _parse_reaction_smiles(text: str) -> ParseResponse:
    fields = text.split(">")
    if len(fields) != 3:
        raise ValueError("Reaction SMILES must contain reactants>agents>products")
    components: list[ComponentDraft] = []
    for role, field in zip((ComponentRole.REACTANT, ComponentRole.CONDITION, ComponentRole.PRODUCT), fields, strict=True):
        for smiles in filter(None, field.split(".")):
            if mol_from_structure(smiles) is None:
                raise ValueError(f"Unable to parse {role.value.lower()} component: {smiles}")
            components.append(ComponentDraft(role=role, structure=smiles))
    if not any(c.role is ComponentRole.REACTANT for c in components) or not any(c.role is ComponentRole.PRODUCT for c in components):
        raise ValueError("Reaction SMILES requires at least one reactant and one product")
    return ParseResponse(draft=ReactionDraft(reaction_smiles=text, editor_structure_data=text, components=components))


def _parse_rxn(text: str) -> ParseResponse:
    try:
        reaction = rdChemReactions.ReactionFromRxnBlock(text, sanitize=False, removeHs=False)
    except Exception as exc:
        raise ValueError(f"Unable to parse RXN: {exc}") from exc
    if reaction is None:
        raise ValueError("Unable to parse RXN")
    components: list[ComponentDraft] = []
    for role, molecules in ((ComponentRole.REACTANT, reaction.GetReactants()), (ComponentRole.PRODUCT, reaction.GetProducts())):
        for molecule in molecules:
            try:
                Chem.SanitizeMol(molecule)
                smiles = Chem.MolToSmiles(molecule, canonical=False)
            except Exception as exc:
                raise ValueError(f"RXN contains an invalid {role.value.lower()} structure: {exc}") from exc
            components.append(ComponentDraft(role=role, structure=smiles))
    if not components:
        raise ValueError("RXN contains no reaction components")
    reaction_smiles = rdChemReactions.ReactionToSmiles(reaction, canonical=False)
    return ParseResponse(draft=ReactionDraft(reaction_smiles=reaction_smiles, editor_structure_data=text, components=components))


def classify(draft: ReactionDraft, parsed: dict[int, Chem.Mol | None] | None = None) -> ValidationMode:
    parsed = parsed or {index: mol_from_structure(c.structure) for index, c in enumerate(draft.components)}
    if any(molecule is None for molecule in parsed.values()):
        return ValidationMode.LIMITED
    has_dummy = any(
        atom.GetAtomicNum() == 0
        for molecule in parsed.values()
        if molecule is not None
        for atom in molecule.GetAtoms()
    )
    has_repeat_coefficient = any(component.coefficient == "n" for component in draft.components)
    if has_repeat_coefficient and has_dummy:
        return ValidationMode.REPEAT_UNIT
    if has_dummy:
        return ValidationMode.LOCAL
    if has_repeat_coefficient:
        # A repeat coefficient on finite structures still permits symbolic unit checks.
        return ValidationMode.REPEAT_UNIT
    return ValidationMode.FULL


def _coefficient(value: str) -> tuple[Fraction, Fraction]:
    return (Fraction(0), Fraction(1)) if value == "n" else (Fraction(value), Fraction(0))


def _format_amount(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _format_expression(constant: Fraction, repeat: Fraction) -> str:
    pieces: list[str] = []
    if constant:
        pieces.append(_format_amount(constant))
    if repeat:
        n = "n" if repeat == 1 else (f"-{_format_amount(-repeat)}n" if repeat < 0 else f"{_format_amount(repeat)}n")
        pieces.append(n)
    return "+".join(pieces).replace("+-", "-") or "0"


def _atom_counts(molecule: Chem.Mol) -> Counter[str]:
    counts: Counter[str] = Counter()
    for atom in molecule.GetAtoms():
        if atom.GetAtomicNum() == 0:
            continue
        counts[atom.GetSymbol()] += 1
        # GetTotalNumHs covers implicit as well as bracketed attached hydrogens;
        # literal [H] atoms above are counted separately.
        counts["H"] += atom.GetTotalNumHs()
    return counts


def _balance(
    components: Iterable[ComponentDraft], parsed: dict[int, Chem.Mol | None], role: ComponentRole, charge: bool = False
) -> dict[str, tuple[Fraction, Fraction]]:
    total: dict[str, tuple[Fraction, Fraction]] = defaultdict(lambda: (Fraction(0), Fraction(0)))
    for index, component in enumerate(components):
        if component.role is not role:
            continue
        molecule = parsed[index]
        if molecule is None:
            continue
        counts: Counter[str] = Counter({"charge": sum(atom.GetFormalCharge() for atom in molecule.GetAtoms())}) if charge else _atom_counts(molecule)
        numeric, repeat = _coefficient(component.coefficient)
        for element, count in counts.items():
            old_numeric, old_repeat = total[element]
            total[element] = (old_numeric + numeric * count, old_repeat + repeat * count)
    return total


def _balance_difference(
    components: list[ComponentDraft], parsed: dict[int, Chem.Mol | None], charge: bool = False
) -> dict[str, str]:
    left = _balance(components, parsed, ComponentRole.REACTANT, charge)
    right = _balance(components, parsed, ComponentRole.PRODUCT, charge)
    difference: dict[str, str] = {}
    for element in set(left) | set(right):
        left_const, left_n = left[element]
        right_const, right_n = right[element]
        delta = (right_const - left_const, right_n - left_n)
        if delta != (0, 0):
            difference[element] = _format_expression(*delta)
    return difference


def _mapping_and_bonds(components: list[ComponentDraft], parsed: dict[int, Chem.Mol | None], mode: ValidationMode) -> tuple[CheckStatus, CheckStatus, str, list[str]]:
    if mode is not ValidationMode.FULL:
        return CheckStatus.NOT_EVALUABLE, CheckStatus.NOT_EVALUABLE, "Atom mapping is not fully evaluable for this coverage mode.", []
    maps: dict[ComponentRole, list[int]] = {ComponentRole.REACTANT: [], ComponentRole.PRODUCT: []}
    missing = False
    bonds: dict[ComponentRole, dict[tuple[int, int], str]] = {ComponentRole.REACTANT: {}, ComponentRole.PRODUCT: {}}
    for index, component in enumerate(components):
        if component.role is ComponentRole.CONDITION:
            continue
        molecule = parsed[index]
        assert molecule is not None
        for atom in molecule.GetAtoms():
            atom_map = atom.GetAtomMapNum()
            if not atom_map:
                missing = True
            else:
                maps[component.role].append(atom_map)
        for bond in molecule.GetBonds():
            first = molecule.GetAtomWithIdx(bond.GetBeginAtomIdx()).GetAtomMapNum()
            second = molecule.GetAtomWithIdx(bond.GetEndAtomIdx()).GetAtomMapNum()
            if first and second:
                bonds[component.role][tuple(sorted((first, second)))] = str(bond.GetBondType())
    if missing:
        return CheckStatus.WARNING, CheckStatus.NOT_EVALUABLE, "Atom mapping is absent or incomplete; bond changes cannot be extracted.", ["Atom mapping is absent or incomplete."]
    reactant_maps, product_maps = maps[ComponentRole.REACTANT], maps[ComponentRole.PRODUCT]
    if len(set(reactant_maps)) != len(reactant_maps) or len(set(product_maps)) != len(product_maps):
        return CheckStatus.WARNING, CheckStatus.NOT_EVALUABLE, "Duplicate atom-map numbers were found.", ["Atom mapping contains duplicate map numbers."]
    if set(reactant_maps) != set(product_maps):
        return CheckStatus.WARNING, CheckStatus.NOT_EVALUABLE, "Reactant and product atom-map sets differ.", ["Reactant and product atom-map sets differ."]
    changes: list[str] = []
    for key in set(bonds[ComponentRole.REACTANT]) | set(bonds[ComponentRole.PRODUCT]):
        before, after = bonds[ComponentRole.REACTANT].get(key), bonds[ComponentRole.PRODUCT].get(key)
        if before != after:
            changes.append(f"{key[0]}-{key[1]}: {before or 'none'} -> {after or 'none'}")
    return CheckStatus.PASS, CheckStatus.INFO, "; ".join(changes) or "No mapped bond changes detected.", []


def validate_draft(draft: ReactionDraft) -> ValidationResponse:
    parsed = {index: mol_from_structure(component.structure) for index, component in enumerate(draft.components)}
    mode = classify(draft, parsed)
    warnings: list[str] = []
    representation = CheckStatus.PASS if any(component.structure.strip() for component in draft.components) else CheckStatus.FAIL
    invalid_indexes = [str(index + 1) for index, molecule in parsed.items() if molecule is None]
    if invalid_indexes:
        structure = CheckStatus.NOT_EVALUABLE
        warnings.append(f"Components {', '.join(invalid_indexes)} cannot be interpreted by RDKit; retained as limited structure data.")
    elif mode is ValidationMode.LOCAL:
        structure = CheckStatus.PASS
        warnings.append("Dummy atoms indicate a local structure; whole-reaction balance is not evaluated.")
    elif mode is ValidationMode.REPEAT_UNIT:
        structure = CheckStatus.PASS
    else:
        structure = CheckStatus.PASS
    can_balance = mode in (ValidationMode.FULL, ValidationMode.REPEAT_UNIT) and not invalid_indexes
    if can_balance:
        element_difference = _balance_difference(draft.components, parsed)
        charge_difference = _balance_difference(draft.components, parsed, charge=True)
        element_status = CheckStatus.PASS if not element_difference else CheckStatus.WARNING
        charge_status = CheckStatus.PASS if not charge_difference else CheckStatus.WARNING
        if element_difference:
            warnings.append("Element balance differs: " + ", ".join(f"{key} {value}" for key, value in sorted(element_difference.items())))
        if charge_difference:
            warnings.append("Formal charge balance differs: " + charge_difference["charge"])
    else:
        element_difference, charge_difference = {}, {}
        element_status = charge_status = CheckStatus.NOT_EVALUABLE
    mapping_status, bond_status, bond_summary, mapping_warnings = _mapping_and_bonds(draft.components, parsed, mode)
    warnings.extend(mapping_warnings)
    return ValidationResponse(
        validation_mode=mode,
        representation_status=representation,
        structure_status=structure,
        element_balance_status=element_status,
        charge_balance_status=charge_status,
        mapping_status=mapping_status,
        bond_change_status=bond_status,
        bond_change_summary=bond_summary,
        element_difference=element_difference | ({"charge": charge_difference["charge"]} if charge_difference else {}),
        warnings=warnings,
        validator_version=VALIDATOR_VERSION,
        validated_at=datetime.now(UTC),
        scope_note=SCOPE_NOTE,
    )


def component_matches_substructure(structure: str, query: str) -> bool:
    molecule = mol_from_structure(structure)
    if molecule is None:
        return False
    pattern = Chem.MolFromSmarts(query) or mol_from_structure(query)
    return pattern is not None and molecule.HasSubstructMatch(pattern)
