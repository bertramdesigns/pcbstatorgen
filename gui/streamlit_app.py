"""
gui/streamlit_app.py — PCB Stator Generator Dashboard
======================================================
Run with:
    streamlit run gui/streamlit_app.py

The UI has two modes selectable from the sidebar:

  🧙 Wizard   — 6-step goal-first flow.  Start here if you're not a motor
                expert.  Answer plain-English questions about what you want
                the motor to DO; the tool derives the technical parameters.

  ⚙️  Advanced — All parameters exposed as direct controls.  For power users
                who know motor theory and want to tweak specific values.

Both modes build the same LinearMotorConfig, which drives the output tabs
(Coil Geometry, Magnet Field, Force Preview, Write to KiCad).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pcbstatorgen.config import (
    CoilTopology,
    LinearMotorConfig,
    MagnetArrangement,
    StackupResult,
)
from pcbstatorgen.stackup.friction import BearingType, FrictionEstimator
from pcbstatorgen.stackup.height_stack import HeightStackCalculator
from pcbstatorgen.stackup.power import PowerEstimator
from pcbstatorgen.units import mm, mils_to_m, oz_to_m, m_to_mm, skin_depth_m

# ─────────────────────────────────────────────────────────────────────────────
# Page config (must be first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="pcbstatorgen",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Pre-filled defaults for each common fader application type
_FADER_PRESETS = {
    "Studio 100 mm": dict(travel_mm=100.0, mass_g=18, board_width_mm=22, ffc=26),
    "Studio 75 mm":  dict(travel_mm=75.0,  mass_g=15, board_width_mm=20, ffc=26),
    "Live sound 60 mm": dict(travel_mm=60.0, mass_g=12, board_width_mm=18, ffc=20),
    "Custom":         dict(travel_mm=75.0,  mass_g=15, board_width_mm=20, ffc=26),
}

# Feel overhead (extra continuous force for haptic quality) in Newtons
_FEEL_FORCE_N = {"Light": 0.040, "Medium": 0.120, "Heavy": 0.280, "Active spring": 0.480}

# Peak acceleration for burst moves, in m/s²
_SPEED_ACCEL = {"Slow (0.05 m/s)": 0.5, "Normal (0.10 m/s)": 2.0, "Fast (0.20 m/s)": 5.0}

# Rough cost for 5 boards at JLCPCB standard per layer count
_COST_USD = {4: 12, 6: 22, 8: 38, 10: 60, 12: 85}

# Arrangement force multipliers vs ALTERNATING baseline
_ARR_MULT = {
    MagnetArrangement.ALTERNATING: 1.00,
    MagnetArrangement.HALBACH: 1.43,
    MagnetArrangement.ALTERNATING_BACK_IRON: 1.42,
    MagnetArrangement.HALBACH_BACK_IRON: 1.68,
}

# Topology force multipliers vs SERPENTINE baseline
_TOPO_MULT = {
    CoilTopology.SERPENTINE: 1.00,
    CoilTopology.CONCENTRATED: 0.95,
    CoilTopology.RHOMBIC: 0.87,
    CoilTopology.SPIRAL: 0.60,
}

# ─────────────────────────────────────────────────────────────────────────────
# Session state initialisation
# ─────────────────────────────────────────────────────────────────────────────

_WIZ_DEFAULTS: dict = {
    "ui_mode": "wizard",
    "wizard_step": 0,
    # Step 0
    "fader_preset": "Studio 75 mm",
    "bearing_label": "PTFE-lined",
    # Step 1
    "height_budget_mm": 8.0,
    "supply_v": 5.0,
    "max_current_a": 1.0,
    # Step 2
    "coil_topology": CoilTopology.SERPENTINE,
    # Step 3
    "magnet_arrangement": MagnetArrangement.ALTERNATING,
    "back_iron_mm": 0.0,
    "magnet_width_mm": 10.0,
    # Step 4
    "desired_feel": "Medium",
    "automation_speed": "Normal (0.10 m/s)",
    # Step 5
    "manufacturer": "JLCPCB Standard",
    "layer_count_override": None,
    # Advanced-mode overrides
    "adv_travel_mm": 75.0,
    "adv_board_width_mm": 20.0,
    "adv_magnet_pitch_mm": 12.0,
    "adv_magnet_h_mm": 4.0,
    "adv_magnet_l_mm": 10.0,
    "adv_remanence_t": 1.35,
    "adv_phases": 3,
    "adv_target_n": 0.25,
    "adv_max_layers": 12,
    "adv_min_trace_mil": 5.0,
    "adv_min_space_mil": 5.0,
    "adv_air_gap_mm": 0.5,
    "adv_board_width_mm": 20.0,
    # Wizard state
    "wizard_started": False,
    # Gap between magnets (derived: pitch = width + gap)
    "gap_between_magnets_mm": 2.0,
}

for k, v in _WIZ_DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────

def eli5(text: str) -> None:
    st.caption(f"💡 {text}")


def badge(value: float, good: float, warn: float, higher_is_better: bool = True) -> str:
    if higher_is_better:
        return "🟢" if value >= good else ("🟡" if value >= warn else "🔴")
    else:
        return "🟢" if value <= good else ("🟡" if value <= warn else "🔴")


def _bearing_type_from_label(label: str) -> BearingType:
    return {
        "Plastic channel": BearingType.PLASTIC_CHANNEL,
        "PTFE-lined":      BearingType.PTFE_LINED,
        "Ball bearing":    BearingType.BALL_BEARING,
    }.get(label, BearingType.PTFE_LINED)


def _estimate_force_n(config: LinearMotorConfig, n_layers: int) -> float:
    """Quick analytical force estimate — good enough for the wizard comparison table."""
    try:
        hz = HeightStackCalculator()
        bz_peak = hz.field_at_gap(config, config.air_gap_m)
        bz_mean = bz_peak * 0.55  # average of |sin| over a half-cycle
        # active conductors: approx active_length / pole_pitch
        n_cond = config.active_length_m / config.pole_pitch_m
        layers_per_phase = n_layers // config.phases
        F = (config.max_current_a * config.board_width_m * bz_mean
             * n_cond * layers_per_phase
             * _ARR_MULT.get(config.magnet_arrangement, 1.0)
             * _TOPO_MULT.get(config.coil_topology, 1.0))
        return max(0.0, float(F))
    except Exception:
        return 0.0


def build_config_from_wizard() -> LinearMotorConfig | None:
    """Assemble a LinearMotorConfig from all wizard session-state values."""
    try:
        preset = _FADER_PRESETS.get(st.session_state["fader_preset"],
                                     _FADER_PRESETS["Studio 75 mm"])
        bearing_label = st.session_state["bearing_label"]
        feel          = st.session_state["desired_feel"]
        speed         = st.session_state["automation_speed"]
        arrangement   = st.session_state["magnet_arrangement"]
        back_iron_m   = mm(st.session_state["back_iron_mm"])
        mw            = mm(st.session_state["magnet_width_mm"])
        gap_m         = mm(st.session_state.get("gap_between_magnets_mm", 2.0))
        pole_pitch_m  = mw + gap_m                        # pitch = width + gap
        height_budget = mm(st.session_state["height_budget_mm"])
        supply_v      = st.session_state["supply_v"]
        max_i         = st.session_state["max_current_a"]
        coil_topo     = st.session_state["coil_topology"]
        n_layers      = st.session_state.get("layer_count_override") or 6
        board_width_m = mm(st.session_state.get("board_width_override_mm",
                                                  preset["board_width_mm"]))

        travel_m  = mm(preset["travel_mm"])
        mass_kg   = preset["mass_g"] / 1000.0
        ffc_count = preset["ffc"]

        # Derive air gap from height budget
        hz_calc = HeightStackCalculator()
        # Height stack without air gap: PCB + Cu + mask + magnets + back_iron + tol
        other_stack = (0.0016 + oz_to_m(1.0) + 20e-6
                       + mm(4.0) + back_iron_m + mm(0.3))
        air_gap_m = max(mm(0.2), height_budget - other_stack)

        # Friction estimate
        bearing_type = _bearing_type_from_label(bearing_label)
        est = FrictionEstimator(bearing_type=bearing_type,
                                ffc_conductor_count=ffc_count,
                                has_wiper_contact=False)
        friction_budget = est.estimate()
        friction_n      = friction_budget.total_n

        # Force target from feel + accel
        feel_n   = _FEEL_FORCE_N.get(feel, 0.12)
        accel    = _SPEED_ACCEL.get(speed, 2.0)
        accel_n  = mass_kg * accel
        target_n = friction_n * 1.3 + feel_n
        peak_n   = max(target_n, friction_n + accel_n + feel_n) * 1.25

        return LinearMotorConfig(
            name=f"wizard-{preset['travel_mm']:.0f}mm",
            travel_m=travel_m,
            magnet_dims_m=(mw, mm(10), mm(4)),
            magnet_count=10,
            magnet_pitch_m=pole_pitch_m,            # width + gap
            magnet_arrangement=arrangement,
            back_iron_thickness_m=back_iron_m,
            coil_topology=coil_topo,
            phases=3,
            target_force_n=round(target_n, 3),
            peak_force_n=round(peak_n, 3),
            friction_n=round(friction_n, 4),
            carriage_mass_kg=mass_kg,
            max_current_a=max_i,
            supply_voltage_v=supply_v,
            min_trace_m=mils_to_m(5),
            min_space_m=mils_to_m(5),
            min_via_drill_m=mm(0.2),
            min_via_annular_ring_m=mm(0.1),
            board_width_m=board_width_m,
            air_gap_m=air_gap_m,
            max_layers=max(n_layers, 4),
            pcb_thickness_m=0.0016,
            capacitor_bank_uf=1000.0,
        )
    except Exception as exc:
        st.error(f"Configuration error: {exc}")
        return None


def build_config_from_advanced() -> LinearMotorConfig | None:
    """Build config from the Advanced mode sliders in session state."""
    try:
        s = st.session_state
        return LinearMotorConfig(
            travel_m=mm(s["adv_travel_mm"]),
            magnet_dims_m=(mm(s["magnet_width_mm"]),
                           mm(s["adv_magnet_l_mm"]),
                           mm(s["adv_magnet_h_mm"])),
            magnet_count=10,
            magnet_pitch_m=mm(s["adv_magnet_pitch_mm"]),
            magnet_remanence_t=s["adv_remanence_t"],
            magnet_arrangement=s["magnet_arrangement"],
            back_iron_thickness_m=mm(s["back_iron_mm"]),
            coil_topology=s["coil_topology"],
            phases=s["adv_phases"],
            target_force_n=s["adv_target_n"],
            peak_force_n=max(s["adv_target_n"], s["adv_target_n"] * 2),
            max_current_a=s["max_current_a"],
            supply_voltage_v=s["supply_v"],
            min_trace_m=mils_to_m(s["adv_min_trace_mil"]),
            min_space_m=mils_to_m(s["adv_min_space_mil"]),
            min_via_drill_m=mm(0.2),
            min_via_annular_ring_m=mm(0.1),
            board_width_m=mm(s["adv_board_width_mm"]),
            air_gap_m=mm(s["adv_air_gap_mm"]),
            max_layers=s["adv_max_layers"],
        )
    except Exception as exc:
        st.error(f"Configuration error: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚡ pcbstatorgen")
    st.caption("PCB stator generator for linear coreless motors")
    st.divider()

    mode = st.radio(
        "Mode",
        ["🧙 Wizard", "⚙️ Advanced"],
        index=0 if st.session_state["ui_mode"] == "wizard" else 1,
        help="Wizard: answer goal-focused questions. Advanced: direct parameter control.",
    )
    st.session_state["ui_mode"] = "wizard" if "Wizard" in mode else "advanced"
    st.divider()
    st.caption(
        "Wizard: start here if you're new to motor design. "
        "Advanced: full control for experienced users."
    )

# ─────────────────────────────────────────────────────────────────────────────
# Wizard renderer
# ─────────────────────────────────────────────────────────────────────────────

_STEP_TITLES = [
    "1 / 6 — Application Profile",
    "2 / 6 — Physical Envelope",
    "3 / 6 — Coil Topology",
    "4 / 6 — Magnet Arrangement",
    "5 / 6 — Force and Feel",
    "6 / 6 — PCB Tier & Layer Count",
]
_N_STEPS = len(_STEP_TITLES)


def _nav_buttons(step: int) -> int:
    """Render Back / Next buttons; return the new step index."""
    col_b, col_spacer, col_n = st.columns([1, 4, 1])
    if step > 0 and col_b.button("← Back", use_container_width=True):
        return step - 1
    if step < _N_STEPS - 1 and col_n.button("Next →", type="primary", use_container_width=True):
        return step + 1
    return step


def render_wizard() -> LinearMotorConfig | None:
    # ── Welcome / landing screen ────────────────────────────────────────────
    if not st.session_state.get("wizard_started", False):
        st.markdown("## Welcome to pcbstatorgen")
        st.markdown(
            "This tool designs a **linear coreless PCB stator** for a motorised "
            "fader — the kind used in studio mixing consoles and DAW controllers.  "
            "Answer a few plain-English questions and it will work out all the "
            "motor parameters, preview the magnetic field and force, then write "
            "the copper traces directly to your KiCad 10 PCB."
        )
        st.info(
            "**You'll need to know:**\n"
            "- What size fader you're building (60 mm / 75 mm / 100 mm)\n"
            "- How much total height is available inside your product\n"
            "- What power supply voltage and current limit your drive circuit has\n\n"
            "That's it — the wizard works out everything else."
        )
        col_start, _ = st.columns([1, 3])
        if col_start.button("🚀  Start the wizard →", type="primary", use_container_width=True):
            st.session_state["wizard_started"] = True
            st.session_state["wizard_step"] = 0
            st.rerun()
        st.divider()
        st.caption(
            "💡 Prefer to set every parameter yourself?  "
            "Switch to **⚙️ Advanced** mode in the sidebar."
        )
        return None

    # ── Step rendering ───────────────────────────────────────────────────────
    step = st.session_state["wizard_step"]
    st.progress((step + 1) / _N_STEPS, text=_STEP_TITLES[step])
    st.divider()

    if step == 0:
        _step0_application()
    elif step == 1:
        _step1_envelope()
    elif step == 2:
        _step2_coil_topology()
    elif step == 3:
        _step3_magnet_arrangement()
    elif step == 4:
        _step4_force_and_feel()
    elif step == 5:
        _step5_pcb_tier()

    st.divider()
    new_step = _nav_buttons(step)
    if new_step != step:
        st.session_state["wizard_step"] = new_step
        st.rerun()

    # Show review card once all steps are visited
    if step == _N_STEPS - 1:
        config = build_config_from_wizard()
        if config:
            _render_review_card(config)
            return config
    return build_config_from_wizard()


def _step0_application() -> None:
    st.subheader("What are you building?")
    eli5(
        "Start by picking your fader type. This sets the travel distance, "
        "carriage weight, and cable count — all the mechanical facts that don't change."
    )

    col1, col2 = st.columns(2)
    with col1:
        preset_label = st.selectbox(
            "Fader application",
            list(_FADER_PRESETS.keys()),
            index=list(_FADER_PRESETS.keys()).index(st.session_state["fader_preset"]),
        )
        st.session_state["fader_preset"] = preset_label
        preset = _FADER_PRESETS[preset_label]

        st.metric("Travel", f"{preset['travel_mm']:.0f} mm")
        st.metric("Carriage mass (est.)", f"{preset['mass_g']} g")
        st.metric("FFC conductors", f"{preset['ffc']}")

    with col2:
        bearing_label = st.radio(
            "Guide rail / bearing type",
            ["Plastic channel", "PTFE-lined", "Ball bearing"],
            index=["Plastic channel", "PTFE-lined", "Ball bearing"].index(
                st.session_state["bearing_label"]
            ),
        )
        st.session_state["bearing_label"] = bearing_label

        bearing_type = _bearing_type_from_label(bearing_label)
        mu = {"Plastic channel": 0.25, "PTFE-lined": 0.12, "Ball bearing": 0.003}[bearing_label]
        eli5({
            "Plastic channel": "Budget guide channels. More friction but cheap and common.",
            "PTFE-lined": "PTFE-coated channels. Good balance — standard for DAW controllers.",
            "Ball bearing": "Precision steel ball bearing. Very low friction. Used in top-tier consoles.",
        }[bearing_label])
        st.metric("Friction coefficient µ", f"{mu}")

    # Live friction preview
    est = FrictionEstimator(
        bearing_type=bearing_type,
        ffc_conductor_count=preset["ffc"],
        has_wiper_contact=False,
    )
    fb = est.estimate()
    st.divider()
    st.caption("**Estimated friction from this configuration:**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bearing friction", f"{fb.bearing_friction_n*1e3:.0f} mN",
              help="µ × magnetic normal force (≈0 for coreless without back-iron)")
    c2.metric("Cable drag", f"{fb.cable_drag_n*1e3:.0f} mN",
              help=f"~20 mN/conductor × {preset['ffc']} conductors")
    c3.metric("Total friction", f"{fb.total_n*1e3:.0f} mN")
    c4.metric("Min. drive force", f"{fb.minimum_drive_force_n*1e3:.0f} mN",
              help="Total × 1.3 safety margin — the motor must exceed this just to start moving")


def _step1_envelope() -> None:
    st.subheader("How much space do you have?")
    eli5(
        "These are the hard physical limits for your design — you can't trade "
        "them against each other. Set them from your product housing dimensions."
    )

    col1, col2 = st.columns(2)
    with col1:
        height = st.slider(
            "Total height budget — PCB + magnets + everything (mm)",
            min_value=5.0, max_value=20.0,
            value=st.session_state["height_budget_mm"], step=0.5,
        )
        st.session_state["height_budget_mm"] = height
        eli5(
            "Measure inside your product housing from the PCB mounting surface "
            "to the highest point of the magnet assembly."
        )

        supply_v = st.selectbox(
            "Power supply voltage",
            [3.3, 5.0, 9.0, 12.0],
            index=[3.3, 5.0, 9.0, 12.0].index(st.session_state["supply_v"])
            if st.session_state["supply_v"] in [3.3, 5.0, 9.0, 12.0] else 1,
            format_func=lambda v: f"{v:.1f} V",
        )
        st.session_state["supply_v"] = float(supply_v)

        max_i = st.selectbox(
            "Maximum continuous current per phase",
            [0.5, 1.0, 1.5, 2.0],
            index=[0.5, 1.0, 1.5, 2.0].index(st.session_state["max_current_a"])
            if st.session_state["max_current_a"] in [0.5, 1.0, 1.5, 2.0] else 1,
            format_func=lambda a: f"{a:.1f} A",
        )
        st.session_state["max_current_a"] = float(max_i)
        eli5("Set by your gate driver IC's current rating, not by what you think you need. Check the datasheet.")

        # Board width override (defaults to preset value)
        preset = _FADER_PRESETS.get(st.session_state["fader_preset"],
                                     _FADER_PRESETS["Studio 75 mm"])
        board_w = st.number_input(
            "Board width (mm)",
            min_value=1.0, max_value=100.0,
            value=float(st.session_state.get("board_width_override_mm",
                                              preset["board_width_mm"])),
            step=0.5, format="%.1f",
            help="PCB dimension perpendicular to the travel axis. Min 1 mm.",
        )
        st.session_state["board_width_override_mm"] = board_w
        eli5("How wide the PCB is (the dimension the coils cross). "
             "Usually set by the magnet length plus a few mm of edge clearance.")

    with col2:
        # Height stack diagram
        budget_m = mm(height)
        hz = HeightStackCalculator()
        other_stack = (0.0016 + oz_to_m(1.0) + 20e-6
                       + mm(4.0)
                       + mm(st.session_state["back_iron_mm"])
                       + mm(0.3))
        air_gap = max(mm(0.2), budget_m - other_stack)
        air_gap_mm = m_to_mm(air_gap)
        fits = air_gap > mm(0.2)

        st.markdown("**Height stack preview**")
        stack_items = [
            ("PCB (FR4)",         1.6,  "#2c3e50"),
            ("Outer Cu (1 oz)",   0.035,"#f39c12"),
            ("Solder mask",       0.02, "#27ae60"),
            ("Air gap",           air_gap_mm, "#3498db"),
            ("Magnets (N44H)",    4.0,  "#e74c3c"),
            ("Tolerance",         0.3,  "#95a5a6"),
        ]
        total_shown = sum(t for _, t, _ in stack_items)
        fig, ax = plt.subplots(figsize=(3, 4))
        y = 0
        for label, thick, color in stack_items:
            ax.barh(y, thick, left=0, height=0.8, color=color, alpha=0.85)
            ax.text(thick + 0.05, y, f"{label} ({thick:.2f} mm)", va="center", fontsize=7)
            y += 1
        ax.set_xlim(0, max(height, total_shown) * 1.5)
        ax.set_yticks([])
        ax.set_xlabel("mm")
        ax.set_title(f"Total: {total_shown:.1f} mm / {height:.1f} mm budget", fontsize=9)
        ax.axvline(height, color="red", linewidth=1.5, linestyle="--", label="Budget")
        ax.legend(fontsize=7)
        fig.tight_layout()
        st.pyplot(fig, use_container_width=False)
        plt.close(fig)

        icon = badge(air_gap_mm, 0.4, 0.2, higher_is_better=True)
        st.metric(f"Resulting air gap {icon}", f"{air_gap_mm:.2f} mm",
                  help="Smaller gap = more force (exponential relationship)")
        if air_gap_mm < 0.2:
            st.error("Air gap < 0.2 mm — too tight for assembly. Increase height budget or reduce magnet size.")
        elif air_gap_mm < 0.35:
            st.warning("Air gap < 0.35 mm — requires precision ball-bearing rails and careful assembly.")


def _step2_coil_topology() -> None:
    st.subheader("What coil pattern should the PCB use?")
    eli5(
        "This is the shape of the copper traces on the stator PCB. "
        "Different shapes have different trade-offs between force, ripple, and simplicity."
    )

    topos = [
        (CoilTopology.SERPENTINE,   "🌊 Serpentine",    "Continuous zigzag",
         "Highest force density. The recommended choice for production designs.",
         "~100% force", "~3% ripple", "Recommended"),
        (CoilTopology.CONCENTRATED, "▭ Straight / Rectangular", "Individual rectangular coil loops",
         "Simple and easy to understand. Good for first prototypes.",
         "~95% force", "~8% ripple", "Prototype"),
        (CoilTopology.RHOMBIC,      "◇ Rhombic / Diamond", "Angled active conductors",
         "Naturally sinusoidal coupling → lower force ripple without extra layers.",
         "~87% force", "~4% ripple", "Low-ripple"),
        (CoilTopology.SPIRAL,       "🌀 Spiral", "Flat Archimedean spirals",
         "Best suited for disk (axial flux) motors. Linear support is exploratory.",
         "~60% force", "~5% ripple", "Axial / Explore"),
    ]

    selected_topo = st.session_state["coil_topology"]
    cols = st.columns(4)
    for col, (topo, title, subtitle, desc, force_str, ripple_str, tag) in zip(cols, topos):
        is_selected = (topo == selected_topo)
        border_color = "#3498db" if is_selected else "#ddd"
        with col:
            st.markdown(
                f"""<div style="border:2px solid {border_color}; border-radius:8px;
                    padding:10px; min-height:200px; background:{'#eaf4fb' if is_selected else 'white'}">
                <b>{title}</b><br>
                <small style="color:#888">{subtitle}</small><br><br>
                <small>{desc}</small><br><br>
                <span style="background:#e8e8e8; padding:2px 6px; border-radius:4px; font-size:11px">
                    {force_str}</span>
                <span style="background:#e8e8e8; padding:2px 6px; border-radius:4px; font-size:11px">
                    {ripple_str}</span><br>
                <small style="color:#3498db">{tag}</small>
                </div>""",
                unsafe_allow_html=True,
            )
            if st.button(
                "✓ Select" if is_selected else "Select",
                key=f"topo_{topo.value}",
                type="primary" if is_selected else "secondary",
                use_container_width=True,
            ):
                st.session_state["coil_topology"] = topo
                st.rerun()

    if selected_topo == CoilTopology.SPIRAL:
        st.info(
            "ℹ️ Spiral coils require **layer pairs** (the trace spirals inward on Layer N, "
            "transitions via a centre via, then spirals out on Layer N+1). "
            "Full production support is coming with the axial motor phase."
        )


def _step3_magnet_arrangement() -> None:
    st.subheader("How should the magnets be arranged?")
    eli5(
        "The arrangement determines how much magnetic field reaches the PCB coil. "
        "More field = more force. But some options add height or cost."
    )

    arrangements = [
        (MagnetArrangement.ALTERNATING,
         "Simple alternating poles",
         "Alternating N-S-N-S. Cheapest and easiest.",
         1.00, 0.0, "$"),
        (MagnetArrangement.HALBACH,
         "Halbach array",
         "Interleaved sideways magnets concentrate all flux toward the PCB. No height penalty.",
         1.43, 0.0, "$$"),
        (MagnetArrangement.ALTERNATING_BACK_IRON,
         "Simple + steel back-iron",
         "A steel plate on the rear of the magnets redirects backward flux. +1 mm height.",
         1.42, 1.0, "$"),
        (MagnetArrangement.HALBACH_BACK_IRON,
         "Halbach + back-iron",
         "Best of both worlds. Maximum force density. +1 mm height.",
         1.68, 1.0, "$$"),
    ]

    selected_arr = st.session_state["magnet_arrangement"]
    for arr, title, desc, mult, extra_mm, cost in arrangements:
        is_sel = (arr == selected_arr)
        icon = "✅" if is_sel else "○"
        col_a, col_b, col_c, col_d, col_e = st.columns([0.5, 3, 2, 1.5, 1])
        col_a.markdown(f"**{icon}**")
        col_b.markdown(f"**{title}**  \n*{desc}*")
        col_c.markdown(f"Force multiplier: **{mult:.2f}×**")
        col_d.markdown(f"Height: {'baseline' if extra_mm == 0 else f'+{extra_mm:.0f} mm'}")
        col_e.markdown(f"Cost tier: **{cost}**")
        if col_a.button("", key=f"arr_{arr.value}", help=f"Select {title}") or (
            st.button(
                "Use this",
                key=f"arr_btn_{arr.value}",
                type="primary" if is_sel else "secondary",
            )
        ):
            st.session_state["magnet_arrangement"] = arr
            if extra_mm > 0:
                st.session_state["back_iron_mm"] = extra_mm
            else:
                st.session_state["back_iron_mm"] = 0.0
            st.rerun()
        st.divider()

    # Magnet size — width + gap inputs
    st.subheader("Magnet size")
    col_mw, col_gap = st.columns(2)

    with col_mw:
        mw = st.number_input(
            "Magnet width along travel axis (mm)",
            min_value=1.0,
            max_value=50.0,
            value=float(st.session_state["magnet_width_mm"]),
            step=0.1,
            format="%.2f",
            help="Width of each magnet in the direction the fader moves",
        )
        st.session_state["magnet_width_mm"] = mw
        eli5(
            "How wide each magnet is (measured along the travel direction). "
            "Wider magnets give a stronger field but leave less room between them."
        )

    with col_gap:
        gap = st.number_input(
            "Distance between magnets (mm)",
            min_value=0.0,
            max_value=20.0,
            value=float(st.session_state.get("gap_between_magnets_mm", 2.0)),
            step=0.1,
            format="%.2f",
            help="0 = edge-to-edge (magnets touching). Larger gap allows a Halbach interleave magnet.",
        )
        st.session_state["gap_between_magnets_mm"] = gap
        eli5(
            "The gap between adjacent magnets. "
            "Zero is fine (edge-to-edge). A gap ≥ 2 mm is needed to fit a "
            "Halbach interleave magnet for a field boost."
        )

    pole_pitch = mw + gap
    st.caption(
        f"Pole pitch (magnet width + gap): **{pole_pitch:.2f} mm** — "
        f"this is the spatial period of the magnetic field."
    )
    if selected_arr in (MagnetArrangement.HALBACH, MagnetArrangement.HALBACH_BACK_IRON) and gap < 1.0:
        st.warning(
            f"⚠️ Gap = {gap:.1f} mm is very small for a Halbach array. "
            "The interleave magnets need at least ~1 mm width to be effective. "
            "Consider increasing the gap or switching to a simpler arrangement."
        )


def _step4_force_and_feel() -> None:
    st.subheader("How should the fader feel?")
    eli5(
        "You're defining the USER EXPERIENCE here, not the motor specs. "
        "The tool converts your answers to the minimum force the motor must produce."
    )

    col1, col2 = st.columns(2)
    with col1:
        feel = st.radio(
            "Tactile resistance under the operator's hand",
            list(_FEEL_FORCE_N.keys()),
            index=list(_FEEL_FORCE_N.keys()).index(st.session_state["desired_feel"]),
        )
        st.session_state["desired_feel"] = feel
        eli5({
            "Light":  "Moves with almost no resistance. Like sliding on glass.",
            "Medium": "Gentle push. Standard for DAW controllers and broadcast desks.",
            "Heavy":  "Deliberate resistance. Professional studio console feel.",
            "Active spring": "The motor actively resists with a configurable spring effect. Used in haptic faders.",
        }[feel])

    with col2:
        speed = st.radio(
            "How fast should automation move the fader?",
            list(_SPEED_ACCEL.keys()),
            index=list(_SPEED_ACCEL.keys()).index(st.session_state["automation_speed"]),
        )
        st.session_state["automation_speed"] = speed
        eli5({
            "Slow (0.05 m/s)":   "Slow fades for gentle automation. Enough for most mixing tasks.",
            "Normal (0.10 m/s)": "Standard speed. Comfortable for live show recall.",
            "Fast (0.20 m/s)":   "Fast snap-to-position. Used in rapid cue switching.",
        }[speed])

    # Live friction breakdown
    st.divider()
    preset  = _FADER_PRESETS.get(st.session_state["fader_preset"],
                                  _FADER_PRESETS["Studio 75 mm"])
    bearing = _bearing_type_from_label(st.session_state["bearing_label"])
    est     = FrictionEstimator(bearing_type=bearing,
                                ffc_conductor_count=preset["ffc"],
                                has_wiper_contact=False)
    fb      = est.estimate()
    feel_n  = _FEEL_FORCE_N.get(feel, 0.12)
    mass_kg = preset["mass_g"] / 1000.0
    accel_n = mass_kg * _SPEED_ACCEL.get(speed, 2.0)
    min_drive = fb.total_n * 1.3
    target_n  = min_drive + feel_n
    peak_n    = max(target_n, fb.total_n + accel_n + feel_n) * 1.25

    st.markdown("**Force budget breakdown:**")
    cols = st.columns(5)
    cols[0].metric("Bearing friction",  f"{fb.bearing_friction_n*1e3:.0f} mN")
    cols[1].metric("Cable drag",        f"{fb.cable_drag_n*1e3:.0f} mN")
    cols[2].metric("Feel overhead",     f"{feel_n*1e3:.0f} mN")
    cols[3].metric("Accel. budget",     f"{accel_n*1e3:.0f} mN",
                   help=f"{mass_kg*1e3:.0f} g × {_SPEED_ACCEL.get(speed,2.0):.1f} m/s²")
    icon = badge(target_n, 0.05, 0.02, higher_is_better=True)
    cols[4].metric(f"Continuous target {icon}", f"{target_n*1e3:.0f} mN",
                   help="The motor must produce at least this much force at all times")
    st.caption(f"Peak burst target: **{peak_n*1e3:.0f} mN** (fast automation)")


def _step5_pcb_tier() -> None:
    st.subheader("Choose your PCB manufacturer and layer count.")
    eli5(
        "More layers = more force, but higher cost. "
        "The tool estimates the achievable force for each option using your magnet and coil settings."
    )

    manufacturer = st.selectbox(
        "PCB manufacturer / design-rule tier",
        ["JLCPCB Standard (5/5 mil)", "JLCPCB Advanced (3/3 mil)",
         "PCBWay Standard", "Custom"],
        index=0,
    )
    st.session_state["manufacturer"] = manufacturer

    # Build a draft config to estimate force
    draft = build_config_from_wizard()
    if draft is None:
        st.warning("Fix earlier steps before estimating force here.")
        return

    target_n = draft.target_force_n
    st.caption(f"Your force target from Step 5: **{target_n*1e3:.0f} mN** continuous")

    # Layer comparison table
    st.markdown("**Layer count comparison:**")
    header = st.columns([1.5, 2, 2, 2, 2])
    header[0].markdown("**Layers**")
    header[1].markdown("**Est. force**")
    header[2].markdown("**Meets target?**")
    header[3].markdown("**Est. cost (5 boards)**")
    header[4].markdown("")

    recommended = None
    for n in [4, 6, 8, 10, 12]:
        force = _estimate_force_n(draft, n)
        meets = force >= target_n
        if meets and recommended is None:
            recommended = n

        cols = st.columns([1.5, 2, 2, 2, 2])
        icon_f = "✅" if meets else "❌"
        selected = (st.session_state.get("layer_count_override") == n)
        cost_str = f"~${_COST_USD.get(n, '?')}"
        badge_txt = " ← recommended" if (n == recommended and not selected) else ""
        cols[0].markdown(f"**{n}**")
        cols[1].markdown(f"{force*1e3:.0f} mN")
        cols[2].markdown(f"{icon_f}")
        cols[3].markdown(f"{cost_str}")
        if cols[4].button(
            "✓ Selected" if selected else "Choose",
            key=f"layer_{n}",
            type="primary" if selected else "secondary",
        ):
            st.session_state["layer_count_override"] = n
            st.rerun()
        if badge_txt:
            cols[4].caption(badge_txt)

    # Auto-select recommended if none chosen
    if st.session_state.get("layer_count_override") is None and recommended:
        st.session_state["layer_count_override"] = recommended

    # Thermal check
    chosen_n = st.session_state.get("layer_count_override", recommended or 6)
    if draft:
        try:
            pb = PowerEstimator(layers_per_phase=chosen_n // draft.phases).estimate(draft)
            dt_icon = badge(pb.temperature_rise_c, 20.0, 35.0, higher_is_better=False)
            st.divider()
            st.caption(
                f"Thermal at {draft.max_current_a:.1f} A continuous, {chosen_n} layers: "
                f"**ΔT ≈ {pb.temperature_rise_c:.0f} °C** {dt_icon} "
                f"(budget: {draft.max_temperature_rise_c:.0f} °C)"
            )
        except Exception:
            pass


def _render_review_card(config: LinearMotorConfig) -> None:
    """Full budget card shown after step 6 and in the review section."""
    st.divider()
    st.subheader("Design Review")
    eli5("This is a summary of all the key numbers for your design. Green = good, Yellow = marginal, Red = a problem.")

    chosen_n = st.session_state.get("layer_count_override", 6)
    try:
        hz  = HeightStackCalculator()
        hs  = hz.calculate(config)
        budget_m = mm(st.session_state["height_budget_mm"])
        fits = hs.fits_in_budget(budget_m)

        pb = PowerEstimator(layers_per_phase=chosen_n // config.phases).estimate(config)

        force_est = _estimate_force_n(config, chosen_n)
        topo_label = config.coil_topology.value.title()
        arr_label  = {
            MagnetArrangement.ALTERNATING: "Alternating",
            MagnetArrangement.HALBACH: "Halbach",
            MagnetArrangement.ALTERNATING_BACK_IRON: "Simple + back-iron",
            MagnetArrangement.HALBACH_BACK_IRON: "Halbach + back-iron",
        }.get(config.magnet_arrangement, "")

        c1, c2, c3, c4, c5 = st.columns(5)
        fi = badge(force_est, config.target_force_n, config.target_force_n * 0.8)
        ti = badge(pb.temperature_rise_c, config.max_temperature_rise_c,
                   config.max_temperature_rise_c * 1.5, higher_is_better=False)
        hi = badge(1 if fits else 0, 1, 0.5)
        pi = badge(pb.continuous_power_w, 0.01, 10.0, higher_is_better=False)

        c1.metric(f"Force {fi}", f"{force_est*1e3:.0f} mN",
                  delta=f"{(force_est - config.target_force_n)*1e3:+.0f} mN vs target")
        c2.metric(f"Thermal {ti}", f"+{pb.temperature_rise_c:.0f} °C",
                  delta=f"budget {config.max_temperature_rise_c:.0f} °C")
        c3.metric(f"Height {hi}", f"{hs.total_height_m*1e3:.1f} mm",
                  delta=f"{'fits' if fits else 'over'} {budget_m*1e3:.0f} mm budget")
        c4.metric(f"Power {pi}", f"{pb.continuous_power_w*1e3:.0f} mW")
        c5.metric("PCB",
                  f"{chosen_n}L  {topo_label}",
                  delta=arr_label)
    except Exception as exc:
        st.warning(f"Could not compute review card: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Advanced renderer
# ─────────────────────────────────────────────────────────────────────────────

def render_advanced() -> LinearMotorConfig | None:
    st.subheader("⚙️ Advanced — Direct Parameter Control")
    st.caption(
        "All motor and PCB parameters exposed directly. "
        "Use the Wizard mode if you want guided goal-first configuration."
    )

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**Mechanical**")
        st.session_state["adv_travel_mm"] = st.number_input(
            "Travel (mm)", min_value=10.0, max_value=200.0,
            value=float(st.session_state["adv_travel_mm"]), step=1.0, format="%.1f")
        st.session_state["adv_board_width_mm"] = st.number_input(
            "Board width (mm)", min_value=1.0, max_value=100.0,
            value=float(st.session_state["adv_board_width_mm"]), step=0.5, format="%.1f",
            help="Minimum 1 mm. Dimension perpendicular to the travel axis.")
        st.session_state["adv_magnet_pitch_mm"] = st.number_input(
            "Pole pitch / magnet pitch (mm)", min_value=1.0, max_value=50.0,
            value=float(st.session_state["adv_magnet_pitch_mm"]), step=0.5, format="%.2f")
        st.session_state["magnet_width_mm"] = st.number_input(
            "Magnet width (mm)", min_value=0.5, max_value=float(st.session_state["adv_magnet_pitch_mm"]),
            value=float(min(st.session_state["magnet_width_mm"],
                            st.session_state["adv_magnet_pitch_mm"])),
            step=0.1, format="%.2f")
        st.session_state["adv_magnet_h_mm"] = st.number_input(
            "Magnet height (mm)", min_value=0.5, max_value=20.0,
            value=float(st.session_state["adv_magnet_h_mm"]), step=0.1, format="%.2f")
        st.session_state["adv_air_gap_mm"] = st.number_input(
            "Air gap (mm)", min_value=0.0, max_value=10.0,
            value=float(st.session_state["adv_air_gap_mm"]), step=0.05, format="%.2f",
            help="0 = magnets touching the PCB surface. Practical minimum ≈ 0.2 mm.")
        st.session_state["adv_remanence_t"] = st.number_input(
            "Magnet Br (T)", min_value=0.1, max_value=2.0,
            value=float(st.session_state["adv_remanence_t"]), step=0.01, format="%.3f")

    with col_r:
        st.markdown("**Electrical & PCB**")
        st.session_state["adv_phases"] = st.select_slider(
            "Phases", [1, 2, 3], st.session_state["adv_phases"])
        st.session_state["max_current_a"] = st.select_slider(
            "Max current (A)", [0.5, 1.0, 1.5, 2.0], st.session_state["max_current_a"])
        st.session_state["supply_v"] = st.select_slider(
            "Supply voltage (V)", [3.3, 5.0, 9.0, 12.0], st.session_state["supply_v"])
        st.session_state["adv_target_n"] = st.slider(
            "Target force (N)", 0.05, 2.0, st.session_state["adv_target_n"], 0.05)
        st.session_state["adv_min_trace_mil"] = st.select_slider(
            "Min trace (mil)", [3, 4, 5, 6, 8, 10], st.session_state["adv_min_trace_mil"])
        st.session_state["adv_min_space_mil"] = st.select_slider(
            "Min space (mil)", [3, 4, 5, 6, 8, 10], st.session_state["adv_min_space_mil"])
        st.session_state["adv_max_layers"] = st.select_slider(
            "Max layers", [4, 6, 8, 10, 12], st.session_state["adv_max_layers"])

        st.markdown("**Magnet arrangement**")
        arr_labels = {
            MagnetArrangement.ALTERNATING: "Alternating",
            MagnetArrangement.HALBACH: "Halbach",
            MagnetArrangement.ALTERNATING_BACK_IRON: "Alternating + back-iron",
            MagnetArrangement.HALBACH_BACK_IRON: "Halbach + back-iron",
        }
        arr_choice = st.selectbox(
            "Arrangement",
            list(arr_labels.values()),
            index=list(arr_labels.keys()).index(st.session_state["magnet_arrangement"]),
        )
        st.session_state["magnet_arrangement"] = [
            k for k, v in arr_labels.items() if v == arr_choice
        ][0]

        topo_labels = {t: t.value.title() for t in CoilTopology}
        topo_choice = st.selectbox(
            "Coil topology",
            list(topo_labels.values()),
            index=list(topo_labels.keys()).index(st.session_state["coil_topology"]),
        )
        st.session_state["coil_topology"] = [
            k for k, v in topo_labels.items() if v == topo_choice
        ][0]

    return build_config_from_advanced()


# ─────────────────────────────────────────────────────────────────────────────
# Output tabs
# ─────────────────────────────────────────────────────────────────────────────

def render_output_tabs(config: LinearMotorConfig) -> None:
    st.divider()
    tab_geo, tab_mag, tab_force, tab_kicad = st.tabs([
        "🔀 Coil Geometry", "🧲 Magnet Field", "📈 Force Preview", "🖥️ Write to KiCad"
    ])

    with tab_geo:
        _tab_geometry(config)
    with tab_mag:
        _tab_magnets(config)
    with tab_force:
        _tab_force(config)
    with tab_kicad:
        _tab_kicad(config)


def _tab_geometry(config: LinearMotorConfig) -> None:
    st.subheader("Coil geometry preview")
    from pcbstatorgen.geometry.coil_generators import make_coil_generator
    gen = make_coil_generator(config.coil_topology)
    if config.coil_topology == CoilTopology.SPIRAL:
        coils = gen.generate(config, layer_pair=(0, 1))
        coils = [c for c in coils if c.layer_idx == 0]  # primary layer only for display
    else:
        coils = gen.generate(config)

    phase_colors = ["#e74c3c", "#2ecc71", "#3498db", "#9b59b6"]
    fig, ax = plt.subplots(figsize=(14, 4))
    for coil in coils:
        color = phase_colors[coil.phase_idx % len(phase_colors)]
        for seg in coil.active_segments:
            ax.plot(
                [seg.start[0] * 1000, seg.end[0] * 1000],
                [seg.start[1] * 1000, seg.end[1] * 1000],
                color=color, linewidth=2,
            )
        for seg in coil.end_turn_segments:
            ax.plot(
                [seg.start[0] * 1000, seg.end[0] * 1000],
                [seg.start[1] * 1000, seg.end[1] * 1000],
                color=color, linewidth=1, linestyle="--", alpha=0.5,
            )
    ax.set_xlabel("Travel axis (mm)")
    ax.set_ylabel("Board width (mm)")
    ax.set_title(
        f"{config.coil_topology.value.title()} winding — "
        f"{config.phases} phases, pole pitch {config.pole_pitch_m*1e3:.0f} mm"
    )
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    if coils:
        n_active = coils[0].active_conductor_count
        c1, c2, c3 = st.columns(3)
        c1.metric("Active conductors/phase", n_active)
        c2.metric("Active copper length/phase",
                  f"{coils[0].active_length_m * 1e3:.0f} mm")
        c3.metric("Topology", config.coil_topology.value.title())


def _tab_magnets(config: LinearMotorConfig) -> None:
    st.subheader("Magnetic field at PCB surface")
    from pcbstatorgen.magnetic.magnet_model import MagnetArray

    fader_pos_mm = st.slider(
        "Fader position (mm)", 0.0, float(config.travel_m * 1000),
        0.0, 1.0, key="fader_mag_tab",
    )

    arr = MagnetArray(config)
    xs = np.linspace(0, config.active_length_m, 200)
    B  = arr.bfield_at_pcb_surface(xs, fader_position_m=mm(fader_pos_mm))

    fig, axes = plt.subplots(2, 1, figsize=(13, 6), sharex=True)
    axes[0].plot(xs * 1000, B[:, 2] * 1000, color="#e74c3c", linewidth=1.5)
    axes[0].fill_between(xs * 1000, B[:, 2] * 1000, 0,
                         where=B[:, 2] > 0, alpha=0.15, color="#e74c3c", label="North")
    axes[0].fill_between(xs * 1000, B[:, 2] * 1000, 0,
                         where=B[:, 2] < 0, alpha=0.15, color="#3498db", label="South")
    axes[0].axhline(0, color="gray", linewidth=0.5)
    axes[0].set_ylabel("Bz (mT)")
    axes[0].legend(fontsize=8)
    axes[0].set_title(
        f"Vertical field Bz — {config.magnet_arrangement.name} "
        f"at {fader_pos_mm:.0f} mm fader position"
    )
    axes[0].grid(True, alpha=0.2)

    axes[1].plot(xs * 1000, B[:, 0] * 1000, "#9b59b6", linewidth=1.5, label="Bx")
    axes[1].plot(xs * 1000, B[:, 1] * 1000, "#27ae60", linewidth=1.0,
                 linestyle="--", label="By", alpha=0.7)
    axes[1].axhline(0, color="gray", linewidth=0.5)
    axes[1].set_ylabel("B (mT)")
    axes[1].set_xlabel("Position along travel (mm)")
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.2)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    bz_peak = float(np.abs(B[:, 2]).max()) * 1000
    bz_mean = float(np.abs(B[:, 2]).mean()) * 1000
    c1, c2 = st.columns(2)
    c1.metric("Peak |Bz|", f"{bz_peak:.0f} mT")
    c2.metric("Mean |Bz|", f"{bz_mean:.0f} mT")
    eli5(
        f"Your {config.magnet_arrangement.name} array produces {bz_peak:.0f} mT peak at the PCB. "
        f"For comparison, a fridge magnet is about 10 mT. Strong field = strong motor."
    )


def _tab_force(config: LinearMotorConfig) -> None:
    st.subheader("Force vs fader position")
    from pcbstatorgen.geometry.coil_generators import make_coil_generator
    from pcbstatorgen.magnetic.force_eval import ForceEvaluator

    col1, col2 = st.columns([1, 3])
    with col1:
        n_pos = st.select_slider("Resolution", [8, 12, 20, 30], 12, key="force_res")
        meshing = st.select_slider("Accuracy", [5, 8, 10, 15], 5, key="force_mesh")
        commutation = st.radio("Commutation", ["max_torque", "phase_a_only"], key="force_comm")
        run = st.button("▶ Calculate Force", type="primary")
        eli5("Start with low settings (8, 5) for a quick estimate (~5 s). "
             "Increase for a final accurate result.")

    with col2:
        if run:
            gen = make_coil_generator(config.coil_topology)
            if config.coil_topology == CoilTopology.SPIRAL:
                coils = gen.generate(config, layer_pair=(0, 1))
            else:
                coils = gen.generate(config)
            with st.spinner("Computing magnetic force…"):
                ev = ForceEvaluator(n_positions=n_pos, meshing=meshing, commutation=commutation)
                result = ev.evaluate(config, coils)
            st.session_state["force_result"] = result
            st.session_state["force_config_label"] = (
                f"{config.coil_topology.value}, {config.magnet_arrangement.name}, "
                f"I={config.max_current_a:.1f}A"
            )

        if "force_result" in st.session_state:
            result = st.session_state["force_result"]
            label  = st.session_state.get("force_config_label", "")

            pos_mm = result.positions_m * 1000
            c1, c2, c3, c4 = st.columns(4)
            fi = badge(result.mean_thrust_n, config.target_force_n, config.target_force_n * 0.8)
            ri = badge(result.ripple_pct, 5.0, 15.0, higher_is_better=False)
            c1.metric(f"Mean thrust {fi}", f"{result.mean_thrust_n*1e3:.1f} mN",
                      delta=f"{(result.mean_thrust_n - config.target_force_n)*1e3:+.1f} mN")
            c2.metric("Peak thrust",  f"{result.peak_thrust_n*1e3:.1f} mN")
            c3.metric(f"Ripple {ri}", f"{result.ripple_pct:.1f} %")
            c4.metric("Target met",
                      "✅ Yes" if result.mean_thrust_n >= config.target_force_n else "❌ No")

            fig2, ax2 = plt.subplots(figsize=(11, 4))
            ax2.plot(pos_mm, result.force_x_n * 1000, "#e74c3c", linewidth=2, label="Thrust")
            ax2.axhline(config.target_force_n * 1000, color="#27ae60", linewidth=1.5,
                        linestyle="--", label=f"Target ({config.target_force_n*1e3:.0f} mN)")
            ax2.axhline(result.mean_thrust_n * 1000, color="#f39c12", linewidth=1,
                        linestyle=":", label=f"Mean")
            ax2.set_xlabel("Fader position (mm)")
            ax2.set_ylabel("Thrust (mN)")
            ax2.set_title(f"Force profile — {label}")
            ax2.legend(fontsize=8)
            ax2.grid(True, alpha=0.2)
            fig2.tight_layout()
            st.pyplot(fig2)
            plt.close(fig2)
        else:
            st.info("Click **Calculate Force** to run the Magpylib force model.")


def _tab_kicad(config: LinearMotorConfig) -> None:
    st.subheader("Write layout to KiCad")
    st.info(
        "**Prerequisites:**  "
        "KiCad 10 running · IPC API enabled (Preferences → Plugins) · "
        "A `.kicad_pcb` file open in the PCB Editor"
    )

    check = st.button("🔌 Check KiCad connection")
    if check:
        with st.spinner("Connecting…"):
            try:
                from pcbstatorgen.kicad_writer.connection import KiCadConnection
                conn = KiCadConnection()
                conn.connect()
                st.session_state["kicad_status"] = "connected"
                st.session_state["kicad_board"] = conn.board_filename
                st.session_state["kicad_layers"] = conn.copper_layer_count
                conn.disconnect()
            except Exception as exc:
                st.session_state["kicad_status"] = f"error: {exc}"

    status = st.session_state.get("kicad_status", "")
    if status == "connected":
        st.success(
            f"✅ Connected — Board: **{st.session_state.get('kicad_board', '?')}**  "
            f"| Copper layers: **{st.session_state.get('kicad_layers', '?')}**"
        )
    elif status.startswith("error"):
        st.error(f"❌ {status[7:]}")

    st.divider()
    # Pipeline status
    st.markdown("**Generation pipeline status:**")
    phases_status = [
        ("Phase 1", "config.py, units.py",              "✅ Complete"),
        ("Phase 2", "geometry/ — wave winding, vias",   "✅ Complete"),
        ("Phase 3", "magnetic/ — Magpylib force model", "✅ Complete"),
        ("Phase 4", "stackup/ — layer optimizer",       "🔲 Next phase"),
        ("Phase 5", "kicad_writer/ — IPC track/via",    "🔲 Pending"),
        ("Phase 6", "optimization/ — bfieldtools",      "🔲 Pending"),
        ("Phase 7", "export/ — GMSH + Elmer FEM",       "🔲 Pending"),
    ]
    for ph, mod, stat in phases_status:
        c1, c2, c3 = st.columns([1, 3, 2])
        c1.caption(ph)
        c2.caption(f"`{mod}`")
        c3.caption(stat)

    st.divider()
    if status == "connected":
        st.button("🚀 Generate Coils in KiCad", type="primary", disabled=True,
                  help="Available after Phase 5 (KiCad writer) is implemented")
        st.caption("Phase 5 is next — Track, Via, Net, BoardStackup placement via IPC API.")
    else:
        st.button("🚀 Generate Coils in KiCad", disabled=True)
        st.caption("Connect to KiCad first.")

    with st.expander("Configuration that will be sent to KiCad"):
        st.code(config.summary(), language="text")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if st.session_state["ui_mode"] == "wizard":
    config = render_wizard()
else:
    config = render_advanced()

if config is not None:
    render_output_tabs(config)
