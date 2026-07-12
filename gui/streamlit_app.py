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
    "magnet_gap_mm": 2.0,
    "magnet_height_mm": 4.0,
    "magnet_length_mm": 10.0,
    "air_gap_mm": 0.5,
    "back_iron_mm": 0.0,
    "spacing_ratio_label": "1:1 Standard (Maximum Fundamental Force)",
    # Linear Specifics
    "travel_mm": 75.0,
    "board_width_mm": 20.0,
    "mass_g": 15.0,
    "friction_mn": 85.0,
    "target_force_n": 0.25,
    # Radial Specifics
    "stator_OD_mm": 80.0,
    "stator_ID_mm": 30.0,
    "rated_speed_rpm": 3000.0,
    "target_torque_m_nm": 100.0,
    "rotor_inertia_gcm2": 100.0,
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


def build_config() -> LinearMotorConfig | AxialMotorConfig | None:
    """Assemble a config from all dashboard session-state values."""
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

with col_params:
    st.subheader("📐 Mechanical & Magnet Geometry")
    
    # Render fields depending on selected class
    if st.session_state["motor_class"] == "Radial":
        st.session_state["stator_OD_mm"] = st.number_input(
            "Stator Outer Diameter (OD) (mm)", min_value=10.0, max_value=250.0,
            value=float(st.session_state["stator_OD_mm"]), step=1.0, format="%.1f",
            help="Maximum outer diameter of the stator disk."
        )
        st.session_state["stator_ID_mm"] = st.number_input(
            "Stator Inner Diameter (ID) (mm)", min_value=5.0, max_value=200.0,
            value=float(st.session_state["stator_ID_mm"]), step=1.0, format="%.1f",
            help="Inner bore diameter (shaft clearance) of the stator disk."
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
        st.session_state["friction_mn"] = st.number_input(
            "Guide Friction Drag (mN)", min_value=0.0, max_value=2000.0,
            value=float(st.session_state["friction_mn"]), step=5.0, format="%.1f",
            help="Frictional resistance from linear guides and cables."
        )
        
        # Display derived properties
        if config:
            st.caption(
                f"**Linear Properties:**  \n"
                f"• Total Active Zone Length: **{config.active_length_m*1000:.1f} mm** (travel + coil span)"
            )

    st.divider()
    st.markdown("**Magnet Array Geometry**")
    
    # Gap instead of Pitch, and direct Magnet Width
    st.session_state["magnet_width_mm"] = st.number_input(
        "Magnet Width along Travel Axis (mm)", min_value=1.0, max_value=50.0,
        value=float(st.session_state["magnet_width_mm"]), step=0.1, format="%.2f",
        help="Physical width of a single magnet block."
    )
    st.session_state["magnet_gap_mm"] = st.number_input(
        "Gap between magnets (mm)", min_value=0.0, max_value=20.0,
        value=float(st.session_state["magnet_gap_mm"]), step=0.1, format="%.2f",
        help="Mechanical separation between adjacent magnets. 0.0 mm = edge-to-edge (magnets touching)."
    )
    st.session_state["magnet_height_mm"] = st.number_input(
        "Magnet Thickness / Height (mm)", min_value=0.5, max_value=20.0,
        value=float(st.session_state["magnet_height_mm"]), step=0.1, format="%.2f",
        help="Thickness of the magnets in the vertical axis."
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
    st.session_state["magnet_grade"] = grade_choice
    mapped_br = _MAGNET_BR_LOOKUP[grade_choice]
    
    if mapped_br is not None:
        st.session_state["remanence_t"] = mapped_br
        st.markdown(f"Remanence flux density ($Br$): **{mapped_br:.2f} Tesla** (Locked by Grade)")
    else:
        st.session_state["remanence_t"] = st.slider(
            "Manual Remanence Br (Tesla)", min_value=0.1, max_value=2.0,
            value=float(st.session_state["remanence_t"]), step=0.01
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