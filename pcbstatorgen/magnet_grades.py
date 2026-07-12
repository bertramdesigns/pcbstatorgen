"""
pcbstatorgen.magnet_grades
==========================
Reference table for standard NdFeB magnet grades (N35–N52).

Correlates each grade to its remanence (Br) range and maximum operating
temperature by suffix code (Std / H / SH / UH / EH / AH).  Used by
:class:`pcbstatorgen.config.BaseMotorConfig` to auto-populate
``magnet_remanence_t`` from a selected grade, and by the UI to populate
the magnet-grade dropdown.

Data source: PRODUCT_GOALS.md §3C.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "MagnetGrade",
    "MAGNET_GRADES",
    "GRADE_NAMES",
    "CUSTOM_GRADE",
    "get_remanence",
    "get_grade",
]


@dataclass(frozen=True)
class MagnetGrade:
    """A single NdFeB magnet grade specification.

    Parameters
    ----------
    name:
        Base grade name without thermal suffix (e.g. ``"N44"``).
    br_min_t:
        Minimum remanent flux density at 20 °C [T].
    br_typ_t:
        Typical (nominal) remanent flux density at 20 °C [T].
    br_max_t:
        Maximum remanent flux density at 20 °C [T].
    max_temp_c:
        Mapping of thermal suffix code → maximum operating temperature [°C].
        Keys are a subset of ``{"Std", "H", "SH", "UH", "EH", "AH"}``.
    """

    name: str
    br_min_t: float
    br_typ_t: float
    br_max_t: float
    max_temp_c: dict[str, int]


_FULL_TEMP_SUFFIXES: dict[str, int] = {
    "Std": 80,
    "H": 120,
    "SH": 150,
    "UH": 180,
    "EH": 200,
    "AH": 220,
}

_MAGNET_GRADES_DATA: tuple[tuple[str, float, float, float, dict[str, int]], ...] = (
    ("N35", 1.17, 1.19, 1.21, _FULL_TEMP_SUFFIXES),
    ("N38", 1.21, 1.23, 1.25, _FULL_TEMP_SUFFIXES),
    ("N42", 1.28, 1.30, 1.32, _FULL_TEMP_SUFFIXES),
    ("N44", 1.32, 1.34, 1.36, _FULL_TEMP_SUFFIXES),
    ("N48", 1.38, 1.40, 1.42, _FULL_TEMP_SUFFIXES),
    ("N52", 1.43, 1.45, 1.48, {"Std": 80}),
)


MAGNET_GRADES: dict[str, MagnetGrade] = {
    name: MagnetGrade(
        name=name,
        br_min_t=br_min,
        br_typ_t=br_typ,
        br_max_t=br_max,
        max_temp_c=dict(temps),
    )
    for name, br_min, br_typ, br_max, temps in _MAGNET_GRADES_DATA
}


GRADE_NAMES: list[str] = [name for name, *_ in _MAGNET_GRADES_DATA]


CUSTOM_GRADE: str = "Custom"


_BASE_GRADE_RE = re.compile(r"^([Nn]\d+)")


def _extract_base_grade(grade: str) -> str:
    """Extract the base grade (e.g. ``"N44"``) from ``"N44H"`` or ``"n44sh"``."""
    match = _BASE_GRADE_RE.match(grade.strip())
    if match is None:
        return grade.strip()
    return match.group(1).upper()


def get_remanence(grade: str) -> float:
    """Return the typical Br [T] for a magnet grade name.

    Handles grade+suffix strings (e.g. ``"N44H"`` → ``"N44"``).

    Parameters
    ----------
    grade:
        Grade name, optionally with a thermal suffix.

    Returns
    -------
    float
        Typical remanent flux density at 20 °C [T].

    Raises
    ------
    KeyError
        If the grade is not found (e.g. ``"Custom"`` or unknown).
    """
    base = _extract_base_grade(grade)
    return MAGNET_GRADES[base].br_typ_t


def get_grade(grade: str) -> MagnetGrade:
    """Return the full :class:`MagnetGrade` for a grade name.

    Handles grade+suffix strings (e.g. ``"N42SH"`` → ``"N42"``).

    Parameters
    ----------
    grade:
        Grade name, optionally with a thermal suffix.

    Returns
    -------
    MagnetGrade

    Raises
    ------
    KeyError
        If the grade is not found.
    """
    base = _extract_base_grade(grade)
    return MAGNET_GRADES[base]
