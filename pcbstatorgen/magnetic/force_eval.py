"""
pcbstatorgen.magnetic.force_eval
=======================================
Evaluates the linear thrust force and torque on the PCB stator coil as a
function of mover position using Magpylib v5 ``getFT()``.

Physical model
--------------
The mover carriage (magnet array) slides in the +X direction over the
stationary PCB stator.  At each carriage position the 3-phase winding is
energised according to a *commutation* strategy that maximises continuous
thrust.

Two commutation strategies are provided:

``max_torque`` (default — field-oriented control)
    Applies sinusoidal phase currents that maximise thrust at each electrical
    angle.  One full electrical cycle equals two pole pitches (the magnets
    advance by ``2τ`` between repeating current patterns).

    .. math::

        I_A = I_{\\text{peak}} \\cdot \\sin(\\theta_e)\\\\
        I_B = I_{\\text{peak}} \\cdot \\sin(\\theta_e - 2\\pi/3)\\\\
        I_C = I_{\\text{peak}} \\cdot \\sin(\\theta_e + 2\\pi/3)

    where :math:`\\theta_e = 2\\pi \\cdot p / (2\\tau)` and *p* is the mover
    position.

``phase_a_only``
    Only Phase A is energised at the full peak current; Phases B and C carry
    zero current.  Useful for measuring the raw coupling coefficient of a
    single phase or debugging geometry.

Force ripple
------------
The force ripple is calculated as:

.. math::

    \\text{ripple}_{\\%} = \\frac{F_{\\max} - F_{\\min}}{F_{\\text{mean}}} \\times 100

For a well-designed 3-phase wave winding with max-torque commutation, ripple
should be well below 5 %.

Magpylib getFT usage
--------------------
``magpy.getFT(sources, targets)`` computes the magnetic force on each
*target* object due to the field of the *sources*.  In our convention:

* **sources** = magnet array (generates the field)
* **targets** = current-carrying Polyline conductors (experience Lorentz force)

The ``meshing`` attribute on each ``Polyline`` sets the number of
integration sub-segments used for the Lorentz force integral.  Higher values
increase accuracy but also computation time.  The default of 20 gives ≤ 1 mm
resolution on a 20 mm active conductor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

import magpylib as magpy

from pcbstatorgen.config import MagnetArrangement, MotorConfig
from pcbstatorgen.geometry.wave_winding import PhaseCoil, WaveWindingGenerator
from pcbstatorgen.magnetic.coil_model import CoilCurrentModel
from pcbstatorgen.magnetic.magnet_model import MagnetArray

__all__ = ["ForceResult", "ForceEvaluator"]

CommutationMode = Literal["max_torque", "phase_a_only"]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ForceResult:
    """Force sweep results across the mover travel range.

    All force arrays are in SI units (Newtons).

    Parameters
    ----------
    positions_m:
        Mover positions at which force was evaluated, shape ``(n,)`` [m].
    force_x_n:
        Total X (thrust) force at each position, shape ``(n,)`` [N].
    force_y_n:
        Total Y (lateral) force at each position, shape ``(n,)`` [N].
    force_z_n:
        Total Z (normal, pull-out) force at each position, shape ``(n,)`` [N].
    per_phase_force_x:
        Per-phase X thrust, shape ``(n, n_phases)`` [N].
    commutation:
        The commutation mode used for this result.
    currents_a:
        Applied peak current [A].
    """

    positions_m: np.ndarray
    force_x_n: np.ndarray
    force_y_n: np.ndarray
    force_z_n: np.ndarray
    per_phase_force_x: np.ndarray
    commutation: CommutationMode
    current_a: float

    @property
    def mean_thrust_n(self) -> float:
        """Mean X thrust force over the sweep [N]."""
        return float(np.mean(self.force_x_n))

    @property
    def peak_thrust_n(self) -> float:
        """Peak X thrust force [N]."""
        return float(np.max(self.force_x_n))

    @property
    def min_thrust_n(self) -> float:
        """Minimum X thrust force [N]."""
        return float(np.min(self.force_x_n))

    @property
    def ripple_pct(self) -> float:
        """Peak-to-peak force ripple as a percentage of mean thrust.

        A well-designed 3-phase wave winding with max-torque commutation
        should produce ripple < 5 %.
        """
        mean = self.mean_thrust_n
        if abs(mean) < 1e-12:
            return 0.0
        return float((self.peak_thrust_n - self.min_thrust_n) / abs(mean) * 100.0)

    @property
    def n_positions(self) -> int:
        """Number of sweep positions."""
        return len(self.positions_m)

    def summary(self) -> str:
        """Return a compact human-readable force summary."""
        return (
            f"ForceResult ({self.commutation}, I={self.current_a:.2f} A, "
            f"n={self.n_positions} positions)\n"
            f"  Mean thrust:   {self.mean_thrust_n * 1e3:.1f} mN\n"
            f"  Peak thrust:   {self.peak_thrust_n * 1e3:.1f} mN\n"
            f"  Min thrust:    {self.min_thrust_n * 1e3:.1f} mN\n"
            f"  Ripple:        {self.ripple_pct:.1f} %\n"
            f"  Mean lateral:  {float(np.mean(self.force_y_n)) * 1e3:.1f} mN\n"
            f"  Mean normal:   {float(np.mean(self.force_z_n)) * 1e3:.1f} mN"
        )


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class ForceEvaluator:
    """Evaluate thrust force across the mover travel range.

    Parameters
    ----------
    n_positions:
        Number of uniformly-spaced mover positions to evaluate.  Default: 50.
        More positions give a smoother ripple curve but take longer.
    meshing:
        Polyline meshing density passed to :class:`~CoilCurrentModel`.
        Default: 20.
    commutation:
        Commutation mode: ``'max_torque'`` (sinusoidal FOC) or
        ``'phase_a_only'``.  Default: ``'max_torque'``.
    layer_z_m:
        Z depth of the conductor plane [m].  0 = PCB top surface.

    Examples
    --------
    Quick evaluation (may take a few seconds)::

        from pcbstatorgen.magnetic.force_eval import ForceEvaluator
        from pcbstatorgen.geometry.wave_winding import WaveWindingGenerator

        gen = WaveWindingGenerator()
        coils = gen.generate(config)          # Phase A, B, C on layer 0

        ev = ForceEvaluator(n_positions=20)
        result = ev.evaluate(config, coils)
        print(result.summary())
    """

    def __init__(
        self,
        n_positions: int = 50,
        meshing: int = 20,
        commutation: CommutationMode = "max_torque",
        layer_z_m: float = 0.0,
    ) -> None:
        if n_positions < 2:
            raise ValueError(f"n_positions must be ≥ 2, got {n_positions}")
        if meshing < 1:
            raise ValueError(f"meshing must be ≥ 1, got {meshing}")
        self.n_positions = n_positions
        self.meshing = meshing
        self.commutation = commutation
        self.layer_z_m = layer_z_m
        self._phase_shift: float = 0.0
        self._calibrated: bool = False

    # ------------------------------------------------------------------
    # Self-calibration guard (PRODUCT_GOALS.md §4.C)
    # ------------------------------------------------------------------

    def _self_calibrate(
        self,
        config: MotorConfig,
        coils: list[PhaseCoil],
    ) -> None:
        """Newton's Third Law calibration guard.

        Evaluates a single test step at +0.1τ_p forward.  If the resulting
        mover force is negative, inverts phase currents (180° shift) to
        align the FOC electrical angle with positive mechanical motion.

        Also sets the sign convention: all returned forces are mover forces
        (``F_mover = -F_stator``) per PRODUCT_GOALS.md §4.C.
        """
        test_pos = 0.1 * config.pole_pitch_m
        self._phase_shift = 0.0
        currents = self._commutation_currents(
            config=config,
            mover_position_m=test_pos,
            n_phases=len(coils),
        )
        magnet_array = MagnetArray(config)
        coil_model = CoilCurrentModel(
            meshing=self.meshing,
            layer_z_m=self.layer_z_m,
        )
        magnets = magnet_array.build_collection(mover_position_m=test_pos)
        flat = coil_model.flat_polylines(
            coil_model.build_all_phases(coils, currents)
        )
        if flat:
            F, _ = magpy.getFT(magnets, flat)
            F = np.atleast_2d(F)
            f_mover_x = -float(F[:, 0].sum())
            if f_mover_x < 0:
                self._phase_shift = math.pi
            else:
                self._phase_shift = 0.0
        else:
            self._phase_shift = 0.0
        self._calibrated = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        config: MotorConfig,
        coils: list[PhaseCoil],
    ) -> ForceResult:
        """Sweep mover position from 0 to ``config.travel_m`` and compute force.

        Parameters
        ----------
        config:
            Motor configuration.
        coils:
            Phase coils from :class:`~WaveWindingGenerator`.  Must cover at
            least the active length region.  Typically the output of
            ``WaveWindingGenerator().generate(config)``.

        Returns
        -------
        ForceResult
        """
        # Self-calibration guard (PRODUCT_GOALS.md §4.C):
        # Test step at +0.1τ_p; if F_mover < 0, invert phase currents.
        if not self._calibrated:
            self._self_calibrate(config, coils)

        positions = np.linspace(0.0, config.travel_m, self.n_positions)
        magnet_array = MagnetArray(config)
        coil_model = CoilCurrentModel(
            meshing=self.meshing,
            layer_z_m=self.layer_z_m,
        )

        n_phases = len(coils)
        force_x = np.zeros(self.n_positions)
        force_y = np.zeros(self.n_positions)
        force_z = np.zeros(self.n_positions)
        per_phase_x = np.zeros((self.n_positions, n_phases))

        for i, pos in enumerate(positions):
            currents = self._commutation_currents(
                config=config,
                mover_position_m=pos,
                n_phases=n_phases,
            )
            magnets = magnet_array.build_collection(mover_position_m=pos)
            phase_sources = coil_model.build_all_phases(coils, currents)

            # Compute force on all conductors simultaneously
            flat = coil_model.flat_polylines(phase_sources)
            if not flat:
                continue

            F, _ = magpy.getFT(magnets, flat)  # F shape: (n_conductors, 3) or (3,)
            F = np.atleast_2d(F)               # ensure (n_conductors, 3)

            # Newton's Third Law: F_mover = -F_stator (PRODUCT_GOALS.md §4.C)
            force_x[i] = -float(F[:, 0].sum())
            force_y[i] = -float(F[:, 1].sum())
            force_z[i] = -float(F[:, 2].sum())

            # Per-phase breakdown
            idx = 0
            for p, src in enumerate(phase_sources):
                n_cond = len(src)
                per_phase_x[i, p] = -float(F[idx : idx + n_cond, 0].sum())
                idx += n_cond

        return ForceResult(
            positions_m=positions,
            force_x_n=force_x,
            force_y_n=force_y,
            force_z_n=force_z,
            per_phase_force_x=per_phase_x,
            commutation=self.commutation,
            current_a=config.max_current_a,
        )

    def evaluate_at(
        self,
        config: MotorConfig,
        coils: list[PhaseCoil],
        mover_position_m: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compute force and torque at a single mover position.

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            ``(F_total, T_total)`` — total force [N] and torque [N·m],
            each shape ``(3,)``.
        """
        # Ensure calibration is applied (PRODUCT_GOALS.md §4.C)
        if not self._calibrated:
            self._self_calibrate(config, coils)

        currents = self._commutation_currents(
            config=config,
            mover_position_m=mover_position_m,
            n_phases=len(coils),
        )
        magnet_array = MagnetArray(config)
        coil_model = CoilCurrentModel(
            meshing=self.meshing,
            layer_z_m=self.layer_z_m,
        )
        magnets = magnet_array.build_collection(mover_position_m=mover_position_m)
        flat = coil_model.flat_polylines(
            coil_model.build_all_phases(coils, currents)
        )
        F, T = magpy.getFT(magnets, flat)
        F = np.atleast_2d(F)
        T = np.atleast_2d(T)
        # Newton's Third Law: F_mover = -F_stator, T_mover = -T_stator
        return -F.sum(axis=0), -T.sum(axis=0)

    # ------------------------------------------------------------------
    # Commutation
    # ------------------------------------------------------------------

    def _commutation_currents(
        self,
        config: MotorConfig,
        mover_position_m: float,
        n_phases: int,
    ) -> list[float]:
        """Return the signed phase currents [A] for the given mover position.

        Parameters
        ----------
        config:
            Motor configuration.
        mover_position_m:
            Current mover position [m].
        n_phases:
            Number of phases.

        Returns
        -------
        list[float]
            Length ``n_phases``.  Signed currents in Amperes.
        """
        I_pk = config.max_current_a

        if self.commutation == "phase_a_only":
            return [I_pk] + [0.0] * (n_phases - 1)

        # max_torque: sinusoidal FOC
        # Electrical period = 2 × pole_pitch for all four MagnetArrangement values.
        # Our HALBACH implementation inserts X-polarised interleave magnets between
        # the standard alternating ±Z main magnets; the dominant Bz spatial period
        # at the PCB surface is still 2τ, not τ.  No period change is needed here.
        # (If a true 4-magnet equal-width Halbach were used — ↑→↑← with Z+ at both
        # x=0 and x=τ — the period would be τ and this formula would need updating.)
        # Phase shift is set dynamically by the self-calibration guard
        # (_self_calibrate) to align FOC electrical angle with positive motion.
        theta_e = 2.0 * math.pi * mover_position_m / (2.0 * config.pole_pitch_m) + self._phase_shift
        phase_offset = 2.0 * math.pi / n_phases  # 120° for 3-phase
        return [
            I_pk * math.sin(theta_e - p * phase_offset)
            for p in range(n_phases)
        ]

    @staticmethod
    def electrical_angle(config: MotorConfig, mover_position_m: float) -> float:
        """Electrical angle in radians for a given mover position.

        One full electrical cycle completes over **two pole pitches** for all
        four :class:`~pcbstatorgen.config.MagnetArrangement` values supported
        by this codebase.  See the module docstring of
        :mod:`pcbstatorgen.magnetic.magnet_model` for why the HALBACH
        arrangement does not require a different period here.

        Parameters
        ----------
        config:
            Motor configuration.
        mover_position_m:
            Mover position [m].

        Returns
        -------
        float
            Electrical angle [rad].
        """
        return 2.0 * math.pi * mover_position_m / (2.0 * config.pole_pitch_m)
