"""
pcbstatorgen.units
=======================
Unit conversion helpers.  All internal calculations use SI (meters, Tesla,
Amperes, Ohms, Watts).  This module provides lightweight conversion functions
so that human-readable inputs (mm, mT, oz/ft², mils) can be converted once at
the boundary and never appear inside the physics code.

Copper weight convention
------------------------
PCB copper weight is specified in ounces per square foot (oz/ft²).  The
relationship to physical thickness is:

    1 oz/ft²  = 35.00 µm  (nominal, IPC-6012 standard)
    2 oz/ft²  = 70.00 µm
    3 oz/ft²  = 105.0 µm
    4 oz/ft²  = 140.0 µm
    0.5 oz/ft² = 17.5 µm  (half-oz, common for fine-pitch outer layers)

These values are nominal; actual plated thickness varies ±10%.

Skin depth
----------
``skin_depth_m`` computes the electromagnetic skin depth δ = sqrt(ρ / (π·f·µ))
for annealed copper.  At the typical motor electrical frequency (drive frequency
× pole pairs), outer-layer traces thinner than δ minimise AC eddy current losses
while inner-layer traces can be thicker to reduce DC resistance.

KiCad IPC unit system
---------------------
The kicad-python IPC API uses **nanometres (int64)** for all coordinates and
dimensions on the wire.  ``m_to_nm`` / ``nm_to_m`` convert between the
project's SI metres and KiCad's internal units:

    m_to_nm(0.000127)  →  127_000   (5 mil trace width)
    m_to_nm(0.0002)    →  200_000   (0.2 mm via drill)

Always pass ``int`` values to kicad-python; floating-point nm values are
silently truncated by protobuf.  Use ``int(metres * 1_000_000_000)`` as the
canonical conversion.
"""

from __future__ import annotations

import math
from typing import NamedTuple

__all__ = [
    # Length
    "mm",
    "um",
    "mils_to_m",
    "m_to_mm",
    "m_to_um",
    "m_to_mils",
    # Magnetic flux density
    "mt_to_t",
    "t_to_mt",
    # Copper weight ↔ thickness
    "oz_to_m",
    "m_to_oz",
    "CopperWeight",
    # Electrical / physics
    "skin_depth_m",
    "cu_resistance_per_length",
    # KiCad IPC unit conversion (metres ↔ nanometres)
    "m_to_nm",
    "nm_to_m",
]

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

#: Electrical resistivity of annealed copper at 20 °C [Ω·m]
RHO_CU: float = 1.724e-8

#: Magnetic permeability of free space [H/m]
MU_0: float = 4.0 * math.pi * 1e-7

#: Nominal copper thickness for 1 oz/ft² [m]
_CU_1OZ_M: float = 35.0e-6


# ---------------------------------------------------------------------------
# Length conversions
# ---------------------------------------------------------------------------


def mm(value: float) -> float:
    """Convert millimetres to metres.

    This is the primary convenience helper for specifying lengths.

    Parameters
    ----------
    value:
        Length in millimetres.

    Returns
    -------
    float
        Length in metres.

    Examples
    --------
    >>> mm(10.0)
    0.01
    >>> mm(0.127)  # 5 mils in mm
    0.000127
    """
    return value * 1e-3


def um(value: float) -> float:
    """Convert micrometres to metres.

    Parameters
    ----------
    value:
        Length in micrometres (µm).

    Returns
    -------
    float
        Length in metres.

    Examples
    --------
    >>> um(35.0)
    3.5e-05
    """
    return value * 1e-6


def mils_to_m(value: float) -> float:
    """Convert mils (thou, 1/1000 inch) to metres.

    Mils appear in PCB DFM specifications (e.g. "5 mil minimum trace/space").

    Parameters
    ----------
    value:
        Length in mils.

    Returns
    -------
    float
        Length in metres.

    Examples
    --------
    >>> round(mils_to_m(5.0), 8)
    0.000127
    """
    return value * 25.4e-6


def m_to_mm(value: float) -> float:
    """Convert metres to millimetres.

    Parameters
    ----------
    value:
        Length in metres.

    Returns
    -------
    float
        Length in millimetres.

    Examples
    --------
    >>> m_to_mm(0.01)
    10.0
    """
    return value * 1e3


