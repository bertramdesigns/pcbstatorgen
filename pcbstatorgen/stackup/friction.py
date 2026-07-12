"""
pcbstatorgen.stackup.friction
==============================
Estimates mechanical friction for a mover assembly and produces a
:class:`~pcbstatorgen.config.FrictionBudget`.

Friction contributors
---------------------
For a motorised PCB-stator mover the main friction sources in descending
order of impact are:

1. **Bearing/guide friction** — ``µ_bearing × F_normal``.
   ``F_normal`` is the force the bearing rails must support perpendicular to
   the travel axis.  For a coreless PCB stator without ferromagnetic rails the
   magnetic normal force on the carriage is very small (no iron to attract).
   The dominant source of normal force is gravity (horizontal movers) or
   contact pre-load (vertical movers).  Pass a measured or estimated value.

2. **Flex-cable (FFC) drag** — empirically ≈ 20 mN per conductor for a
   standard 0.5 mm pitch FFC.  This contribution is significant for
   movers with many conductors (e.g., Alps / Bourns 26-conductor touch-
   sensitive movers).

3. **Wiper contact spring** — if the mover uses a resistive pot for
   position sensing the carbon wiper applies 30–100 mN of spring force
   over the full travel.  Non-contact sensing (magnetic encoder, optical)
   eliminates this term entirely.

4. **Cogging / reluctance detent** — near zero for coreless PCB stators
   (no iron in the stator → no reluctance variation).  Non-zero only
   when the optional steel back-iron introduces periodic flux leakage.

Bearing type reference
-----------------------

+-----------------------+------+-------------------------------------------------+
| Type                  | µ    | Notes                                           |
+=======================+======+=================================================+
| Plastic channel       | 0.25 | Consumer movers, budget mixers                  |
+-----------------------+------+-------------------------------------------------+
| PTFE-lined channel    | 0.12 | Standard DAW controllers                        |
+-----------------------+------+-------------------------------------------------+
| Linear ball bearing   | 0.003| Studio consoles, high-end custom designs        |
+-----------------------+------+-------------------------------------------------+
"""

from __future__ import annotations

from enum import Enum

from pcbstatorgen.config import FrictionBudget, LinearMotorConfig

__all__ = ["BearingType", "FrictionEstimator"]


class BearingType(Enum):
    """Mover linear bearing / guide type with associated friction coefficient."""

    PLASTIC_CHANNEL = "plastic_channel"
    """Moulded plastic guide channel.  µ ≈ 0.25.
    Common in budget consumer audio gear."""

    PTFE_LINED = "ptfe_lined"
    """PTFE-lined channel or shaft.  µ ≈ 0.12.
    Standard quality for DAW controllers and live sound desks."""

    BALL_BEARING = "ball_bearing"
    """Precision linear ball bearing (e.g., THK, IKO).  µ ≈ 0.003.
    Used in high-end studio consoles and custom broadcast equipment."""


#: Friction coefficient (µ) for each bearing type.
MU_BEARING: dict[BearingType, float] = {
    BearingType.PLASTIC_CHANNEL: 0.25,
    BearingType.PTFE_LINED: 0.12,
    BearingType.BALL_BEARING: 0.003,
}

#: Empirical FFC drag per conductor [N].
#: Measured for a standard 0.5 mm pitch 26-conductor FFC at mid-stroke.
_FFC_DRAG_PER_CONDUCTOR_N: float = 0.020

#: Wiper contact spring force [N].
_WIPER_CONTACT_N: float = 0.055


