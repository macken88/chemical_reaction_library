"""GUI-independent RDKit parsing, coverage selection, validation, and search."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from fractions import Fraction
import json
from typing import Iterable

from rdkit import Chem
from rdkit.Chem import rdChemReactions

from backend.schemas import CheckStatus, ComponentDraft, ComponentRole, ParseResponse, ReactionDraft, ValidationMode, ValidationResponse

VALIDATOR_VERSION = "1.1"
SCOPE_NOTE = "Mechanical validation checks only representational consistency; it does not guarantee that a reaction is chemically feasible."


def mol_from_structure(structure: str) -> Chem.Mol | None:
    try:
        return Chem.MolFromSmiles(structure)
    except Exception:
        return None


def canonical_smiles(structure: str) -> str | None:
    molecule = mol_from_structure(structure)
    if molecule is None:
        return None
    # Search identity is molecular identity, not atom-map identity.  Keep maps
    # separately in the original structure/reaction representation.
    unmarked = Chem.Mol(molecule)
    for atom in unmarked.GetAtoms():
        atom.SetAtomMapNum(0)
    return Chem.MolToSmiles(unmarked, canonical=True)


def _representation_smiles(structure: str) -> str | None:
    molecule = mol_from_structure(structure)
    return Chem.MolToSmiles(molecule, canonical=True) if molecule is not None else None


def canonical_reaction_smiles(components: Iterable[ComponentDraft]) -> str | None:
    """A role-preserving canonical reaction representation from component data."""
    fields: list[list[str]] = [[], [], []]
    roles = (ComponentRole.REACTANT, ComponentRole.CONDITION, ComponentRole.PRODUCT)
    for component in components:
        canonical = _representation_smiles(component.structure)
        if canonical is None:
            return None
        fields[roles.index(component.role)].append(canonical)
    if not fields[0] or not fields[2]:
        return None
    return ">".join(".".join(sorted(field)) for field in fields)


def parse_reaction_components(text: str) -> list[ComponentDraft]:
    fields = text.strip().split(">")
    if len(fields) != 3:
        raise ValueError("Reaction SMILES must contain reactants>agents>products")
    components: list[ComponentDraft] = []
    for role, field in zip((ComponentRole.REACTANT, ComponentRole.CONDITION, ComponentRole.PRODUCT), fields, strict=True):
        for smiles in filter(None, field.split(".")):
            if mol_from_structure(smiles) is None:
                raise ValueError(f"Unable to parse {role.value.lower()} component: {smiles}")
            components.append(ComponentDraft(role=role, structure=smiles))
    if not any(component.role is ComponentRole.REACTANT for component in components) or not any(component.role is ComponentRole.PRODUCT for component in components):
        raise ValueError("Reaction SMILES requires at least one reactant and one product")
    return components


def parse_reaction(content: str, input_format: str = "auto") -> ParseResponse:
    stripped = content.strip()
    is_rxn = input_format == "rxn" or (input_format == "auto" and ("$RXN" in stripped or "$MOL" in stripped))
    if is_rxn:
        return _parse_rxn(stripped)
    components = parse_reaction_components(stripped)
    return ParseResponse(draft=ReactionDraft(editor_structure_data=stripped, components=components))


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
                components.append(ComponentDraft(role=role, structure=Chem.MolToSmiles(molecule, canonical=False)))
            except Exception as exc:
                raise ValueError(f"RXN contains an invalid {role.value.lower()} structure: {exc}") from exc
    if not components:
        raise ValueError("RXN contains no reaction components")
    return ParseResponse(draft=ReactionDraft(editor_structure_data=text, components=components))


def _editor_polymer_markers(draft: ReactionDraft) -> bool:
    """Read role-scoped editor data only; a condition marker must not alter coverage."""
    data = (draft.editor_structure_data or "").upper()
    if not data:
        return False
    # Structured editor payloads are inspected role by role.  This keeps a
    # condition-only SRU label out of the reactant/product coverage decision.
    try:
        payload = json.loads(draft.editor_structure_data or "")
        components = payload.get("components") if isinstance(payload, dict) else None
        if isinstance(components, list):
            relevant = " ".join(json.dumps(component).upper() for component in components if isinstance(component, dict) and component.get("role") in ("REACTANT", "PRODUCT"))
            return any(marker in relevant for marker in ("SRU", "S-GROUP", "SGROUP", "POLYMER", "CONNECTIONPOINT"))
    except (TypeError, ValueError):
        pass
    # Reaction SMILES can be safely split into roles.  RXN does not classify as
    # polymer unless its own mol blocks carry an S-group marker.
    if ">" in data and data.count(">") == 2:
        relevant = ">".join((data.split(">")[0], data.split(">")[2]))
    else:
        relevant = data
    return any(marker in relevant for marker in ("SRU", "S-GROUP", "SGROUP", "POLYMER", "CONNECTIONPOINT"))


def _has_ambiguous_bond(component: ComponentDraft, molecule: Chem.Mol) -> bool:
    if "~" in component.structure:
        return True
    return any(bond.GetBondType() in (Chem.BondType.UNSPECIFIED, Chem.BondType.ZERO) for bond in molecule.GetBonds())


def _reactive_components(draft: ReactionDraft) -> list[tuple[int, ComponentDraft]]:
    return [(index, component) for index, component in enumerate(draft.components) if component.role is not ComponentRole.CONDITION]


def classify(draft: ReactionDraft, parsed: dict[int, Chem.Mol | None] | None = None) -> ValidationMode:
    parsed = parsed or {index: mol_from_structure(component.structure) for index, component in enumerate(draft.components)}
    reactive = _reactive_components(draft)
    if any(parsed[index] is None for index, _ in reactive):
        return ValidationMode.LIMITED
    molecules = [(index, component, parsed[index]) for index, component in reactive]
    assert all(molecule is not None for _, _, molecule in molecules)
    if any(_has_ambiguous_bond(component, molecule) for _, component, molecule in molecules if molecule is not None):
        return ValidationMode.LIMITED
    has_dummy = any(atom.GetAtomicNum() == 0 for _, _, molecule in molecules for atom in molecule.GetAtoms() if molecule is not None)
    polymer_markers = _editor_polymer_markers(draft)
    n_by_role = {role: [component for _, component in reactive if component.role is role and component.coefficient == "n"] for role in (ComponentRole.REACTANT, ComponentRole.PRODUCT)}
    has_n = bool(n_by_role[ComponentRole.REACTANT] or n_by_role[ComponentRole.PRODUCT])
    simple_n_placement = all(len(values) <= 1 for values in n_by_role.values()) and has_n
    if simple_n_placement and (has_dummy or polymer_markers):
        return ValidationMode.REPEAT_UNIT
    if has_n or polymer_markers:
        return ValidationMode.LIMITED
    if has_dummy:
        # Require a real drawn local atom on both sides; a wildcard-only or
        # entirely abstract graph is not a meaningful local reaction site.
        has_local_site = all(any(atom.GetAtomicNum() > 0 for atom in molecule.GetAtoms()) for _, _, molecule in molecules if molecule is not None)
        return ValidationMode.LOCAL if has_local_site else ValidationMode.LIMITED
    return ValidationMode.FULL


def _coefficient(value: str) -> tuple[Fraction, Fraction]:
    return (Fraction(0), Fraction(1)) if value == "n" else (Fraction(value), Fraction(0))


def _format_amount(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _format_expression(constant: Fraction, repeat: Fraction) -> str:
    pieces = ([_format_amount(constant)] if constant else []) + (["n" if repeat == 1 else f"{_format_amount(repeat)}n"] if repeat else [])
    return "+".join(pieces).replace("+-", "-") or "0"


def _atom_counts(molecule: Chem.Mol) -> Counter[str]:
    counts: Counter[str] = Counter()
    for atom in molecule.GetAtoms():
        if atom.GetAtomicNum() == 0:
            continue
        counts[atom.GetSymbol()] += 1
        counts["H"] += atom.GetTotalNumHs()
    return counts


def _balance(components: Iterable[ComponentDraft], parsed: dict[int, Chem.Mol | None], role: ComponentRole, charge: bool = False) -> dict[str, tuple[Fraction, Fraction]]:
    total: dict[str, tuple[Fraction, Fraction]] = defaultdict(lambda: (Fraction(0), Fraction(0)))
    for index, component in enumerate(components):
        if component.role is not role:
            continue
        molecule = parsed[index]
        if molecule is None:
            continue
        counts = Counter({"charge": sum(atom.GetFormalCharge() for atom in molecule.GetAtoms())}) if charge else _atom_counts(molecule)
        numeric, repeat = _coefficient(component.coefficient)
        for element, count in counts.items():
            current = total[element]
            total[element] = (current[0] + numeric * count, current[1] + repeat * count)
    return total


def _balance_difference(components: list[ComponentDraft], parsed: dict[int, Chem.Mol | None], charge: bool = False) -> dict[str, str]:
    left, right = _balance(components, parsed, ComponentRole.REACTANT, charge), _balance(components, parsed, ComponentRole.PRODUCT, charge)
    result: dict[str, str] = {}
    for element in set(left) | set(right):
        delta = (right[element][0] - left[element][0], right[element][1] - left[element][1])
        if delta != (0, 0):
            result[element] = _format_expression(*delta)
    return result


def _mapping_and_bonds(components: list[ComponentDraft], parsed: dict[int, Chem.Mol | None], mode: ValidationMode) -> tuple[CheckStatus, CheckStatus, str, list[str]]:
    if mode not in (ValidationMode.FULL, ValidationMode.LOCAL):
        return CheckStatus.NOT_EVALUABLE, CheckStatus.NOT_EVALUABLE, "Atom mapping is not evaluable for this coverage mode.", []
    maps: dict[ComponentRole, dict[int, tuple[int, int]]] = {ComponentRole.REACTANT: {}, ComponentRole.PRODUCT: {}}
    bonds: dict[ComponentRole, dict[tuple[int, int], str]] = {ComponentRole.REACTANT: {}, ComponentRole.PRODUCT: {}}
    warnings: list[str] = []
    for index, component in enumerate(components):
        if component.role is ComponentRole.CONDITION:
            continue
        molecule = parsed[index]
        assert molecule is not None
        for atom in molecule.GetAtoms():
            # In LOCAL mode an unmapped dummy attachment is allowed; actual site
            # atoms still require maps before bond changes are claimed.
            atom_map = atom.GetAtomMapNum()
            if not atom_map and mode is ValidationMode.LOCAL and atom.GetAtomicNum() == 0:
                continue
            if not atom_map:
                warnings.append("Atom mapping is absent or incomplete.")
                continue
            identity = (atom.GetAtomicNum(), atom.GetIsotope())
            if atom_map in maps[component.role]:
                warnings.append("Atom mapping contains duplicate map numbers.")
            else:
                maps[component.role][atom_map] = identity
        for bond in molecule.GetBonds():
            first = molecule.GetAtomWithIdx(bond.GetBeginAtomIdx()).GetAtomMapNum()
            second = molecule.GetAtomWithIdx(bond.GetEndAtomIdx()).GetAtomMapNum()
            if first and second:
                bonds[component.role][tuple(sorted((first, second)))] = str(bond.GetBondType())
    if warnings:
        return CheckStatus.WARNING, CheckStatus.NOT_EVALUABLE, "; ".join(sorted(set(warnings))), sorted(set(warnings))
    if set(maps[ComponentRole.REACTANT]) != set(maps[ComponentRole.PRODUCT]):
        return CheckStatus.WARNING, CheckStatus.NOT_EVALUABLE, "Reactant and product atom-map sets differ.", ["Reactant and product atom-map sets differ."]
    mismatched = [str(atom_map) for atom_map in maps[ComponentRole.REACTANT] if maps[ComponentRole.REACTANT][atom_map] != maps[ComponentRole.PRODUCT][atom_map]]
    if mismatched:
        return CheckStatus.WARNING, CheckStatus.NOT_EVALUABLE, "Mapped atom identity differs across sides.", ["Mapped atom identity differs across sides: " + ", ".join(mismatched)]
    changes = []
    for key in set(bonds[ComponentRole.REACTANT]) | set(bonds[ComponentRole.PRODUCT]):
        before, after = bonds[ComponentRole.REACTANT].get(key), bonds[ComponentRole.PRODUCT].get(key)
        if before != after:
            changes.append(f"{key[0]}-{key[1]}: {before or 'none'} -> {after or 'none'}")
    return CheckStatus.PASS, CheckStatus.INFO, "; ".join(changes) or "No mapped bond changes detected.", []


def validate_draft(draft: ReactionDraft) -> ValidationResponse:
    parsed = {index: mol_from_structure(component.structure) for index, component in enumerate(draft.components)}
    mode = classify(draft, parsed)
    invalid = [str(index + 1) for index, component in _reactive_components(draft) if parsed[index] is None]
    warnings: list[str] = []
    if invalid:
        structure = CheckStatus.NOT_EVALUABLE
        warnings.append(f"Components {', '.join(invalid)} cannot be interpreted by RDKit; retained as editor data.")
    else:
        structure = CheckStatus.PASS
    can_balance = mode in (ValidationMode.FULL, ValidationMode.REPEAT_UNIT) and not invalid
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
    return ValidationResponse(validation_mode=mode, representation_status=CheckStatus.PASS, structure_status=structure, element_balance_status=element_status, charge_balance_status=charge_status, mapping_status=mapping_status, bond_change_status=bond_status, bond_change_summary=bond_summary, element_difference=element_difference | ({"charge": charge_difference["charge"]} if charge_difference else {}), warnings=warnings, validator_version=VALIDATOR_VERSION, validated_at=datetime.now(UTC), scope_note=SCOPE_NOTE)


def is_valid_substructure_query(query: str) -> bool:
    try:
        return Chem.MolFromSmarts(query) is not None or mol_from_structure(query) is not None
    except Exception:
        return False


def component_matches_substructure(structure: str, query: str) -> bool:
    molecule = mol_from_structure(structure)
    if molecule is None:
        return False
    try:
        pattern = Chem.MolFromSmarts(query) or mol_from_structure(query)
        return pattern is not None and molecule.HasSubstructMatch(pattern)
    except Exception:
        return False