def m_to_um(value: float) -> float:
    """Convert metres to micrometres.

    Parameters
    ----------
    value:
        Length in metres.

    Returns
    -------
    float
        Length in micrometres.

    Examples
    --------
    >>> m_to_um(35e-6)
    35.0
    """
    return value * 1e6


def m_to_mils(value: float) -> float:
    """Convert metres to mils (thou).

    Parameters
    ----------
    value:
        Length in metres.

    Returns
    -------
    float
        Length in mils.

    Examples
    --------
    >>> round(m_to_mils(0.000127), 2)
    5.0
    """
    return value / 25.4e-6


# ---------------------------------------------------------------------------
# Magnetic flux density conversions
# ---------------------------------------------------------------------------


def mt_to_t(value: float) -> float:
    """Convert millitesla to tesla.

    Parameters
    ----------
    value:
        Flux density in mT.

    Returns
    -------
    float
        Flux density in T.

    Examples
    --------
    >>> mt_to_t(500.0)
    0.5
    """
    return value * 1e-3


def t_to_mt(value: float) -> float:
    """Convert tesla to millitesla.

    Parameters
    ----------
    value:
        Flux density in T.

    Returns
    -------
    float
        Flux density in mT.

    Examples
    --------
    >>> t_to_mt(1.32)
    1320.0
    """
    return value * 1e3


# ---------------------------------------------------------------------------
# Copper weight / thickness conversions
# ---------------------------------------------------------------------------


class CopperWeight(NamedTuple):
    """Standard PCB copper weight presets (oz/ft²) with nominal thicknesses."""

    oz: float
    """Copper weight in oz/ft²."""
    thickness_m: float
    """Nominal copper thickness in metres."""
    label: str
    """Human-readable label."""


#: Standard copper weight presets used by JLCPCB / PCBWay.
STANDARD_CU_WEIGHTS: tuple[CopperWeight, ...] = (
    CopperWeight(oz=0.5, thickness_m=17.5e-6, label="0.5 oz (17.5 µm)"),
    CopperWeight(oz=1.0, thickness_m=35.0e-6, label="1 oz (35 µm)"),
    CopperWeight(oz=2.0, thickness_m=70.0e-6, label="2 oz (70 µm)"),
    CopperWeight(oz=3.0, thickness_m=105.0e-6, label="3 oz (105 µm)"),
    CopperWeight(oz=4.0, thickness_m=140.0e-6, label="4 oz (140 µm)"),
)


def oz_to_m(oz: float) -> float:
    """Convert PCB copper weight (oz/ft²) to nominal thickness (m).

    Uses the IPC standard value of 35 µm per oz/ft².

    Parameters
    ----------
    oz:
        Copper weight in oz/ft².

    Returns
    -------
    float
        Nominal copper thickness in metres.

    Examples
    --------
    >>> oz_to_m(1.0)
    3.5e-05
    >>> oz_to_m(2.0)
    7e-05
    """
    return oz * _CU_1OZ_M


def m_to_oz(thickness_m: float) -> float:
    """Convert copper thickness (m) to equivalent copper weight (oz/ft²).

    Parameters
    ----------
    thickness_m:
        Copper thickness in metres.

    Returns
    -------
    float
        Copper weight in oz/ft².

    Examples
    --------
    >>> m_to_oz(35e-6)
    1.0
    >>> round(m_to_oz(70e-6), 1)
    2.0
    """
    return thickness_m / _CU_1OZ_M


# ---------------------------------------------------------------------------
# Electrical / physics helpers
# ---------------------------------------------------------------------------