class FrictionEstimator:
    """Estimate mover mechanical friction and return a :class:`~pcbstatorgen.config.FrictionBudget`.

    The estimator computes bearing friction from a user-supplied (or zero)
    normal force and empirical models for cable drag and wiper contact.

    For coreless PCB stators without steel back-iron, the magnetic normal
    force on non-ferromagnetic guide rails is negligible and
    ``normal_force_n`` defaults to 0.  If back-iron is present, or if the
    guide rails have ferromagnetic inserts, measure the actual pull-in force
    or compute it from the field model and pass it explicitly.

    Parameters
    ----------
    bearing_type:
        Linear bearing / guide type.  See :class:`BearingType`.
    ffc_conductor_count:
        Number of FFC conductors in the flex cable(s) attached to the carriage.
        A typical touch-sensitive mover uses 26 conductors.  Set to 0 if no
        FFC is used.  Default: 26.
    has_wiper_contact:
        ``True`` if the mover uses a resistive potentiometer wiper for position
        sensing.  ``False`` (default) for non-contact sensing (encoder, optical,
        Hall effect).
    normal_force_n:
        Force perpendicular to the travel axis that the bearing must support [N].
        For coreless stators with non-magnetic rails: 0 N.
        For stators with steel back-iron attracting to a ferromagnetic guide: 5–15 N
        (measured).  Default: 0 N.
    cogging_n:
        Reluctance detent force [N].  Use 0 for coreless designs (default).

    Examples
    --------
    Ball-bearing mover with a 26-conductor FFC and magnetic encoder::

        from pcbstatorgen.stackup.friction import BearingType, FrictionEstimator

        est = FrictionEstimator(
            bearing_type=BearingType.BALL_BEARING,
            ffc_conductor_count=26,
            has_wiper_contact=False,
            normal_force_n=0.0,   # coreless, non-magnetic rails
        )
        budget = est.estimate()
        print(budget.summary())
    """

    def __init__(
        self,
        bearing_type: BearingType = BearingType.PTFE_LINED,
        ffc_conductor_count: int = 26,
        has_wiper_contact: bool = False,
        normal_force_n: float = 0.0,
        cogging_n: float = 0.0,
    ) -> None:
        if ffc_conductor_count < 0:
            raise ValueError(
                f"ffc_conductor_count must be ≥ 0, got {ffc_conductor_count}"
            )
        if normal_force_n < 0:
            raise ValueError(f"normal_force_n must be ≥ 0, got {normal_force_n}")
        if cogging_n < 0:
            raise ValueError(f"cogging_n must be ≥ 0, got {cogging_n}")

        self.bearing_type = bearing_type
        self.ffc_conductor_count = ffc_conductor_count
        self.has_wiper_contact = has_wiper_contact
        self.normal_force_n = normal_force_n
        self.cogging_n = cogging_n

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(self) -> FrictionBudget:
        """Compute a :class:`~pcbstatorgen.config.FrictionBudget`.

        Returns
        -------
        FrictionBudget
        """
        mu = MU_BEARING[self.bearing_type]
        bearing_n = mu * self.normal_force_n
        cable_n = _FFC_DRAG_PER_CONDUCTOR_N * self.ffc_conductor_count
        wiper_n = _WIPER_CONTACT_N if self.has_wiper_contact else 0.0

        return FrictionBudget(
            bearing_friction_n=bearing_n,
            cable_drag_n=cable_n,
            wiper_contact_n=wiper_n,
            cogging_n=self.cogging_n,
        )

    def estimate_for_config(self, config: LinearMotorConfig) -> FrictionBudget:
        """Estimate friction using ``config.friction_n`` as the total.

        Splits the configured ``friction_n`` proportionally across contributors
        as a starting point for the breakdown.  Useful for the Streamlit wizard
        when the user enters a total friction figure before breaking it down.

        Parameters
        ----------
        config:
            Linear motor configuration.

        Returns
        -------
        FrictionBudget
        """
        total = config.friction_n
        if total <= 0:
            return FrictionBudget(
                bearing_friction_n=0.0,
                cable_drag_n=0.0,
                wiper_contact_n=0.0,
                cogging_n=0.0,
            )

        # Rough fractional split based on bearing type
        bearing_fraction = {
            BearingType.PLASTIC_CHANNEL: 0.70,
            BearingType.PTFE_LINED: 0.55,
            BearingType.BALL_BEARING: 0.25,
        }[self.bearing_type]
        cable_fraction = 0.20
        wiper_fraction = 0.10 if self.has_wiper_contact else 0.0
        cogging_fraction = 0.05

        # Normalise (fractions may not sum to 1.0)
        total_fraction = bearing_fraction + cable_fraction + wiper_fraction + cogging_fraction
        sf = total / total_fraction

        return FrictionBudget(
            bearing_friction_n=bearing_fraction * sf,
            cable_drag_n=cable_fraction * sf,
            wiper_contact_n=wiper_fraction * sf,
            cogging_n=cogging_fraction * sf,
        )

    # ------------------------------------------------------------------
    # Class methods
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        config: LinearMotorConfig,
        bearing_type: BearingType = BearingType.PTFE_LINED,
        ffc_conductor_count: int = 26,
        has_wiper_contact: bool = False,
    ) -> "FrictionEstimator":
        """Construct an estimator using back-iron config to set normal force.

        If the config has ``back_iron_thickness_m > 0`` a conservative
        non-zero normal force is used; otherwise normal force is zero.

        Parameters
        ----------
        config:
            Linear motor configuration.
        bearing_type:
            See :class:`BearingType`.
        ffc_conductor_count:
            FFC conductors.
        has_wiper_contact:
            Wiper contact flag.
        """
        # For coreless stators without back-iron: normal force ≈ 0.
        # With back-iron: conservative estimate based on friction_n field.
        # A fully rigorous estimate would use FT() from force_eval.py.
        if config.back_iron_thickness_m > 0:
            # Rough: back-iron magnets attract to stator back-iron equivalently;
            # force is proportional to magnet area and remanence squared.
            # Use 5 N as a conservative default — user should measure and override.
            normal_force = 5.0
        else:
            normal_force = 0.0

        return cls(
            bearing_type=bearing_type,
            ffc_conductor_count=ffc_conductor_count,
            has_wiper_contact=has_wiper_contact,
            normal_force_n=normal_force,
        )
