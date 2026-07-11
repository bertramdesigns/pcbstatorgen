"""
Optimization sub-package: bfieldtools stream function refinement and impedance extraction.

This sub-package is **optional**.  If bfieldtools / cvxpy are not installed the
pipeline falls back to the parametric wave winding produced by
``pcbstatorgen.geometry.wave_winding``.

Check availability::

    from pcbstatorgen.optimization import BFIELDTOOLS_AVAILABLE
    if BFIELDTOOLS_AVAILABLE:
        from pcbstatorgen.optimization.stream_function import StreamFunctionOptimizer
"""

try:
    import bfieldtools  # noqa: F401

    BFIELDTOOLS_AVAILABLE = True
except ImportError:
    BFIELDTOOLS_AVAILABLE = False

__all__ = ["BFIELDTOOLS_AVAILABLE"]
