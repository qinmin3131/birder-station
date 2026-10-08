from dataclasses import dataclass
from typing import Callable, Iterable

from .birdreport_client import NormalizedSpecies


@dataclass(frozen=True)
class MappedSpecies:
    source: str
    birdreport_name: str | None
    local_name: str | None
    scientific_name: str | None
    ebird_name: str | None
    taxonomy_code: str | None
    count_value: str
    included: bool
    mapping_status: str


def merge_species(
    report_species: Iterable[NormalizedSpecies],
    local_species: Iterable[object],
    taxonomy_lookup: Callable[[str], list[dict]],
) -> list[MappedSpecies]:
    local_by_key = {}
    for item in local_species:
        scientific = getattr(item, "scientific_name", None)
        chinese = getattr(item, "primary_bird_cn", None)
        local_by_key[scientific or chinese] = item

    output = []
    consumed = set()
    for remote in report_species:
        key = remote.scientific_name or remote.name
        local = local_by_key.get(key)
        if local is None:
            local = next((value for value in local_by_key.values() if getattr(value, "primary_bird_cn", None) == remote.name), None)
        if local is not None:
            consumed.add(id(local))
        candidates = taxonomy_lookup(remote.scientific_name or remote.name)
        chosen = candidates[0] if len(candidates) == 1 else None
        output.append(MappedSpecies(
            source="both" if local is not None else "birdreport",
            birdreport_name=remote.name,
            local_name=getattr(local, "primary_bird_cn", None) if local else None,
            scientific_name=(chosen or {}).get("scientific_name") or remote.scientific_name,
            ebird_name=(chosen or {}).get("common_name"),
            taxonomy_code=(chosen or {}).get("code"),
            count_value=remote.count,
            included=True,
            mapping_status="mapped" if chosen else "needs_confirmation",
        ))

    for local in local_by_key.values():
        if id(local) in consumed:
            continue
        scientific = getattr(local, "scientific_name", None)
        candidates = taxonomy_lookup(scientific or getattr(local, "primary_bird_cn", ""))
        chosen = candidates[0] if len(candidates) == 1 else None
        output.append(MappedSpecies(
            source="local_supplement",
            birdreport_name=None,
            local_name=getattr(local, "primary_bird_cn", None),
            scientific_name=(chosen or {}).get("scientific_name") or scientific,
            ebird_name=(chosen or {}).get("common_name"),
            taxonomy_code=(chosen or {}).get("code"),
            count_value="X",
            included=False,
            mapping_status="mapped" if chosen else "needs_confirmation",
        ))
    return output
