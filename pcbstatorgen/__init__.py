"""
pcbstatorgen
============
KiCad PCB stator generator for linear and axial-flux coreless motors.

Pipeline summary
----------------
1. LinearMotorConfig / AxialMotorConfig  — user-supplied parameters (SI units)
2. LayerOptimizer     — determines optimal layer count + copper weights
3. Coil generators    — wave winding, sine wave, concentrated, rhombic, or spiral paths
4. ViaGridGenerator   — produces grid via arrays for layer transitions
5. ForceEvaluator     — validates force/ripple with Magpylib analytical model
6. KiCadBoardWriter   — writes Tracks and Vias via the KiCad 10 IPC API

Entry points
------------
*  ``python -m pcbstatorgen.server``  — JSON-RPC server (Tauri sidecar)
*  ``streamlit run gui/streamlit_app.py``  — Streamlit dashboard (legacy)
*  ``python plugin_entry.py``  — CLI plugin entry (requires KiCad 10 open)
"""

from pcbstatorgen.config import (
    MagnetArrangement,
    CoilTopology,
    BaseMotorConfig,
    LinearMotorConfig,
    AxialMotorConfig,
    MotorConfig,
    StackupResult,
    HeightStackResult,
    FrictionBudget,
    PowerBudget,
)
from pcbstatorgen.units import mm, m_to_mm

__all__ = [
    "MagnetArrangement",
    "CoilTopology",
    "BaseMotorConfig",
    "LinearMotorConfig",
    "AxialMotorConfig",
    "MotorConfig",
    "StackupResult",
    "HeightStackResult",
    "FrictionBudget",
    "PowerBudget",
    "mm",
    "m_to_mm",
]
__version__ = "0.3.0"

