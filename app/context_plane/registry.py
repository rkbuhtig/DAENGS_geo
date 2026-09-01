"""닫힌 capability registry, 목적 Lens, bundle/evidence 조립 정책."""

from datetime import datetime
from types import MappingProxyType

from app.context_plane.contract import (
    CONTEXT_REGISTRY_VERSION,
    ContextAtom,
    ContextBundle,
    ContextCapabilityId,
    ContextCapabilitySpec,
    ContextEvidenceReceipt,
    ContextFacet,
    ContextLensId,
    ContextLensSpec,
    ContextNamespace,
    ContextRequest,
    ContextUse,
    ContextUseAllowance,
    SubjectProfileRevisionRefV1,
    SubjectProfileSnapshotV1,
    SubjectProfileTimeBasis,
)

_NO_CAUSAL_OR_SAFETY = (
    ContextUse.FILTER,
    ContextUse.DESCRIBE,
    ContextUse.COMPARE,
    ContextUse.RECOMMEND,
)

CAPABILITY_REGISTRY = MappingProxyType(
    {
        ContextCapabilityId.WORLD_TRAIL_WEATHER: ContextCapabilitySpec(
            capability_id=ContextCapabilityId.WORLD_TRAIL_WEATHER,
            namespace=ContextNamespace.WORLD_DYNAMIC,
            payload_types=("trail_weather_v1",),
            allowed_uses=_NO_CAUSAL_OR_SAFETY,
        ),
        ContextCapabilityId.SUBJECT_DOG_PROFILE: ContextCapabilitySpec(
            capability_id=ContextCapabilityId.SUBJECT_DOG_PROFILE,
            namespace=ContextNamespace.SUBJECT,
            payload_types=("subject_profile_snapshot_v1", "subject_profile_revision_ref_v1"),
            allowed_uses=_NO_CAUSAL_OR_SAFETY,
        ),
        ContextCapabilityId.MEASUREMENT_WALK_QUALITY: ContextCapabilitySpec(
            capability_id=ContextCapabilityId.MEASUREMENT_WALK_QUALITY,
            namespace=ContextNamespace.MEASUREMENT,
            payload_types=("walk_measurement_v1",),
            allowed_uses=(ContextUse.FILTER, ContextUse.DESCRIBE, ContextUse.COMPARE),
        ),
    }
)

LENS_REGISTRY = MappingProxyType(
    {
        ContextLensId.EPISODE_REVIEW: ContextLensSpec(
            lens_id=ContextLensId.EPISODE_REVIEW,
            lens_version=1,
            required_capabilities=(ContextCapabilityId.MEASUREMENT_WALK_QUALITY,),
            optional_capabilities=(
                ContextCapabilityId.WORLD_TRAIL_WEATHER,
                ContextCapabilityId.SUBJECT_DOG_PROFILE,
            ),
            allowed_uses=(ContextUse.FILTER, ContextUse.DESCRIBE),
            subject_profile_time_basis=SubjectProfileTimeBasis.WALK_TIME,
        ),
        ContextLensId.WALK_JOURNAL: ContextLensSpec(
            lens_id=ContextLensId.WALK_JOURNAL,
            lens_version=1,
            required_capabilities=(ContextCapabilityId.WORLD_TRAIL_WEATHER,),
            optional_capabilities=(
                ContextCapabilityId.SUBJECT_DOG_PROFILE,
                ContextCapabilityId.MEASUREMENT_WALK_QUALITY,
            ),
            allowed_uses=(ContextUse.DESCRIBE,),
            subject_profile_time_basis=SubjectProfileTimeBasis.WALK_TIME,
        ),
        ContextLensId.MEMORY_PLACE_BIOGRAPHY: ContextLensSpec(
            lens_id=ContextLensId.MEMORY_PLACE_BIOGRAPHY,
            lens_version=1,
            required_capabilities=(
                ContextCapabilityId.WORLD_TRAIL_WEATHER,
                ContextCapabilityId.MEASUREMENT_WALK_QUALITY,
            ),
            optional_capabilities=(ContextCapabilityId.SUBJECT_DOG_PROFILE,),
            allowed_uses=(ContextUse.FILTER, ContextUse.DESCRIBE, ContextUse.COMPARE),
            subject_profile_time_basis=SubjectProfileTimeBasis.WALK_TIME,
        ),
        ContextLensId.ROUTE_RECOMMENDATION: ContextLensSpec(
            lens_id=ContextLensId.ROUTE_RECOMMENDATION,
            lens_version=1,
            required_capabilities=(
                ContextCapabilityId.WORLD_TRAIL_WEATHER,
                ContextCapabilityId.SUBJECT_DOG_PROFILE,
            ),
            optional_capabilities=(),
            allowed_uses=(ContextUse.FILTER, ContextUse.DESCRIBE, ContextUse.RECOMMEND),
            subject_profile_time_basis=SubjectProfileTimeBasis.CURRENT,
        ),
    }
)


