from types import SimpleNamespace

from src.records.birdreport_client import NormalizedSpecies
from src.records.mapping import merge_species


def taxonomy_lookup(name):
    return [{"scientific_name": name, "code": "tarsia", "common_name": "Red-flanked Bluetail"}]


def test_local_only_species_is_excluded_with_x_count():
    mapped = merge_species([], [SimpleNamespace(scientific_name="Tarsiger cyanurus", primary_bird_cn="红胁蓝尾鸲")], taxonomy_lookup)
    assert mapped[0].source == "local_supplement"
    assert mapped[0].included is False
    assert mapped[0].count_value == "X"


def test_remote_count_wins_and_ambiguous_taxonomy_requires_confirmation():
    def ambiguous(_name):
        return [
            {"scientific_name": "Cyanopica cyanus", "code": "azwmag", "common_name": "Azure-winged Magpie"},
            {"scientific_name": "Cyanopica cooki", "code": "ibemag2", "common_name": "Iberian Magpie"},
        ]

    mapped = merge_species(
        [NormalizedSpecies("灰喜鹊", "Cyanopica cyanus", "8")],
        [SimpleNamespace(scientific_name="Cyanopica cyanus", primary_bird_cn="灰喜鹊")],
        ambiguous,
    )
    assert mapped[0].count_value == "8"
    assert mapped[0].source == "both"
    assert mapped[0].mapping_status == "needs_confirmation"


def test_unique_remote_species_is_included():
    mapped = merge_species([NormalizedSpecies("喜鹊", "Pica pica", "2")], [], lambda _: [{"scientific_name": "Pica pica", "code": "eurmag", "common_name": "Eurasian Magpie"}])
    assert mapped[0].included is True
    assert mapped[0].mapping_status == "mapped"
