"""
gui/streamlit_app.py — PCB Stator Motor Generator Dashboard
============================================================
Run with:
    streamlit run gui/streamlit_app.py

A single, unified Advanced Dashboard for designing and validating
PCB stator motors. Supports both Linear and Radial (axial-flux)
topologies with dual-fidelity physics (instant analytical + on-demand
3D Magpylib sweep).
"""

from __future__ import annotations

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
)
from pcbstatorgen.magnet_grades import (
    MAGNET_GRADES,
    GRADE_NAMES,
    CUSTOM_GRADE,
    get_remanence,
    get_grade,
)
from pcbstatorgen.geometry.coil_generators import make_coil_generator
from pcbstatorgen.magnetic.force_eval import ForceEvaluator
from pcbstatorgen.magnetic.magnet_model import MagnetArray
from pcbstatorgen.stackup.friction import FrictionEstimator
from pcbstatorgen.stackup.height_stack import HeightStackCalculator
from pcbstatorgen.stackup.power import PowerEstimator
from pcbstatorgen.units import mm, mils_to_m

st.set_page_config(
    page_title="pcbstatorgen",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

_SPACING_RATIOS = {
    "1:1 Standard (Maximum Fundamental Force)": 1.0,
    "Vernier 4:5 (Suppresses 5th Harmonic)": 0.8,
    "Vernier 5:6 (Suppresses 6th Harmonic)": 0.8333,
}

_ARR_MULT = {
    MagnetArrangement.ALTERNATING: 1.00,
    MagnetArrangement.HALBACH: 1.43,
    MagnetArrangement.ALTERNATING_BACK_IRON: 1.42,
    MagnetArrangement.HALBACH_BACK_IRON: 1.68,
}

_TOPO_MULT = {
    CoilTopology.SERPENTINE: 1.00,
    CoilTopology.SINE_WAVE: 0.78,
}

_ARR_LABELS = {
    MagnetArrangement.ALTERNATING: "Simple Alternating Poles",
    MagnetArrangement.HALBACH: "Halbach Array",
    MagnetArrangement.ALTERNATING_BACK_IRON: "Alternating + Back-Iron",
    MagnetArrangement.HALBACH_BACK_IRON: "Halbach + Back-Iron",
}

_TOPO_LABELS = {
    CoilTopology.SERPENTINE: "Square Serpentine",
    CoilTopology.SINE_WAVE: "Sine Wave Serpentine",
}

_PHASE_COLORS = ["#e74c3c", "#2ecc71", "#3498db", "#9b59b6", "#f39c12", "#1abc9c"]

_DEFAULTS = {
    "motor_class": "Linear",
    "coil_topology": CoilTopology.SERPENTINE,
    "spacing_ratio_label": list(_SPACING_RATIOS.keys())[0],
    "magnet_grade": "N44",
    "magnet_remanence_t": 1.34,
    "magnet_arrangement": MagnetArrangement.ALTERNATING,
    "magnet_width_mm": 10.0,
    "magnet_gap_mm": 2.0,
    "magnet_height_mm": 4.0,
    "magnet_length_mm": 10.0,
    "air_gap_mm": 0.5,
    "back_iron_mm": 0.0,
    "phases": 3,
    "max_current_a": 1.0,
    "supply_v": 5.0,
    "layers": 6,
    "min_trace_mil": 5.0,
    "min_space_mil": 5.0,
    "active_area_length_mm": 200.0,
    "board_width_mm": 20.0,
    "mass_g": 15.0,
    "friction_mn": 50.0,
    "target_force_n": 0.5,
    "magnet_count": 10,
}

for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


def _badge(value: float, good: float, warn: float, higher_is_better: bool = True) -> str:
    if higher_is_better:
        return "🟢" if value >= good else ("🟡" if value >= warn else "🔴")
    return "🟢" if value <= good else ("🟡" if value <= warn else "🔴")


def _estimate_force_n(config, n_layers: int) -> float:
    try:
        hz = HeightStackCalculator()
        bz_peak = hz.field_at_gap(config, config.air_gap_m)
        bz_mean = bz_peak * 0.55
        n_cond = config.active_length_m / config.pole_pitch_m
        layers_per_phase = n_layers // config.phases
        F = (
            config.max_current_a
            * config.board_width_m
            * bz_mean
            * n_cond
            * layers_per_phase
            * _ARR_MULT.get(config.magnet_arrangement, 1.0)
            * _TOPO_MULT.get(config.coil_topology, 1.0)
        )
        return max(0.0, float(F))
    except Exception:
        return 0.0


def build_config():
    s = st.session_state
    try:
        mw = mm(s["magnet_width_mm"])
        gap = mm(s["magnet_gap_mm"])
        pitch = mw + gap
        height = mm(s["magnet_height_mm"])
        length = mm(s["magnet_length_mm"])
        air_gap = mm(s["air_gap_mm"])
        coil_topo = s["coil_topology"]
        arrangement = s["magnet_arrangement"]
        phases = s["phases"]
        max_i = s["max_current_a"]
        supply_v = s["supply_v"]
        min_trace = mils_to_m(s["min_trace_mil"])
        min_space = mils_to_m(s["min_space_mil"])
        n_layers = s["layers"]
        ratio = _SPACING_RATIOS.get(s["spacing_ratio_label"], 1.0)
        grade = s["magnet_grade"]

        if arrangement in (MagnetArrangement.ALTERNATING_BACK_IRON, MagnetArrangement.HALBACH_BACK_IRON):
            back_iron = mm(s["back_iron_mm"])
        else:
            back_iron = 0.0

        if grade == CUSTOM_GRADE:
            remanence = s["magnet_remanence_t"]
        else:
            remanence = get_remanence(grade)

        common = dict(
            magnet_dims_m=(mw, length, height),
            magnet_count=s["magnet_count"],
            magnet_pitch_m=pitch,
            magnet_grade=grade,
            magnet_remanence_t=remanence,
            magnet_arrangement=arrangement,
            back_iron_thickness_m=back_iron,
            coil_topology=coil_topo,
            phases=phases,
            spacing_ratio=ratio,
            max_current_a=max_i,
            supply_voltage_v=supply_v,
            min_trace_m=min_trace,
            min_space_m=min_space,
            min_via_drill_m=mm(0.2),
            min_via_annular_ring_m=mm(0.1),
            air_gap_m=air_gap,
            max_layers=n_layers,
        )

        return LinearMotorConfig(
            name=f"linear-{s['active_area_length_mm']:.0f}mm",
            active_area_length_m=mm(s["active_area_length_mm"]),
            target_force_n=s["target_force_n"],
            peak_force_n=s["target_force_n"] * 2.0,
            friction_n=s["friction_mn"] / 1000.0,
            carriage_mass_kg=s["mass_g"] / 1000.0,
            board_width_m=mm(s["board_width_mm"]),
            pcb_thickness_m=0.0016,
            capacitor_bank_uf=1000.0,
            **common,
        )
    except Exception as exc:
        st.error(f"Configuration error: {exc}")
        return None


def _plot_coil_geometry(coils):
    fig, ax = plt.subplots(figsize=(10, 4))
    for i, coil in enumerate(coils):
        color = _PHASE_COLORS[i % len(_PHASE_COLORS)]
        for seg in coil.segments:
            x = [seg.start[0] * 1000, seg.end[0] * 1000]
            y = [seg.start[1] * 1000, seg.end[1] * 1000]
            ls = "-" if seg.is_active else "--"
            lw = 1.5 if seg.is_active else 0.8
            ax.plot(x, y, color=color, linestyle=ls, linewidth=lw)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.set_title("Coil Geometry Preview")
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def _plot_force(result):
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(result.positions_m * 1000, result.force_x_n * 1000, color="#3498db", linewidth=1.5)
    ax.axhline(
        result.mean_thrust_n * 1000,
        color="#e74c3c",
        linestyle="--",
        label=f"Mean: {result.mean_thrust_n * 1000:.1f} mN",
    )
    ax.fill_between(
        result.positions_m * 1000,
        result.min_thrust_n * 1000,
        result.peak_thrust_n * 1000,
        alpha=0.15,
        color="#3498db",
        label=f"Ripple: {result.ripple_pct:.1f}%",
    )
    ax.set_xlabel("Position (mm)")
    ax.set_ylabel("Force (mN)")
    ax.set_title("Force vs Position")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def _plot_bfield(config):
    arr = MagnetArray(config)
    x_sample = np.linspace(0, config.active_length_m, 200)
    b = arr.bfield_at_pcb_surface(x_sample)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(x_sample * 1000, b[:, 2] * 1000, color="#2ecc71", linewidth=1.5, label="Bz")
    ax.plot(x_sample * 1000, b[:, 0] * 1000, color="#e74c3c", linewidth=1, alpha=0.5, label="Bx")
    ax.set_xlabel("Position (mm)")
    ax.set_ylabel("B-field (mT)")
    ax.set_title("Magnetic B-Field at PCB Surface")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def _plot_height_stack(config, hs):
    stack_items = [
        ("PCB Substrate", config.pcb_thickness_m * 1000, "#2c3e50"),
        ("Copper Layers", 0.035 * config.max_layers, "#f39c12"),
        ("Solder Mask", 0.020, "#27ae60"),
        ("Air Gap", config.air_gap_m * 1000, "#3498db"),
        ("Magnets", config.magnet_dims_m[2] * 1000, "#e74c3c"),
    ]
    if config.back_iron_thickness_m > 0:
        stack_items.append(("Back-Iron", config.back_iron_thickness_m * 1000, "#7f8c8d"))
    fig, ax = plt.subplots(figsize=(8, 3))
    left = 0
    for label, thick, color in stack_items:
        ax.barh(0, thick, left=left, height=0.6, color=color, alpha=0.85, label=label)
        if thick > 0.1:
            ax.text(left + thick / 2, 0, f"{thick:.2f}", ha="center", va="center", fontsize=7, color="white")
        left += thick
    ax.set_xlim(0, left * 1.1)
    ax.set_yticks([])
    ax.set_xlabel("Thickness (mm)")
    ax.set_title(f"Height Stack: {hs.total_height_m * 1000:.2f} mm total")
    ax.legend(fontsize=7, loc="upper right")
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def _plot_force_budget(em_force_mn: float, friction_mn: float):
    net = max(0.0, em_force_mn - friction_mn)
    fig, ax = plt.subplots(figsize=(8, 2))
    ax.barh(0, net, height=0.4, color="#2ecc71", label=f"Net Usable ({net:.0f} mN)")
    ax.barh(0, friction_mn, left=net, height=0.4, color="#e74c3c", label=f"Friction ({friction_mn:.0f} mN)")
    ax.set_xlim(0, max(em_force_mn, friction_mn, 1.0) * 1.2)
    ax.set_yticks([])
    ax.set_xlabel("Force (mN)")
    ax.set_title(f"Force Budget (EM Force: {em_force_mn:.0f} mN)")
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def render_output_tabs(config):
    tab_geom, tab_force, tab_bfield, tab_stack = st.tabs(
        ["Coil Geometry", "Force Plot", "B-Field", "Height Stack"]
    )

    with tab_geom:
        coils = st.session_state.get("coils")
        if coils:
            _plot_coil_geometry(coils)
        else:
            st.info("Click 'Run Force/Torque Preview' to generate coil geometry.")

    with tab_force:
        result = st.session_state.get("force_result")
        if result:
            _plot_force(result)
        else:
            st.info("Click 'Run Force/Torque Preview' to compute the force sweep.")

    with tab_bfield:
        try:
            _plot_bfield(config)
        except Exception as exc:
            st.warning(f"B-field computation failed: {exc}")

    with tab_stack:
        hs = HeightStackCalculator().calculate(config)
        _plot_height_stack(config, hs)


with st.sidebar:
    st.title("⚡ pcbstatorgen")
    st.caption("Multiphysics PCB Stator Motor Generator")
    st.divider()

    st.selectbox(
        "Coil Topology",
        options=list(_TOPO_LABELS.keys()),
        format_func=lambda t: _TOPO_LABELS[t],
        key="coil_topology",
    )

    st.selectbox(
        "Winding Spacing Ratio",
        options=list(_SPACING_RATIOS.keys()),
        key="spacing_ratio_label",
        help="Vernier ratios cancel spatial force harmonics, reducing ripple "
        "at the cost of slightly lower fundamental force.",
    )

    st.divider()
    st.caption("ℹ️ Local-first drafting to KiCad 10 via IPC API. Physics powered by Magpylib.")


st.title("🛠️ PCB Stator Motor Generator")

st.radio(
    "Motor Class",
    ["Linear Motion", "Radial Motion (TODO — not yet implemented)"],
    index=0,
    disabled=True,
    help="Radial (axial-flux) mode is a design stub. Implementation tracked as future work.",
)
st.session_state["motor_class"] = "Linear"

config = build_config()

col_btn, col_status = st.columns([1, 2])
with col_btn:
    if st.button("⚡ Run Force/Torque Preview", type="primary"):
        if config:
            try:
                with st.spinner("Computing force sweep..."):
                    coils = make_coil_generator(config.coil_topology).generate(config)
                    evaluator = ForceEvaluator(n_positions=50)
                    result = evaluator.evaluate(config, coils)
                    st.session_state["force_result"] = result
                    st.session_state["coils"] = coils
            except Exception as exc:
                st.error(f"Force evaluation failed: {exc}")
with col_status:
    _result = st.session_state.get("force_result")
    if _result:
        st.caption(
            f"Last sweep: ripple={_result.ripple_pct:.1f}%, "
            f"mean={_result.mean_thrust_n * 1000:.1f} mN, "
            f"peak={_result.peak_thrust_n * 1000:.1f} mN"
        )
    else:
        st.caption("No force sweep computed yet. Adjust parameters and click Run.")

st.divider()

col_params, col_feedback = st.columns([1, 1])

with col_params:
    st.subheader("Parameters")

    if st.session_state["motor_class"] == "Linear":
        st.number_input(
            "Active Area Length (mm)",
            min_value=10.0,
            max_value=1000.0,
            step=5.0,
            key="active_area_length_mm",
            help="Physical length of the stator copper trace region (PCB board constraint). "
            "Travel is derived: travel = active_area - coil_span (mover array length).",
        )
        st.number_input(
            "Active Area Width (mm)",
            min_value=1.0,
            max_value=100.0,
            step=1.0,
            key="board_width_mm",
            help="Width of the copper trace region perpendicular to travel (drives Lorentz force).",
        )
        st.number_input("Mover Carriage Mass (g)", min_value=1.0, max_value=2000.0, step=1.0, key="mass_g")
        st.number_input(
            "Friction (mN)",
            min_value=0.0,
            max_value=1000.0,
            step=5.0,
            key="friction_mn",
            help="Estimated total mechanical friction force.",
        )
        st.number_input("Target Continuous Force (N)", min_value=0.05, max_value=10.0, step=0.05, key="target_force_n")

    st.divider()
    st.markdown("**Magnet Array**")

    grade_options = GRADE_NAMES + [CUSTOM_GRADE]
    st.selectbox(
        "Magnet Grade",
        grade_options,
        key="magnet_grade",
        format_func=lambda g: g if g == CUSTOM_GRADE else f"{g} (Br: {get_grade(g).br_typ_t:.2f} T)",
    )

    if st.session_state["magnet_grade"] != CUSTOM_GRADE:
        _grade = get_grade(st.session_state["magnet_grade"])
        st.caption(
            f"Br: {_grade.br_min_t:.2f}–{_grade.br_max_t:.2f} T (typ: {_grade.br_typ_t:.2f} T) | "
            f"Max temps: {', '.join(f'{k}={v}°C' for k, v in _grade.max_temp_c.items())}"
        )
    else:
        st.number_input("Custom Remanence Br (T)", min_value=0.1, max_value=2.0, step=0.01, key="magnet_remanence_t")

    st.selectbox(
        "Magnet Arrangement",
        options=list(_ARR_LABELS.keys()),
        format_func=lambda a: _ARR_LABELS[a],
        key="magnet_arrangement",
    )

    if st.session_state["magnet_arrangement"] in (
        MagnetArrangement.ALTERNATING_BACK_IRON,
        MagnetArrangement.HALBACH_BACK_IRON,
    ):
        if st.session_state.get("back_iron_mm", 0.0) < 0.5:
            st.session_state["back_iron_mm"] = 1.0
        st.slider("Back-Iron Thickness (mm)", min_value=0.5, max_value=5.0, step=0.5, key="back_iron_mm")

    st.number_input("Magnet Width — along travel (mm)", min_value=1.0, max_value=50.0, step=0.1, key="magnet_width_mm")
    st.number_input(
        "Gap Between Magnets (mm)",
        min_value=0.0,
        max_value=20.0,
        step=0.1,
        key="magnet_gap_mm",
        help="Edge-to-edge gap between adjacent magnets. 0 = touching (continuous array). "
        "Pole pitch = magnet width + gap (computed dynamically).",
    )
    st.number_input(
        "Number of Magnets (mover array)",
        min_value=2,
        max_value=50,
        step=2,
        key="magnet_count",
        help="Number of magnets in the mover carriage array. Must be even for alternating poles. "
        "More magnets = longer mover = longer stator track needed to maintain coupling at travel extremes.",
    )
    st.number_input("Magnet Height (mm)", min_value=0.5, max_value=20.0, step=0.5, key="magnet_height_mm")
    st.number_input("Magnet Length — across stator (mm)", min_value=1.0, max_value=100.0, step=1.0, key="magnet_length_mm")
    st.number_input("Air Gap Clearance (mm)", min_value=0.05, max_value=10.0, step=0.05, key="air_gap_mm")

    st.divider()
    st.markdown("**Electrical**")
    st.select_slider("Phases", options=[1, 2, 3], key="phases")
    st.number_input("Max Current (A)", min_value=0.1, max_value=50.0, step=0.1, key="max_current_a")
    st.number_input("Supply Voltage (V)", min_value=1.0, max_value=120.0, step=0.5, key="supply_v")

    st.divider()
    st.markdown("**PCB Manufacturing**")
    st.select_slider("Max Layers", options=[4, 6, 8, 10, 12], key="layers")
    st.selectbox("Min Trace Width (mil)", options=[3.0, 4.0, 5.0, 6.0, 8.0, 10.0], key="min_trace_mil")
    st.selectbox("Min Trace Spacing (mil)", options=[3.0, 4.0, 5.0, 6.0, 8.0, 10.0], key="min_space_mil")

with col_feedback:
    st.subheader("Live Feedback")

    if config:
        force_est = _estimate_force_n(config, config.max_layers)
        hs = HeightStackCalculator().calculate(config)
        pb = PowerEstimator(layers_per_phase=config.max_layers // config.phases).estimate(config)

        pole_pitch_mm = config.pole_pitch_m * 1000
        magnet_gap_mm = config.magnet_gap_m * 1000

        c1, c2, c3 = st.columns(3)

        force_mn = force_est * 1000
        target_f = config.target_force_n * 1000
        c1.metric(
            f"Cont. Force {_badge(force_est, config.target_force_n, config.target_force_n * 0.8)}",
            f"{force_mn:.0f} mN",
            delta=f"{force_mn - target_f:+.0f} mN vs target",
        )

        c2.metric(
            f"Temp Rise {_badge(pb.temperature_rise_c, config.max_temperature_rise_c, config.max_temperature_rise_c * 1.5, higher_is_better=False)}",
            f"+{pb.temperature_rise_c:.0f} °C",
            delta=f"budget +{config.max_temperature_rise_c:.0f} °C",
        )
        c3.metric("Phase Resistance", f"{pb.phase_resistance_ohm:.2f} Ω")

        st.caption(
            f"**Pole Pitch:** {pole_pitch_mm:.2f} mm "
            f"(= {config.magnet_dims_m[0] * 1000:.1f} mm magnet + {magnet_gap_mm:.1f} mm gap)"
        )

        if st.session_state["motor_class"] == "Linear":
            active_mm = config.active_area_length_m * 1000
            travel_mm = config.travel_m * 1000
            coil_span_mm = config.coil_span_m * 1000
            st.caption(
                f"**Stator track (active area):** {active_mm:.1f} mm (INPUT)"
            )
            st.caption(
                f"**Mover (magnet array):** {coil_span_mm:.1f} mm "
                f"({config.magnet_count} magnets × {pole_pitch_mm:.1f} mm pitch)"
            )
            if travel_mm > 0:
                st.caption(
                    f"**Usable travel:** {travel_mm:.1f} mm (DERIVED = {active_mm:.1f} − {coil_span_mm:.1f})"
                )
            else:
                st.warning(
                    f"Active area ({active_mm:.0f} mm) must be longer than the mover array "
                    f"({coil_span_mm:.0f} mm). Increase active area length or reduce magnet count."
                )

        st.caption(f"**Height Stack:** {hs.total_height_m * 1000:.2f} mm total")

        st.markdown("**Force Budget**")
        _plot_force_budget(force_est * 1000, config.friction_n * 1000)

        st.info(
            "**Zero-Cogging:** Coreless (air-core) PCB stator → F_cogging = 0. "
            "No ferromagnetic slots to attract magnets."
        )

        _result = st.session_state.get("force_result")
        if _result:
            ri_badge = _badge(_result.ripple_pct, 5.0, 15.0, higher_is_better=False)
            st.metric(
                f"Force Ripple {ri_badge}",
                f"{_result.ripple_pct:.1f}%",
                delta=f"peak: {_result.peak_thrust_n * 1000:.1f} mN, min: {_result.min_thrust_n * 1000:.1f} mN",
            )
        else:
            st.caption("💡 Click 'Run Force/Torque Preview' to compute force ripple.")
    else:
        st.warning("Configuration invalid. Adjust parameters.")

st.divider()

if config:
    render_output_tabs(config)
