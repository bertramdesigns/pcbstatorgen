"""
pcbstatorgen.stackup.power
===========================
Estimates power consumption, thermal rise, and capacitor bank sizing for the
stator drive circuit and produces a :class:`~pcbstatorgen.config.PowerBudget`.

Model overview
--------------
The power model proceeds in three steps:

1. **DC resistance** — computes the total trace length for one phase using
   the :class:`~pcbstatorgen.geometry.wave_winding.WaveWindingGenerator` at
   the given layer count, then applies
   :func:`~pcbstatorgen.units.cu_resistance_per_length`.

2. **Temperature rise** — uses the IPC-2152 empirical formula for PCB copper
   conductors in free air.  The aggregate board temperature rise (from all
   phases dissipating simultaneously) is estimated using a PCB thermal
   resistance of 15 °C/W — appropriate for a 20 mm × 200 mm board with
   natural convection.

3. **Burst / capacitor sizing** — the burst current for rapid automation
   moves is sourced from a local capacitor bank to avoid drooping the supply
   rail.  The minimum bank is sized to supply the burst current for 100 ms
   with ≤ 10 % voltage droop.

Efficiency note
---------------
The mechanical efficiency of a short-stroke coreless PCB mover at rated
continuous current is typically 1–5 %.  Most electrical energy is dissipated
as heat even at full speed because the mover spends most of its time in
position-hold (zero velocity → zero mechanical output).
"""

from __future__ import annotations

import math

from pcbstatorgen.config import LinearMotorConfig, PowerBudget, StackupResult
from pcbstatorgen.units import cu_resistance_per_length, oz_to_m

__all__ = ["PowerEstimator"]

#: PCB thermal resistance [°C/W] — 20 mm × 200 mm board, natural convection.
_R_THERMAL_C_PER_W: float = 15.0

#: Burst duration used for capacitor sizing [s].
_T_BURST_S: float = 0.1  # 100 ms

#: Maximum acceptable voltage droop during burst as fraction of supply voltage.
_DROOP_FRACTION: float = 0.10  # 10 %

#: Approximate rated velocity for efficiency calculation [m/s].
_V_RATED_M_S: float = 0.10


class PowerEstimator:
    """Estimate drive-circuit power budget for a mover stator design.

    The estimator can work with or without a :class:`~pcbstatorgen.config.StackupResult`:

    * **With** ``StackupResult`` — uses actual per-layer trace widths and
      copper thicknesses from the layer optimiser.
    * **Without** — falls back to conservative defaults: trace width =
      ``2 × min_trace_m``, inner copper = 2 oz.

    Parameters
    ----------
    layers_per_phase:
        How many copper layers carry each phase.  When ``None`` (default),
        the estimator infers this from the ``StackupResult`` if provided,
        or uses 2 as a fallback.

    Examples
    --------
    Quick estimate without a stackup::

        from pcbstatorgen.stackup.power import PowerEstimator

        est = PowerEstimator()
        budget = est.estimate(config)
        print(budget.summary())

    With LayerOptimizer output::

        budget = est.estimate(config, stackup_result=stackup)
    """

    def __init__(self, layers_per_phase: int | None = None) -> None:
        if layers_per_phase is not None and layers_per_phase < 1:
            raise ValueError(
                f"layers_per_phase must be ≥ 1, got {layers_per_phase}"
            )
        self.layers_per_phase = layers_per_phase

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(
        self,
        config: LinearMotorConfig,
        stackup_result: StackupResult | None = None,
    ) -> PowerBudget:
        """Compute a :class:`~pcbstatorgen.config.PowerBudget`.

        Parameters
        ----------
        config:
            Linear motor configuration.
        stackup_result:
            Optional stackup from the LayerOptimizer.  If provided, actual
            per-layer trace widths and copper weights are used.

        Returns
        -------
        PowerBudget
        """
        trace_width_m, cu_thickness_m, lpp = self._trace_params(
            config, stackup_result
        )

        # Coil total length per layer per phase (active + end-turn)
        single_layer_length_m = self._single_layer_trace_length_m(config)
        total_length_m = single_layer_length_m * lpp

        # DC resistance per phase
        R_per_m = cu_resistance_per_length(trace_width_m, cu_thickness_m)
        R_phase = R_per_m * total_length_m

        # Continuous power — all phases on simultaneously
        I_cont = config.max_current_a
        P_cont = config.phases * I_cont ** 2 * R_phase

        # Burst current — scales linearly with force ratio
        if config.target_force_n > 0:
            I_burst = I_cont * (config.peak_force_n / config.target_force_n)
        else:
            I_burst = I_cont
        P_burst = config.phases * I_burst ** 2 * R_phase

        # Temperature rise (aggregate)
        delta_T = P_cont * _R_THERMAL_C_PER_W

        # Capacitor sizing
        delta_V = config.supply_voltage_v * _DROOP_FRACTION
        C_uf = max(
            0.0,
            (I_burst * config.phases * _T_BURST_S / delta_V) * 1e6,
        )

        # Mechanical efficiency at rated velocity
        P_mech = config.target_force_n * _V_RATED_M_S
        P_elec = config.supply_voltage_v * I_cont
        efficiency = min(100.0, (P_mech / P_elec * 100.0) if P_elec > 0 else 0.0)

        return PowerBudget(
            phase_resistance_ohm=R_phase,
            continuous_power_w=P_cont,
            burst_power_w=P_burst,
            temperature_rise_c=delta_T,
            capacitor_required_uf=C_uf,
            efficiency_pct=efficiency,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _trace_params(
        self,
        config: LinearMotorConfig,
        stackup_result: StackupResult | None,
    ) -> tuple[float, float, int]:
        """Return ``(trace_width_m, cu_thickness_m, layers_per_phase)``."""
        if self.layers_per_phase is not None:
            lpp = self.layers_per_phase
        elif stackup_result is not None:
            lpp = max(1, stackup_result.layer_count // config.phases)
        else:
            lpp = 2  # conservative fallback

        if stackup_result is not None:
            # Use inner-layer values (index 1) for the dominant resistance contribution
            idx = min(1, len(stackup_result.trace_widths_m) - 1)
            tw = stackup_result.trace_widths_m[idx]
            ct = stackup_result.cu_thickness_m[idx]
        else:
            # Conservative defaults: 2× min trace, 2 oz copper
            tw = config.min_trace_m * 2.0
            ct = oz_to_m(2.0)

        return tw, ct, lpp

    @staticmethod
    def _single_layer_trace_length_m(config: LinearMotorConfig) -> float:
        """Approximate total trace length per phase per layer [m].

        Uses the WaveWindingGenerator to compute the exact value for the
        SERPENTINE topology.  Other topologies are within ~15 % of this.
        """
        from pcbstatorgen.geometry.wave_winding import WaveWindingGenerator
        gen = WaveWindingGenerator()
        coils = gen.generate(config, layer_idx=0)
        if not coils:
            return 0.0
        # Average across all phases (they differ by at most 2 conductors)
        return sum(c.total_length_m for c in coils) / len(coils)
