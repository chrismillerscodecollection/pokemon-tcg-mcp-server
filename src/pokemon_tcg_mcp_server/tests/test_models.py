import pytest
from pydantic import ValidationError

from pokemon_tcg_mcp_server.models import (
    Ability,
    Attack,
    BlockFormat,
    Card,
    CardFilters,
    DeckEntry,
    DeckList,
    DeckValidation,
    HPFilter,
    Images,
    SearchResults,
)

from .conftest import BASE_FOSSIL, BILLS, CHARIZARD


class TestCard:
    def test_maps_mongo_document(self):
        card = Card.model_validate(CHARIZARD)

        assert card.id == "baseset-4"
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
        assert card.images == Images(
            small="https://images.pokemontcg.io/base1/91.png",
            large="https://images.pokemontcg.io/base1/91_hires.png",
        )

    def test_populate_by_name_accepts_field_names(self):
        card = Card(id="baseset-4", name="Charizard", retreat_cost=["Colorless"])

        assert card.id == "baseset-4"
        assert card.retreat_cost == ["Colorless"]

    def test_name_is_required(self):
        with pytest.raises(ValidationError):
            Card.model_validate({"_id": "baseset-4"})

    def test_id_is_required(self):
        with pytest.raises(ValidationError):
            Card.model_validate({"name": "Charizard"})

    def test_model_dump_uses_snake_case_field_names(self):
        # The tools json.dumps() this dump, so the wire shape is field names,
        # not the camelCase Mongo aliases.
        dumped = Card.model_validate(CHARIZARD).model_dump()

        assert dumped["id"] == "baseset-4"
        assert dumped["retreat_cost"] == ["Colorless"] * 3
        assert dumped["attacks"][0]["converted_energy_cost"] == 4
        assert "_id" not in dumped
        assert "retreatCost" not in dumped

    def test_maps_rules_and_legalities(self):
        # A Trainer's whole effect is in 'rules'; without it a search result
        # for one is a name and a number.
        card = Card.model_validate(BILLS)

        assert card.rules == ["Draw 2 cards."]
        assert card.legalities == {"unlimited": "Legal"}

    def test_rules_and_legalities_default_to_empty(self):
        card = Card.model_validate({"_id": "x-1", "name": "X"})

        assert card.rules == []
        assert card.legalities == {}


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

    def test_still_derives_from_a_full_document(self):
        # The validator reads 'hp' out of the fields validated so far, so it
        # only works while 'hp' is declared above 'hp_numeric'. Adding a field
        # between them would silently zero every card's hp_numeric.
        assert Card.model_validate(CHARIZARD).hp_numeric == 120


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
        assert block_format.sets == ["baseset", "jungle", "fossil"]

    def test_maps_promo_sets(self):
        block_format = BlockFormat.model_validate(BASE_FOSSIL)

        assert len(block_format.promo_sets) == 1
        assert block_format.promo_sets[0].name == "wizardsblackstarpromos"
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
        assert filters.supertype is None
        assert filters.name is None
        assert filters.weakness is None
        assert filters.resistance is None
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


class TestSearchResults:
    def test_paging_numbers_come_before_the_payload(self):
        # The caller has to see total_count to know whether to page again;
        # burying it after 'cards' means reading past the whole result first.
        dumped = SearchResults(
            total_count=228, limit=25, offset=0, returned=1, cards=[]
        ).model_dump()

        assert list(dumped) == [
            "total_count",
            "limit",
            "offset",
            "returned",
            "cards",
        ]

    def test_cards_are_dumped_as_cards(self):
        dumped = SearchResults(
            total_count=1,
            limit=25,
            offset=0,
            returned=1,
            cards=[Card.model_validate(BILLS)],
        ).model_dump()

        assert dumped["cards"][0]["id"] == "baseset-91"
        assert dumped["cards"][0]["rules"] == ["Draw 2 cards."]


class TestDeckInput:
    """Deck input rejects unknown keys, unlike the Mongo-facing models.

    CardFilters is lenient because a dropped filter only widens a search. A
    dropped deck key would produce a confident verdict about a different deck.
    """

    def test_accepts_a_well_formed_deck(self):
        deck = DeckList.model_validate(
            {
                "cards": [{"card_id": "baseset-4", "count": 4}],
                "block_format": "base-fossil",
            }
        )

        assert deck.cards == [DeckEntry(card_id="baseset-4", count=4)]

    def test_count_is_required(self):
        with pytest.raises(ValidationError):
            DeckEntry.model_validate({"card_id": "baseset-4"})

    def test_unknown_key_is_rejected(self):
        with pytest.raises(ValidationError):
            DeckEntry.model_validate({"card_id": "baseset-4", "qty": 4})

    @pytest.mark.parametrize("count", [0, -1, 61])
    def test_out_of_range_counts_are_rejected(self, count):
        with pytest.raises(ValidationError):
            DeckEntry.model_validate({"card_id": "baseset-4", "count": count})

    def test_empty_card_id_is_rejected(self):
        with pytest.raises(ValidationError):
            DeckEntry.model_validate({"card_id": "", "count": 4})

    def test_an_empty_deck_is_rejected(self):
        with pytest.raises(ValidationError):
            DeckList.model_validate({"cards": [], "block_format": "base-fossil"})

    def test_block_format_is_required(self):
        with pytest.raises(ValidationError):
            DeckList.model_validate({"cards": [{"card_id": "x-1", "count": 1}]})


class TestDeckValidation:
    def test_defaults_to_a_clean_verdict(self):
        result = DeckValidation(valid=True)

        assert result.errors == []
        assert result.warnings == []
        assert result.total_cards == 0
