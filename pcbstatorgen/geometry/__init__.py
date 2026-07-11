"""Geometry sub-package: wave winding paths, via grids, end-turn routing,
and concentrated/rhombic/spiral coil generators."""

from pcbstatorgen.geometry.coil_generators import (
    make_coil_generator,
    ConcentratedCoilGenerator,
    RhombicCoilGenerator,
    SpiralCoilGenerator,
)
from pcbstatorgen.geometry.wave_winding import (
    WaveWindingGenerator,
    PhaseCoil,
    CoilSegment,
)

__all__ = [
    "make_coil_generator",
    "ConcentratedCoilGenerator",
    "RhombicCoilGenerator",
    "SpiralCoilGenerator",
    "WaveWindingGenerator",
    "PhaseCoil",
    "CoilSegment",
]
