from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Model(BaseModel):
    """Shared config: accept Mongo's camelCase keys, ignore unmapped fields."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class Attack(_Model):
    name: str
    cost: list[str] = Field(default_factory=list)
    converted_energy_cost: int = Field(default=0, alias="convertedEnergyCost")
    damage: str = ""
    text: str = ""


class Ability(_Model):
    name: str
    text: str = ""
    type: str = ""


class Weakness(_Model):
    type: str
    value: str


class Resistance(_Model):
    type: str
    value: str


class Images(_Model):
    small: str = ""
    large: str = ""


Types = list[str]
Attacks = list[Attack]
Weaknesses = list[Weakness]
Resistances = list[Resistance]
Abilities = list[Ability]
AttackCost = list[str]


class HPFilter(_Model):
    eq: str | None = None
    gte: int | None = None
    lte: int | None = None


class Card(_Model):
    id: str = Field(alias="_id")
    name: str
    supertype: str = ""
    subtypes: list[str] = Field(default_factory=list)
    number: str = ""
    hp: str | None = None
    hp_numeric: int = Field(default=0, validate_default=True)
    types: Types = Field(default_factory=list)
    attacks: Attacks = Field(default_factory=list)
    abilities: Abilities = Field(default_factory=list)
    weaknesses: Weaknesses = Field(default_factory=list)
    resistances: Resistances = Field(default_factory=list)
    retreat_cost: list[str] = Field(default_factory=list, alias="retreatCost")
    rarity: str | None = None
    artist: str = ""
    images: Images = Field(default_factory=Images)

    @field_validator("hp_numeric", mode="before")
    @classmethod
    def derive_hp_numeric(cls, v, info):
        """Cards store hp as a string ('90') and have no hp_numeric field.

        validate_default is required on the field: without it Pydantic skips
        the validator entirely when the key is absent from the document, which
        for this database is always.
        """
        if v:
            return v
        hp = info.data.get("hp") or ""
        digits = "".join(c for c in hp if c.isdigit())
        return int(digits) if digits else 0


class PromoSet(_Model):
    name: str
    card_range: str = Field(default="", alias="cardRange")


class BlockFormat(_Model):
    id: str = Field(alias="_id")
    name: str
    category: str = ""
    blog_label_year: int | None = Field(default=None, alias="blogLabelYear")
    era_years_covered: str = Field(default="", alias="eraYearsCovered")
    set_range_label: str = Field(default="", alias="setRangeLabel")
    sets: list[str] = Field(default_factory=list)
    promo_sets: list[PromoSet] = Field(default_factory=list, alias="promoSets")


class CardFilters(_Model):
    hp: HPFilter | None = None
    types: Types = Field(default_factory=list)
    weakness: str | None = None
    attack_cost: AttackCost | None = None
    rarity: str | None = None
    block_format: str | None = None