def skin_depth_m(frequency_hz: float, rho: float = RHO_CU, mu_r: float = 1.0) -> float:
    """Calculate electromagnetic skin depth δ for a conductor.

    .. math::

        \\delta = \\sqrt{\\frac{\\rho}{\\pi f \\mu_r \\mu_0}}

    Used to select outer-layer copper weight: an outer layer thinner than δ at
    the motor drive frequency minimises AC eddy current losses.  Inner layers can
    be thicker (lower DC resistance) because they are shielded by the outer layers.

    Parameters
    ----------
    frequency_hz:
        AC drive frequency in Hz.  For a linear motor: ``electrical_freq = speed
        [pole-pairs/m] × velocity [m/s]``.
    rho:
        Electrical resistivity of the conductor material [Ω·m].
        Default is annealed copper at 20 °C (1.724 × 10⁻⁸ Ω·m).
    mu_r:
        Relative magnetic permeability (dimensionless).  Copper ≈ 1.0.

    Returns
    -------
    float
        Skin depth in metres.

    Examples
    --------
    >>> round(skin_depth_m(1e6) * 1e6, 1)   # δ at 1 MHz in µm
    66.1
    >>> round(skin_depth_m(1e7) * 1e6, 1)   # δ at 10 MHz in µm
    20.9
    >>> round(skin_depth_m(1000.0) * 1e3, 2)  # δ at 1 kHz in mm
    2.09
    """
    if frequency_hz <= 0:
        raise ValueError(f"frequency_hz must be positive, got {frequency_hz}")
    return math.sqrt(rho / (math.pi * frequency_hz * mu_r * MU_0))


def cu_resistance_per_length(width_m: float, thickness_m: float, rho: float = RHO_CU) -> float:
    """Calculate DC resistance per unit length of a rectangular copper trace.

    .. math::

        R' = \\frac{\\rho}{w \\cdot t}  \\quad [\\Omega / \\text{m}]

    Parameters
    ----------
    width_m:
        Trace width in metres.
    thickness_m:
        Copper layer thickness in metres (use :func:`oz_to_m` for conversion).
    rho:
        Electrical resistivity [Ω·m].  Default is annealed copper at 20 °C.

    Returns
    -------
    float
        Resistance per unit length [Ω/m].

    Raises
    ------
    ValueError
        If width or thickness are non-positive.

    Examples
    --------
    >>> # 0.2 mm trace, 1 oz copper
    >>> r = cu_resistance_per_length(0.2e-3, oz_to_m(1.0))
    >>> round(r, 3)
    2.463
    """
    if width_m <= 0:
        raise ValueError(f"width_m must be positive, got {width_m}")
    if thickness_m <= 0:
        raise ValueError(f"thickness_m must be positive, got {thickness_m}")
    return rho / (width_m * thickness_m)


# ---------------------------------------------------------------------------
# KiCad IPC unit conversion
# ---------------------------------------------------------------------------


def m_to_nm(metres: float) -> int:
    """Convert metres to KiCad IPC nanometres (int64).

    The kicad-python IPC API uses **nanometres** as its internal unit for all
    coordinates, widths, drill diameters, and copper thicknesses.  This
    function converts from the project's SI metres to the integer nm value
    expected by kicad-python.

    .. important::
        The return type is ``int``.  Passing a ``float`` to kicad-python
        protobuf fields causes silent truncation.  Always use this function
        rather than multiplying inline.

    Parameters
    ----------
    metres:
        Length, width, or position in metres.

    Returns
    -------
    int
        Value in nanometres, truncated toward zero.

    Examples
    --------
    >>> m_to_nm(0.000127)    # 5-mil (0.127 mm) trace width
    127000
    >>> m_to_nm(0.0002)      # 0.2 mm via drill
    200000
    >>> m_to_nm(0.02)        # 20 mm board width
    20000000
    >>> m_to_nm(0.000035)    # 35 µm = 1 oz copper thickness
    35000
    """
    return int(metres * 1_000_000_000)


def nm_to_m(nanometres: int) -> float:
    """Convert KiCad IPC nanometres back to metres.

    The inverse of :func:`m_to_nm`.  Use when reading coordinates or
    dimensions from kicad-python objects and converting back to SI for
    physics calculations.

    Parameters
    ----------
    nanometres:
        Value in nanometres (as returned by kicad-python properties).

    Returns
    -------
    float
        Length in metres.

    Examples
    --------
    >>> nm_to_m(127000)
    0.000127
    >>> nm_to_m(200000)
    0.0002
    >>> round(nm_to_m(35000), 8)
    3.5e-05
    """
    return float(nanometres) / 1_000_000_000
