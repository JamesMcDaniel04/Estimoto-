"""Canonical US ZIP service areas used for exact provider matching."""
import re

ZIP = re.compile(r"^[0-9]{5}(?:-[0-9]{4})?$")


def canonical_zip(value: str) -> str | None:
    value = value.strip()
    if not ZIP.fullmatch(value):
        return None
    return value[:5]
