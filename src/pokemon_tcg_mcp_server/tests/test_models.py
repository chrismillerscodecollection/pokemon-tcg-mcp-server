import pytest
from pydantic import ValidationError

from pokemon_tcg_mcp_server.models import (
    Ability,
    Attack,
    BlockFormat,
    Card,
    CardFilters,
    HPFilter,
    Images,
)

from .conftest import BASE_FOSSIL, BILLS, CHARIZARD


class TestCard:
    def test_maps_mongo_document(self):
        card = Card.model_validate(CHARIZARD)

        assert card.id == "base1-4"
        assert card.name == "Charizard"
        assert card.supertype == "Pokémon"
        assert card.subtypes == ["Stage 2"]
        assert card.number == "4"
        assert card.hp == "120"
        assert card.types == ["Fire"]
        assert card.rarity == "Rare Holo"
        assert card.artist == "Mitsuhiro Arita"
        assert card.images.large.endswith("4_hires.png")

    def test_maps_camel_case_aliases(self):
        card = Card.model_validate(CHARIZARD)

        assert card.retreat_cost == ["Colorless"] * 3
        assert card.attacks[0].converted_energy_cost == 4

    def test_nested_documents(self):
        card = Card.model_validate(CHARIZARD)

        assert card.attacks[0].name == "Fire Spin"
        assert card.attacks[0].cost == ["Fire"] * 4
        assert card.attacks[0].damage == "100"
        assert card.weaknesses[0].type == "Water"
        assert card.weaknesses[0].value == "×2"
        assert card.resistances[0].type == "Fighting"

    def test_ignores_unmapped_fields(self):
        card = Card.model_validate(CHARIZARD)

        assert not hasattr(card, "set")

    def test_absent_fields_fall_back_to_empty_containers(self):
        card = Card.model_validate(BILLS)

        assert card.hp is None
        assert card.types == []
        assert card.attacks == []
        assert card.abilities == []
        assert card.weaknesses == []
        assert card.resistances == []
        assert card.retreat_cost == []
        assert card.images == Images(small="s", large="l")

    def test_populate_by_name_accepts_field_names(self):
        card = Card(id="base1-4", name="Charizard", retreat_cost=["Colorless"])

        assert card.id == "base1-4"
        assert card.retreat_cost == ["Colorless"]

    def test_name_is_required(self):
        with pytest.raises(ValidationError):
            Card.model_validate({"_id": "base1-4"})

    def test_id_is_required(self):
        with pytest.raises(ValidationError):
            Card.model_validate({"name": "Charizard"})

    def test_model_dump_uses_snake_case_field_names(self):
        # The tools json.dumps() this dump, so the wire shape is field names,
        # not the camelCase Mongo aliases.
        dumped = Card.model_validate(CHARIZARD).model_dump()

        assert dumped["id"] == "base1-4"
        assert dumped["retreat_cost"] == ["Colorless"] * 3
        assert dumped["attacks"][0]["converted_energy_cost"] == 4
        assert "_id" not in dumped
        assert "retreatCost" not in dumped


class TestHPNumeric:
    """hp is stored as a string and no document carries hp_numeric."""

    @pytest.mark.parametrize(
        ("hp", "expected"),
        [
            ("120", 120),
            ("40", 40),
            ("90+", 90),  # stray suffixes are stripped
            ("", 0),
            (None, 0),
            ("???", 0),  # no digits at all
        ],
    )
    def test_derived_from_hp_string(self, hp, expected):
        card = Card.model_validate({"_id": "x-1", "name": "X", "hp": hp})

        assert card.hp_numeric == expected

    def test_defaults_to_zero_when_hp_key_is_absent(self):
        # The validator has to run on the default, which is what
        # validate_default=True on the field buys.
        card = Card.model_validate({"_id": "x-1", "name": "X"})

        assert card.hp_numeric == 0

    def test_explicit_value_wins(self):
        card = Card.model_validate(
            {"_id": "x-1", "name": "X", "hp": "120", "hp_numeric": 999}
        )

        assert card.hp_numeric == 999


class TestAttackAndAbility:
    def test_attack_defaults(self):
        attack = Attack.model_validate({"name": "Tackle"})

        assert attack.cost == []
        assert attack.converted_energy_cost == 0
        assert attack.damage == ""
        assert attack.text == ""

    def test_ability_defaults(self):
        ability = Ability.model_validate({"name": "Energy Burn"})

        assert ability.text == ""
        assert ability.type == ""


class TestBlockFormat:
    def test_maps_mongo_document(self):
        block_format = BlockFormat.model_validate(BASE_FOSSIL)

        assert block_format.id == "base-fossil"
        assert block_format.name == "Base - Fossil"
        assert block_format.category == "Block"
        assert block_format.blog_label_year == 1999
        assert block_format.era_years_covered == "1999-2000"
        assert block_format.set_range_label == "Base through Fossil"
        assert block_format.sets == ["base1", "basep", "base2", "base3"]

    def test_maps_promo_sets(self):
        block_format = BlockFormat.model_validate(BASE_FOSSIL)

        assert len(block_format.promo_sets) == 1
        assert block_format.promo_sets[0].name == "Wizards Black Star Promos"
        assert block_format.promo_sets[0].card_range == "1-9"

    def test_optional_fields_default(self):
        block_format = BlockFormat.model_validate({"_id": "x", "name": "X"})

        assert block_format.blog_label_year is None
        assert block_format.era_years_covered == ""
        assert block_format.sets == []
        assert block_format.promo_sets == []


class TestFilters:
    def test_card_filters_default_to_no_filtering(self):
        filters = CardFilters()

        assert filters.hp is None
        assert filters.types == []
        assert filters.weakness is None
        assert filters.attack_cost is None
        assert filters.rarity is None
        assert filters.block_format is None

    def test_card_filters_parse_nested_hp(self):
        filters = CardFilters.model_validate(
            {"hp": {"gte": 70, "lte": 120}, "types": ["Fire"]}
        )

        assert filters.hp == HPFilter(gte=70, lte=120)
        assert filters.types == ["Fire"]

    def test_hp_filter_eq_is_a_string(self):
        # 'eq' is matched against the raw stored value, which is a string.
        assert HPFilter.model_validate({"eq": "90"}).eq == "90"

    def test_hp_bounds_coerce_numeric_strings(self):
        assert HPFilter.model_validate({"gte": "70"}).gte == 70

    def test_hp_bounds_reject_non_numeric(self):
        with pytest.raises(ValidationError):
            HPFilter.model_validate({"gte": "lots"})
