"""Importing this package registers every tool with the FastMCP app."""

from . import get_card_by_id, list_all_block_formats, search_cards, validate_deck

__all__ = [
    "get_card_by_id",
    "list_all_block_formats",
    "search_cards",
    "validate_deck",
]
