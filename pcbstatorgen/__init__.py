"""
pcbstatorgen
============
KiCad PCB stator generator for linear coreless motors (flying fader)
and future axial flux rotary motors.

Pipeline summary
----------------
1. LinearMotorConfig  — user-supplied parameters (SI units)
2. LayerOptimizer     — determines optimal layer count + copper weights
3. Coil generators    — wave winding, concentrated, rhombic, or spiral paths
4. ViaGridGenerator   — produces grid via arrays for layer transitions
5. ForceEvaluator     — validates force/ripple with Magpylib analytical model
6. KiCadBoardWriter   — writes Tracks and Vias via the KiCad 10 IPC API
7. [Optional] StreamFunctionOptimizer — bfieldtools convex path refinement
8. FEAExporter        — GMSH + Elmer FEM for 3D thermal/AC validation

Entry point
-----------
Run ``plugin_entry.py`` from a terminal while KiCad 10 is open.
Or launch the Streamlit dashboard: ``streamlit run gui/streamlit_app.py``
"""

from pcbstatorgen.config import (
    # Enums
    MagnetArrangement,
    CoilTopology,
    # Config classes
    BaseMotorConfig,
    LinearMotorConfig,
    AxialMotorConfig,
    MotorConfig,        # backwards-compatible alias
    # Result dataclasses
    StackupResult,
    HeightStackResult,
    FrictionBudget,
    PowerBudget,
)
from pcbstatorgen.units import mm, m_to_mm

__all__ = [
    # Enums
    "MagnetArrangement",
    "CoilTopology",
    # Config classes
    "BaseMotorConfig",
    "LinearMotorConfig",
    "AxialMotorConfig",
    "MotorConfig",
    # Result dataclasses
    "StackupResult",
    "HeightStackResult",
    "FrictionBudget",
    "PowerBudget",
    # Unit helpers
    "mm",
    "m_to_mm",
]
__version__ = "0.2.0"

