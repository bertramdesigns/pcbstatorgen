"""
gui/streamlit_app.py — PCB Stator Generator Dashboard
======================================================
Run with:
    streamlit run gui/streamlit_app.py

A unified, high-fidelity Advanced Dashboard for designing and validating
PCB stator motors. Fully generalized from specific applications (such as faders)
to any linear actuator or radial (rotary) axial-flux motor.
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
    AxialMotorConfig,
    MagnetArrangement,
    StackupResult,
)
from pcbstatorgen.stackup.friction import BearingType, FrictionEstimator
from pcbstatorgen.stackup.height_stack import HeightStackCalculator, HeightStackResult
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
# Constants & Lookups
# ─────────────────────────────────────────────────────────────────────────────

# Rough fabrication cost for 5 boards at JLCPCB standard per layer count
_COST_USD = {4: 12, 6: 22, 8: 38, 10: 60, 12: 85}

# Magnet Grade Br Lookup Table
_MAGNET_BR_LOOKUP = {
    "N35 (Standard)": 1.19,
    "N38 (Medium)": 1.23,
    "N42 (Strong)": 1.30,
    "N44H (High-Temp Standard)": 1.34,
    "N48 (Ultra-Strong)": 1.40,
    "N52 (Premium / Maximum)": 1.45,
    "Custom (Manual Input)": None
}

# Winding Spacing Ratio Lookup Table
_SPACING_RATIO_LOOKUP = {
    "1:1 Standard (Maximum Fundamental Force)": 1.0,
    "Vernier 4:5 (Suppresses 5th Winding Harmonic, Low Ripple)": 0.8,
    "Vernier 5:6 (Suppresses 6th Winding Harmonic, Low Ripple)": 0.8333,
}

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
    CoilTopology.SINE_WAVE: 0.78,
}

# ─────────────────────────────────────────────────────────────────────────────
# Session state initialisation
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULTS = {
    "motor_class": "Linear",
    "coil_topology": CoilTopology.SERPENTINE,
    "magnet_arrangement": MagnetArrangement.ALTERNATING,
    "magnet_grade": "N44H (High-Temp Standard)",
    "remanence_t": 1.34,
    "max_current_a": 1.0,
    "supply_v": 5.0,
    "layers": 6,
    "phases": 3,
    "min_trace_mil": 5.0,
    "min_space_mil": 5.0,
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
}

for k, v in _DEFAULTS.items():
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


def _estimate_force_n(config: LinearMotorConfig | AxialMotorConfig, n_layers: int) -> float:
    """Quick analytical force estimate — good enough for the live dashboard metrics."""
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
        height_budget = mm(st.session_state["height_budget_mm"])
        supply_v      = st.session_state["supply_v"]
        max_i         = st.session_state["max_current_a"]
        coil_topo     = st.session_state["coil_topology"]
        n_layers      = st.session_state.get("layer_count_override") or 6

        travel_m      = mm(preset["travel_mm"])
        mass_kg       = preset["mass_g"] / 1000.0
        board_width_m = mm(preset["board_width_mm"])
        ffc_count     = preset["ffc"]

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
            magnet_pitch_m=mm(12),
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
        arrangement = s["magnet_arrangement"]
        back_iron_m = mm(s["back_iron_mm"])
        mw = mm(s["magnet_width_mm"])
        gap_m = mm(s["magnet_gap_mm"])
        pole_pitch_m = mw + gap_m
        height_m = mm(s["magnet_height_mm"])
        length_m = mm(s["magnet_length_mm"])
        air_gap_m = mm(s["air_gap_mm"])
        remanence = s["remanence_t"]
        coil_topo = s["coil_topology"]
        n_layers = s["layers"]
        phases = s["phases"]
        min_trace = mils_to_m(s["min_trace_mil"])
        min_space = mils_to_m(s["min_space_mil"])
        max_i = s["max_current_a"]
        supply_v = s["supply_v"]
        ratio = _SPACING_RATIO_LOOKUP.get(s["spacing_ratio_label"], 1.0)

        if s["motor_class"] == "Radial":
            od_m = mm(s["stator_OD_mm"])
            id_m = mm(s["stator_ID_mm"])
            speed = s["rated_speed_rpm"]
            target_t_nm = s["target_torque_m_nm"] / 1000.0
            peak_t_nm = target_t_nm * 2.0
            inertia = s["rotor_inertia_gcm2"] * 1e-7  # g·cm² to kg·m²
            
            return AxialMotorConfig(
                name=f"axial-{s['stator_OD_mm']:.0f}mm",
                stator_OD_m=od_m,
                stator_ID_m=id_m,
                rated_speed_rpm=speed,
                target_torque_nm=target_t_nm,
                peak_torque_nm=peak_t_nm,
                rotor_inertia_kgm2=inertia,
                magnet_dims_m=(mw, length_m, height_m),
                magnet_count=10,
                magnet_pitch_m=pole_pitch_m,
                magnet_remanence_t=remanence,
                magnet_arrangement=arrangement,
                back_iron_thickness_m=back_iron_m,
                coil_topology=coil_topo,
                phases=phases,
                spacing_ratio=ratio,
                max_current_a=max_i,
                supply_voltage_v=supply_v,
                min_trace_m=min_trace,
                min_space_m=min_space,
                min_via_drill_m=mm(0.2),
                min_via_annular_ring_m=mm(0.1),
                air_gap_m=air_gap_m,
                max_layers=n_layers,
            )
        else:
            travel_m = mm(s["travel_mm"])
            board_width_m = mm(s["board_width_mm"])
            mass_kg = s["mass_g"] / 1000.0
            friction_n = s["friction_mn"] / 1000.0
            target_n = s["target_force_n"]
            peak_n = target_n * 2.0

            return LinearMotorConfig(
                name=f"linear-{s['travel_mm']:.0f}mm",
                travel_m=travel_m,
                magnet_dims_m=(mw, length_m, height_m),
                magnet_count=10,
                magnet_pitch_m=pole_pitch_m,
                magnet_remanence_t=remanence,
                magnet_arrangement=arrangement,
                back_iron_thickness_m=back_iron_m,
                coil_topology=coil_topo,
                phases=phases,
                spacing_ratio=ratio,
                target_force_n=target_n,
                peak_force_n=peak_n,
                friction_n=friction_n,
                carriage_mass_kg=mass_kg,
                max_current_a=max_i,
                supply_voltage_v=supply_v,
                min_trace_m=min_trace,
                min_space_m=min_space,
                min_via_drill_m=mm(0.2),
                min_via_annular_ring_m=mm(0.1),
                board_width_m=board_width_m,
                air_gap_m=air_gap_m,
                max_layers=n_layers,
                pcb_thickness_m=0.0016,
                capacitor_bank_uf=1000.0,
            )
    except Exception as exc:
        st.error(f"Configuration error: {exc}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚡ pcbstatorgen")
    st.caption("Multiphysics PCB Stator Motor Generator")
    st.divider()

    motor_class_selection = st.radio(
        "Motor Class",
        ["Linear Motor", "Radial (Rotary) Motor"],
        index=0 if st.session_state["motor_class"] == "Linear" else 1,
        help="Linear Motor: Straight stroke actuator.\nRadial Motor: Rotating disk / shaft motor."
    )
    st.session_state["motor_class"] = "Linear" if "Linear" in motor_class_selection else "Radial"
    st.divider()

    # Coil Topology Selectable (Serpentine vs Sine Wave Serpentine only)
    topo_labels = {
        CoilTopology.SERPENTINE: "🌊 Square Serpentine",
        CoilTopology.SINE_WAVE: "🌊 Sine Wave Serpentine"
    }
    topo_choice = st.selectbox(
        "Coil Topology",
        list(topo_labels.values()),
        index=0 if st.session_state["coil_topology"] not in topo_labels else list(topo_labels.keys()).index(st.session_state["coil_topology"]),
        help="Select the trace winding shape of the stator."
    )
    st.session_state["coil_topology"] = [
        k for k, v in topo_labels.items() if v == topo_choice
    ][0]

    # Spacing Ratio (Vernier) selectbox
    ratio_choice = st.selectbox(
        "Winding Spacing Ratio",
        list(_SPACING_RATIO_LOOKUP.keys()),
        index=list(_SPACING_RATIO_LOOKUP.keys()).index(st.session_state["spacing_ratio_label"]),
        help="Vernier misaligns the coils to poles by a fractional ratio to cancel spatial force harmonics and flatten ripple, at the cost of a slightly lower fundamental force."
    )
    st.session_state["spacing_ratio_label"] = ratio_choice

    st.divider()
    st.caption("ℹ️ *Designed for local-first drafting directly to KiCad 10 over the kipy IPC API. Offline physics verification powered by Magpylib.*")

# ─────────────────────────────────────────────────────────────────────────────
# Main Dashboard Layout
# ─────────────────────────────────────────────────────────────────────────────

st.title(f"🛠️ Unified {st.session_state['motor_class']} Dashboard")
st.divider()

# Build and store configuration
config = build_config()

col_params, col_feedback = st.columns([1, 1])

def render_wizard() -> LinearMotorConfig | None:
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
        st.session_state["rated_speed_rpm"] = st.number_input(
            "Target Rated Speed (RPM)", min_value=1.0, max_value=25000.0,
            value=float(st.session_state["rated_speed_rpm"]), step=50.0, format="%.1f",
            help="Continuous rated operating speed of the rotary motor."
        )
        st.session_state["rotor_inertia_gcm2"] = st.number_input(
            "Rotor Inertia (g·cm²)", min_value=0.1, max_value=10000.0,
            value=float(st.session_state["rotor_inertia_gcm2"]), step=5.0, format="%.1f",
            help="Total rotational inertia of the rotor assembly."
        )
        
        # Display derived properties
        if config:
            st.caption(
                f"**Radial Properties:**  \n"
                f"• Active Area Width (radial span): **{config.board_width_m*1000:.1f} mm**  \n"
                f"• Mean Stator Radius: **{config.mean_radius_m*1000:.1f} mm**  \n"
                f"• Equivalent Active Zone Length: **{config.active_length_m*1000:.1f} mm**"
            )
    else:
        st.session_state["travel_mm"] = st.number_input(
            "Center-to-Center Travel (mm)", min_value=10.0, max_value=500.0,
            value=float(st.session_state["travel_mm"]), step=5.0, format="%.1f",
            help="The physical center-to-center stroke of the mover reference center."
        )
        st.session_state["board_width_mm"] = st.number_input(
            "Active Area Width (mm)", min_value=1.0, max_value=100.0,
            value=float(st.session_state["board_width_mm"]), step=1.0, format="%.1f",
            help="Width of the copper traces perpendicular to travel."
        )
        st.session_state["mass_g"] = st.number_input(
            "Mover Carriage Mass (g)", min_value=1.0, max_value=2000.0,
            value=float(st.session_state["mass_g"]), step=1.0, format="%.1f",
            help="Total mass of the moving carriage assembly."
        )
        st.session_state["max_current_a"] = float(max_i)
        eli5("Set by your gate driver IC's current rating, not by what you think you need. Check the datasheet.")

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

    st.divider()
    st.markdown("**Magnet Array Geometry**")
    
    # Gap instead of Pitch, and direct Magnet Width
    st.session_state["magnet_width_mm"] = st.number_input(
        "Magnet Width along Travel Axis (mm)", min_value=1.0, max_value=50.0,
        value=float(st.session_state["magnet_width_mm"]), step=0.1, format="%.2f",
        help="Physical width of a single magnet block."
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

    # Magnet width
    preset = _FADER_PRESETS.get(st.session_state["fader_preset"], _FADER_PRESETS["Studio 75 mm"])
    st.subheader("Magnet size")
    mw = st.slider(
        "Magnet width along travel axis (mm)",
        min_value=4.0, max_value=11.5, value=st.session_state["magnet_width_mm"],
        step=0.5,
        help="Must be ≥ 0.3 mm smaller than pole pitch (12 mm) for assembly clearance",
    )
    st.session_state["magnet_width_mm"] = mw
    gap_mm = 12.0 - mw
    icon = badge(gap_mm, 2.0, 0.5, higher_is_better=True)
    st.caption(f"Inter-magnet gap: **{gap_mm:.1f} mm** {icon}")
    eli5(
        "The gap between adjacent magnets must be ≥ 0.3 mm to physically fit them together. "
        "Larger gap = more room for a Halbach interleave magnet, but less magnet material per pole."
    )


def _step4_force_and_feel() -> None:
    st.subheader("How should the fader feel?")
    eli5(
        "You're defining the USER EXPERIENCE here, not the motor specs. "
        "The tool converts your answers to the minimum force the motor must produce."
    )
    st.session_state["magnet_length_mm"] = st.number_input(
        "Magnet Length across Stator (mm)", min_value=1.0, max_value=100.0,
        value=float(st.session_state["magnet_length_mm"]), step=1.0, format="%.1f",
        help="Length of magnets perpendicular to travel."
    )
    st.session_state["air_gap_mm"] = st.number_input(
        "Assembly Air Gap Clearance (mm)", min_value=0.05, max_value=10.0,
        value=float(st.session_state["air_gap_mm"]), step=0.05, format="%.2f",
        help="Physical clearance between magnet face and PCB top surface."
    )

    # Derived Pole Pitch feedback
    pole_pitch = st.session_state["magnet_width_mm"] + st.session_state["magnet_gap_mm"]
    st.caption(f"**Computed Pole Pitch (magnet width + gap):** **{pole_pitch:.2f} mm**")

    # Magnet Grade dropdown with helper lookup
    grade_choice = st.selectbox(
        "Magnet Grade Selection",
        list(_MAGNET_BR_LOOKUP.keys()),
        index=list(_MAGNET_BR_LOOKUP.keys()).index(st.session_state["magnet_grade"]),
        help="Select a standard grade to look up typical remanence Br, or choose Custom."
    )

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**Mechanical**")
        st.session_state["adv_travel_mm"] = st.slider(
            "Travel (mm)", 40.0, 120.0, st.session_state["adv_travel_mm"], 5.0)
        st.session_state["adv_board_width_mm"] = st.slider(
            "Board width (mm)", 10.0, 40.0, st.session_state["adv_board_width_mm"], 1.0)
        st.session_state["adv_magnet_pitch_mm"] = st.slider(
            "Magnet pitch / pole pitch (mm)", 6.0, 20.0,
            st.session_state["adv_magnet_pitch_mm"], 0.5)
        st.session_state["magnet_width_mm"] = st.slider(
            "Magnet width (mm)", 4.0, 11.5, st.session_state["magnet_width_mm"], 0.5)
        st.session_state["adv_magnet_h_mm"] = st.slider(
            "Magnet height (mm)", 2.0, 8.0, st.session_state["adv_magnet_h_mm"], 0.5)
        st.session_state["adv_air_gap_mm"] = st.slider(
            "Air gap (mm)", 0.2, 3.0, st.session_state["adv_air_gap_mm"], 0.1)
        st.session_state["adv_remanence_t"] = st.slider(
            "Magnet Br (T)", 0.9, 1.5, st.session_state["adv_remanence_t"], 0.01)

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

    # Magnet Arrangement selection with direct back-iron keeper inputs
    st.divider()
    st.markdown("**Flux Management**")
    
    arr_labels = {
        MagnetArrangement.ALTERNATING: "Simple Alternating Poles",
        MagnetArrangement.HALBACH: "Halbach Wavelength Concentrator",
        MagnetArrangement.ALTERNATING_BACK_IRON: "Simple + Steel Back-Iron Keeper",
        MagnetArrangement.HALBACH_BACK_IRON: "Halbach + Steel Back-Iron Keeper",
    }
    arr_choice = st.selectbox(
        "Magnet Arrangement",
        list(arr_labels.values()),
        index=list(arr_labels.keys()).index(st.session_state["magnet_arrangement"]),
        help="Select arrangement to shape and concentrate the magnetic flux."
    )
    st.session_state["magnet_arrangement"] = [
        k for k, v in arr_labels.items() if v == arr_choice
    ][0]

    # Dynamically show Back-Iron thickness option if a back-iron arrangement is chosen
    if st.session_state["magnet_arrangement"] in (MagnetArrangement.ALTERNATING_BACK_IRON, MagnetArrangement.HALBACH_BACK_IRON):
        st.session_state["back_iron_mm"] = st.slider(
            "Steel Keeper Plate (Back-Iron) Thickness (mm)", min_value=0.5, max_value=5.0,
            value=float(max(0.5, st.session_state["back_iron_mm"])), step=0.5,
            help="Sinks rear-side flux, reducing magnetic reluctance and boosting coupling."
        )
    else:
        st.session_state["back_iron_mm"] = 0.0

    st.divider()
    st.subheader("⚡ Electrical Inputs & Targets")
    
    if st.session_state["motor_class"] == "Radial":
        st.session_state["target_torque_m_nm"] = st.slider(
            "Continuous Torque Target (mN·m)", min_value=1.0, max_value=2000.0,
            value=float(st.session_state["target_torque_m_nm"]), step=10.0,
            help="Target holding or continuous torque output."
        )
    else:
        st.session_state["target_force_n"] = st.slider(
            "Continuous Force Target (Newtons)", min_value=0.05, max_value=10.0,
            value=float(st.session_state["target_force_n"]), step=0.05,
            help="Target continuous thrust output perpendicular to the coils. 1 N ≈ 100g force."
        )

    # Unregulated Power Inputs (User inputs voltage & current limits directly)
    st.session_state["supply_v"] = st.number_input(
        "Custom Driver Supply Voltage (V)", min_value=1.0, max_value=120.0,
        value=float(st.session_state["supply_v"]), step=0.5, format="%.1f",
        help="The voltage of your custom power supply."
    )
    st.session_state["max_current_a"] = st.number_input(
        "Custom Controller Continuous Current Limit (A)", min_value=0.1, max_value=50.0,
        value=float(st.session_state["max_current_a"]), step=0.1, format="%.2f",
        help="Maximum continuous phase current of your driver board."
    )
    
    # Grounding scales helper container
    st.caption(
        "**Real-World System Scale Reference:**  \n"
        "• *Phone Haptic*: 5V, 0.2A (1W)  \n"
        "• *USB Standard Slot / Mixer*: 5V, 1A (5W)  \n"
        "• *Small Drone Joint*: 12V, 3A (36W)  \n"
        "• *Large Gimbal Actuator*: 24V, 5A (120W)  \n"
        "• *Industrial Gantry*: 48V, 15A (480W)"
    )

    st.divider()
    st.subheader("🛠️ PCB Layer & Manufacturing Limits")
    st.session_state["layers"] = st.select_slider(
        "Layers Count limit", [4, 6, 8, 10, 12], st.session_state["layers"],
        help="The layer limit for the stator. More layers pack more copper but raise fab costs."
    )
    st.session_state["min_trace_mil"] = st.selectbox(
        "PCB Trace Width Class", [3.0, 4.0, 5.0, 6.0, 8.0, 10.0],
        index=[3.0, 4.0, 5.0, 6.0, 8.0, 10.0].index(st.session_state["min_trace_mil"]),
        help="JLCPCB standard classes. Thinner trace widths fit more turns but have lower current limits."
    )
    st.session_state["min_space_mil"] = st.selectbox(
        "PCB Trace Clearance Class", [3.0, 4.0, 5.0, 6.0, 8.0, 10.0],
        index=[3.0, 4.0, 5.0, 6.0, 8.0, 10.0].index(st.session_state["min_space_mil"]),
        help="Minimum spacing between parallel traces."
    )

with col_feedback:
    st.subheader("📊 Live Analytical Performance Feedback")
    
    if config:
        # 1. Height budget results stackup
        hz_calc = HeightStackCalculator()
        hs = hz_calc.calculate(config)
        
        # 2. Power loss thermals
        pb = PowerEstimator(layers_per_phase=config.max_layers // config.phases).estimate(config)
        
        # 3. Analytical Force/Torque estimation
        force_est = _estimate_force_n(config, config.max_layers)
        
        # Layout metrics row
        c1, c2, c3 = st.columns(3)
        
        if st.session_state["motor_class"] == "Radial":
            torque_m_nm_est = force_est * config.mean_radius_m * 1000.0  # mN·m
            target_t_m_nm = config.target_torque_nm * 1000.0            # mN·m
            ti_badge = badge(torque_m_nm_est, target_t_m_nm, target_t_m_nm * 0.8)
            
            c1.metric(f"Holding Torque {ti_badge}", f"{torque_m_nm_est:.1f} mN·m",
                      delta=f"{torque_m_nm_est - target_t_m_nm:+.1f} mN·m vs target")
        else:
            target_f = config.target_force_n
            fi_badge = badge(force_est, target_f, target_f * 0.8)
            
            c1.metric(f"Cont. Force {fi_badge}", f"{force_est*1000:.0f} mN",
                      delta=f"{(force_est - target_f)*1000:+.0f} mN vs target")

        dt_badge = badge(pb.temperature_rise_c, config.max_temperature_rise_c, config.max_temperature_rise_c * 1.5, higher_is_better=False)
        c2.metric(f"Temp. Rise {dt_badge}", f"+{pb.temperature_rise_c:.0f} °C",
                  delta=f"budget +{config.max_temperature_rise_c:.0f} °C")
        
        c3.metric("Winding Resistance", f"{pb.phase_resistance_ohm:.2f} Ω",
                  help="Per-phase continuous copper trace resistance.")
        
        st.markdown("**Thickness Stackup Result**")
        st.caption(f"Estimated total thickness of stator & magnet stack: **{hs.total_height_m*1000:.2f} mm**")
        
        # Plotly height stack drawing
        stack_items = [
            ("PCB Substrate (FR4)", 1.6, "#2c3e50"),
            ("Copper Layers",       0.035 * config.max_layers, "#f39c12"),
            ("Air gap clearance",   st.session_state["air_gap_mm"], "#3498db"),
            ("Magnets (N44H)",      st.session_state["magnet_height_mm"], "#e74c3c"),
        ]
        if config.back_iron_thickness_m > 0:
            stack_items.append(("Steel Back-Iron", config.back_iron_thickness_m * 1000, "#7f8c8d"))
            
        total_thick = sum(t for _, t, _ in stack_items)
        fig_st, ax_st = plt.subplots(figsize=(6, 3))
        y = 0
        for label, thick, color in stack_items:
            ax_st.barh(y, thick, left=0, height=0.8, color=color, alpha=0.85)
            ax_st.text(thick + 0.1, y, f"{label} ({thick:.2f} mm)", va="center", fontsize=8)
            y += 1
        ax_st.set_xlim(0, total_thick * 1.8)
        ax_st.set_yticks([])
        ax_st.set_xlabel("Thickness (mm)")
        ax_st.set_title(f"Stator Height Stack: {total_thick:.2f} mm", fontsize=10)
        fig_st.tight_layout()
        st.pyplot(fig_st, width="content")
        plt.close(fig_st)

    st.divider()
    st.subheader("🧩 Smoothness, Friction & Zero-Cogging")
    
    st.markdown(
        "**Zero-Cogging Characteristic:**  \n"
        "Because this design features an **air-core (coreless) PCB stator**, there are "
        "no ferromagnetic slots or cores to attract the permanent magnets. Consequently, "
        "**unenergized cogging torque/force is mathematically zero ($F_{cogging} = 0$)**. "
        "This ensures maximum motion smoothness and haptic texture fidelity."
    )
    
    # Calculate force ripple if force sweep result exists
    if "force_result" in st.session_state:
        fr = st.session_state["force_result"]
        ri_badge = badge(fr.ripple_pct, 5.0, 15.0, higher_is_better=False)
        st.metric(f"Harmonic Force Ripple {ri_badge}", f"{fr.ripple_pct:.1f} %",
                  help="Spatial force/torque variations due to winding and magnet boundaries.")
    else:
        st.caption("💡 *Run the Force/Torque Preview below to compute exact harmonic force ripple.*")

# Render Output Tabs
if config:
    render_output_tabs(config)