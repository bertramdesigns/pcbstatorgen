"""
pcbstatorgen.stackup.height_stack
===================================
Computes the physical vertical stack from the PCB bottom surface to the top
of the magnet assembly and returns a :class:`~pcbstatorgen.config.HeightStackResult`.

Stack model (bottom to top)
----------------------------

.. code-block:: text

    ─────────────────────────────────────── PCB bottom surface
    │  pcb_thickness_m (1.0–1.6 mm FR4)
    ─────────────────────────────────────── PCB top surface
    │  cu_protrusion_m  (35 µm @ 1 oz)
    ─────────────────────────────────────── PCB copper top
    │  solder_mask_m    (~20 µm)
    ─────────────────────────────────────── Solder mask surface
    │  air_gap_m        (≥ 0.2 mm)
    ─────────────────────────────────────── Magnet bottom face
    │  magnet_height_m  (magnet_dims_m[2])
    ─────────────────────────────────────── Magnet top face
    │  back_iron_thickness_m (0 = none)
    ─────────────────────────────────────── Back-iron top
    │  tolerance_m      (assembly margin)
    ═══════════════════════════════════════ Total height

Field sensitivity
-----------------
Air gap has the strongest (exponential) effect on field strength.  The
:meth:`HeightStackCalculator.field_sensitivity_per_mm` method returns the
fractional change in B_z per mm of additional air gap:

.. math::

    \\frac{\\partial B_z}{\\partial h} = -\\frac{\\pi}{\\tau} B_z

This is the most important design insight from the height stack analysis:
for a 12 mm pole pitch, every extra 1 mm of air gap costs ≈ 26 % of
the field strength.
"""

from __future__ import annotations

import math

from pcbstatorgen.config import HeightStackResult, LinearMotorConfig
from pcbstatorgen.units import oz_to_m

__all__ = ["HeightStackCalculator"]

#: Nominal LPI solder mask thickness [m].
_SOLDER_MASK_M: float = 20e-6  # 20 µm

#: Default assembly tolerance / adhesive fillet margin [m].
_DEFAULT_TOLERANCE_M: float = 3e-4  # 0.3 mm


class HeightStackCalculator:
    """Compute the physical height stack for a linear fader assembly.

    Parameters
    ----------
    outer_copper_oz:
        Outer-layer copper weight [oz/ft²].  Sets the copper protrusion
        above the PCB substrate.  Default: 1 oz (35 µm).
    tolerance_m:
        Assembly tolerance / adhesive fillet margin [m].
        Default: 0.3 mm.

    Examples
    --------
    Default config::

        from pcbstatorgen.stackup.height_stack import HeightStackCalculator

        calc = HeightStackCalculator()
        result = calc.calculate(config)
        print(result.summary())
        print("Fits in 8 mm:", result.fits_in_budget(0.008))
        print(
            "Field sensitivity:",
            f"{calc.field_sensitivity_per_mm(config)*100:.1f} %/mm",
        )
    """

    def __init__(
        self,
        outer_copper_oz: float = 1.0,
        tolerance_m: float = _DEFAULT_TOLERANCE_M,
    ) -> None:
        if outer_copper_oz <= 0:
            raise ValueError(
                f"outer_copper_oz must be positive, got {outer_copper_oz}"
            )
        if tolerance_m < 0:
            raise ValueError(f"tolerance_m must be ≥ 0, got {tolerance_m}")
        self.outer_copper_oz = outer_copper_oz
        self.tolerance_m = tolerance_m

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate(self, config: LinearMotorConfig) -> HeightStackResult:
        """Return the full height stack for *config*.

        Parameters
        ----------
        config:
            Linear motor configuration.

        Returns
        -------
        HeightStackResult
        """
        return HeightStackResult(
            pcb_thickness_m=config.pcb_thickness_m,
            cu_protrusion_m=oz_to_m(self.outer_copper_oz),
            solder_mask_m=_SOLDER_MASK_M,
            air_gap_m=config.air_gap_m,
            magnet_height_m=config.magnet_dims_m[2],
            back_iron_thickness_m=config.back_iron_thickness_m,
            tolerance_m=self.tolerance_m,
        )

    def fits_in_budget(self, config: LinearMotorConfig, budget_m: float) -> bool:
        """Return ``True`` if the stack fits within *budget_m*.

        Parameters
        ----------
        config:
            Linear motor configuration.
        budget_m:
            Total available height [m].
        """
        return self.calculate(config).fits_in_budget(budget_m)

    def headroom_m(self, config: LinearMotorConfig, budget_m: float) -> float:
        """Remaining height margin [m]  (negative = over budget)."""
        return self.calculate(config).headroom_m(budget_m)

    def max_air_gap_for_budget(
        self,
        config: LinearMotorConfig,
        budget_m: float,
    ) -> float:
        """Maximum air gap that fits within *budget_m* [m].

        All other stack components are held constant.  Useful for the wizard
        "how tight can I make the air gap?" question.

        Returns 0 if there is no room even for a zero air gap.
        """
        result = self.calculate(config)
        # Subtract all components except air_gap_m
        other = result.total_height_m - result.air_gap_m
        return max(0.0, budget_m - other)

    @staticmethod
    def field_sensitivity_per_mm(config: LinearMotorConfig) -> float:
        """Fractional change in Bz per mm of additional air gap.

        Derived from the first Fourier harmonic of the alternating-pole field:

        .. math::

            \\frac{\\partial B_z}{\\partial h} = -\\frac{\\pi}{\\tau} B_z

        so the *fractional* sensitivity (independent of Br) is:

        .. math::

            s = \\frac{1}{B_z}\\frac{\\partial B_z}{\\partial h}
              = -\\frac{\\pi}{\\tau}   \\quad [\\mathrm{m}^{-1}]

        Converting to per-mm: ``s × 1e-3`` (negative = field decreases with gap).

        Parameters
        ----------
        config:
            Motor configuration supplying ``pole_pitch_m``.

        Returns
        -------
        float
            Fractional Bz change per mm of additional air gap (negative).
            E.g. −0.26 means every +1 mm of gap removes ~26 % of the field.
        """
        tau = config.pole_pitch_m
        return -(math.pi / tau) * 1e-3  # [per mm]

    @staticmethod
    def field_at_gap(config: LinearMotorConfig, air_gap_m: float) -> float:
        """Estimate the peak Bz [T] at a given air gap using the 1st harmonic.

        Uses the analytical formula for a sinusoidally magnetised pole array:

        .. math::

            B_z \\approx \\frac{4}{\\pi} B_r
            \\left(1 - e^{-\\pi t_m / \\tau}\\right)
            e^{-\\pi h / \\tau}

        where :math:`t_m` is the magnet height and :math:`h` is the air gap.

        Parameters
        ----------
        config:
            Motor configuration.
        air_gap_m:
            Air gap to evaluate at [m].

        Returns
        -------
        float
            Estimated peak Bz [T] at the PCB surface.
        """
        br = config.magnet_remanence_t
        tau = config.pole_pitch_m
        tm = config.magnet_dims_m[2]
        bz = (4.0 / math.pi) * br * (1.0 - math.exp(-math.pi * tm / tau)) * math.exp(
            -math.pi * air_gap_m / tau
        )
        return bz
