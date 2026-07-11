"""
pcbstatorgen
=================
KiCad PCB stator generator for linear coreless motors (flying fader).

Pipeline summary
----------------
1. MotorConfig  — user-supplied parameters (SI units)
2. LayerOptimizer — determines optimal layer count + copper weights
3. WaveWindingGenerator — produces 3-phase sinusoidal coil polylines
4. ViaGridGenerator — produces grid via arrays for end-turns
5. ForceEvaluator (Magpylib) — validates force ripple before writing
6. KiCadBoardWriter (kipy IPC API) — writes Tracks and Vias to a live KiCad 10 board
7. [Optional] StreamFunctionOptimizer (bfieldtools) — convex path refinement
8. FEAExporter (GMSH + Elmer) — exports geometry for 3D thermal/AC validation

Entry point
-----------
Run ``plugin_entry.py`` from the KiCad 10 scripting console with the
IPC API server enabled (Preferences > Plugins > Enable IPC API).
"""

from pcbstatorgen.config import MotorConfig, StackupResult
from pcbstatorgen.units import mm, m_to_mm

__all__ = ["MotorConfig", "StackupResult", "mm", "m_to_mm"]
__version__ = "0.1.0"