def capability_spec(capability_id: ContextCapabilityId) -> ContextCapabilitySpec:
    return CAPABILITY_REGISTRY[capability_id]


def lens_spec(lens_id: ContextLensId) -> ContextLensSpec:
    return LENS_REGISTRY[lens_id]


def validate_request(request: ContextRequest) -> ContextLensSpec:
    lens = lens_spec(request.lens_id)
    requested = set(request.requested_capabilities)
    required = set(lens.required_capabilities)
    available = required | set(lens.optional_capabilities)
    if not required <= requested:
        raise ValueError("context request is missing a lens-required capability")
    if not requested <= available:
        raise ValueError("context request asks for a capability outside its lens")
    return lens


def _validate_atoms(lens: ContextLensSpec, atoms: tuple[ContextAtom, ...]) -> None:
    for atom in atoms:
        spec = capability_spec(atom.capability_id)
        if atom.payload is not None and atom.payload.payload_type not in spec.payload_types:
            raise ValueError("context atom payload is not registered for its capability")
        payload = atom.payload
        if (
            isinstance(payload, (SubjectProfileSnapshotV1, SubjectProfileRevisionRefV1))
            and payload.time_basis is not lens.subject_profile_time_basis
        ):
            raise ValueError("subject profile time basis does not match the context lens")


def build_context_bundle(
    *,
    bundle_id: str,
    request: ContextRequest,
    atoms: tuple[ContextAtom, ...],
    facets: tuple[ContextFacet, ...] = (),
    created_at: datetime,
) -> ContextBundle:
    lens = validate_request(request)
    _validate_atoms(lens, atoms)
    allowed = tuple(
        use
        for use in ContextUse
        if use in lens.allowed_uses
        and all(use in capability_spec(atom.capability_id).allowed_uses for atom in atoms)
    )
    prohibited = tuple(use for use in ContextUse if use not in allowed)
    return ContextBundle(
        bundle_id=bundle_id,
        request=request,
        registry_version=CONTEXT_REGISTRY_VERSION,
        lens_version=lens.lens_version,
        atoms=tuple(sorted(atoms, key=lambda atom: atom.atom_id)),
        facets=tuple(sorted(facets, key=lambda facet: facet.facet_id)),
        use_allowance=ContextUseAllowance(allowed=allowed, prohibited=prohibited),
        created_at=created_at,
    )


def evidence_receipt(
    bundle: ContextBundle,
    *,
    use: ContextUse,
    evidence_atom_ids: tuple[str, ...],
) -> ContextEvidenceReceipt:
    if use not in bundle.use_allowance.allowed:
        raise ValueError("requested context use is prohibited by the lens")
    known_ids = {atom.atom_id for atom in bundle.atoms}
    if not set(evidence_atom_ids) <= known_ids:
        raise ValueError("context evidence must refer to atoms in the bundle")
    if not evidence_atom_ids:
        raise ValueError("context evidence cannot be empty")
    used_atoms = [atom for atom in bundle.atoms if atom.atom_id in evidence_atom_ids]
    if any(use not in capability_spec(atom.capability_id).allowed_uses for atom in used_atoms):
        raise ValueError("an evidence capability prohibits the requested use")
    return ContextEvidenceReceipt(
        bundle_fingerprint=bundle.bundle_fingerprint,
        request_fingerprint=bundle.request.request_fingerprint,
        registry_version=bundle.registry_version,
        lens_id=bundle.request.lens_id,
        lens_version=bundle.lens_version,
        use=use,
        evidence_atom_ids=evidence_atom_ids,
    )
