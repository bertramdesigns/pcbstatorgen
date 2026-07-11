"""
gui/streamlit_app.py — PCB Motor Coil Generator Dashboard
==========================================================
Run with:
    streamlit run gui/streamlit_app.py

Requires KiCad 10 to be open (with IPC API enabled) only for the
"Write to KiCad" tab — all other tabs work offline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import streamlit as st

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pcbstatorgen.config import MotorConfig, StackupResult
from pcbstatorgen.units import mm, mils_to_m, oz_to_m, m_to_mm, m_to_mils, skin_depth_m

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="PCB Motor Coil Generator",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def eli5(text: str) -> None:
    """Render an ELI5 tooltip block."""
    st.caption(f"💡 {text}")


def good_bad(value: float, good_threshold: float, bad_threshold: float,
             higher_is_better: bool = True) -> str:
    """Return a coloured emoji based on a threshold."""
    if higher_is_better:
        if value >= good_threshold:
            return "🟢"
        if value >= bad_threshold:
            return "🟡"
        return "🔴"
    else:
        if value <= good_threshold:
            return "🟢"
        if value <= bad_threshold:
            return "🟡"
        return "🔴"


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — MotorConfig parameters
# ─────────────────────────────────────────────────────────────────────────────

st.sidebar.title("⚙️ Motor Parameters")
st.sidebar.markdown("Drag the sliders to configure your fader. Everything updates live.")

with st.sidebar.expander("📏 Fader Travel & Board", expanded=True):
    travel_mm = st.slider(
        "Travel distance (mm)",
        min_value=40.0, max_value=120.0, value=75.0, step=5.0,
    )
    eli5("How far the fader knob slides from one end to the other.")

    board_width_mm = st.slider(
        "Board width (mm)",
        min_value=10.0, max_value=40.0, value=20.0, step=1.0,
    )
    eli5("How wide the PCB is, measured across the travel direction.")

    air_gap_mm = st.slider(
        "Air gap (mm)",
        min_value=0.2, max_value=3.0, value=0.5, step=0.1,
    )
    eli5("The gap between the bottom of the magnets and the top copper on the PCB. "
         "Smaller = stronger force, but tighter to assemble.")

with st.sidebar.expander("🧲 Magnet Array", expanded=True):
    magnet_count = st.select_slider(
        "Number of magnets",
        options=[4, 6, 8, 10, 12, 14], value=10,
    )
    eli5("More magnets = more force, but the fader gets heavier and more expensive.")

    pitch_mm = st.slider(
        "Magnet pitch (mm)",
        min_value=6.0, max_value=20.0, value=12.0, step=1.0,
    )
    eli5("Centre-to-centre spacing between adjacent magnets. "
         "Smaller pitch = more poles = smoother fader feel.")

    magnet_w_mm = st.slider(
        "Magnet width (mm) — travel axis",
        min_value=4.0, max_value=15.0, value=10.0, step=1.0,
    )
    magnet_l_mm = st.slider(
        "Magnet length (mm) — cross axis",
        min_value=4.0, max_value=25.0, value=10.0, step=1.0,
    )
    magnet_h_mm = st.slider(
        "Magnet height (mm)",
        min_value=2.0, max_value=8.0, value=4.0, step=0.5,
    )
    eli5("Taller magnets have more magnetic material = stronger field at the PCB, "
         "but the fader assembly gets thicker.")

    remanence_t = st.slider(
        "Magnet grade — Br (T)",
        min_value=0.9, max_value=1.5, value=1.35, step=0.01,
        help="Remnant flux density. N44H at 20°C ≈ 1.35 T",
    )
    eli5("How 'strong' the magnet material is. N44H is a good high-performance grade. "
         "Higher = more force per magnet.")

with st.sidebar.expander("⚡ Electrical", expanded=True):
    phases = st.select_slider("Phases", options=[1, 2, 3], value=3)
    eli5("3-phase motors produce smoother, constant force. Like a car engine with 3 cylinders "
         "firing in sequence rather than 1 big cylinder banging.")

    target_force_n = st.slider(
        "Target force (mN)",
        min_value=50.0, max_value=2000.0, value=500.0, step=50.0,
    )
    eli5("The minimum force the motor needs to produce to move the fader reliably. "
         "500 mN (0.5 N) feels like the weight of a small apple pushing the fader.")

    max_current_a = st.slider(
        "Peak current (A)",
        min_value=0.2, max_value=3.0, value=1.0, step=0.1,
    )
    eli5("The most current the drive chip (STM G4) will push through the coil. "
         "More current = more force, but also more heat.")

with st.sidebar.expander("🏭 PCB Manufacturing Rules", expanded=False):
    min_trace_mil = st.select_slider(
        "Min trace width (mil)",
        options=[3, 3.5, 4, 5, 6, 8, 10], value=5,
    )
    eli5("The thinnest copper line the factory can reliably make. "
         "5 mil (0.127 mm) is JLCPCB's standard tier.")

    min_space_mil = st.select_slider(
        "Min trace spacing (mil)",
        options=[3, 3.5, 4, 5, 6, 8, 10], value=5,
    )
    eli5("The smallest gap allowed between two copper lines. "
         "Too close and the voltage can arc between them.")

    via_drill_mm = st.select_slider(
        "Via drill (mm)",
        options=[0.15, 0.2, 0.25, 0.3], value=0.2,
    )
    eli5("The hole drilled through all layers to connect them. "
         "Smaller holes are harder to drill but allow tighter layouts.")

    max_layers = st.select_slider(
        "Max copper layers",
        options=[4, 6, 8, 10, 12], value=12,
    )
    eli5("How many copper layers the optimizer is allowed to use. "
         "More layers = more force, but higher PCB cost.")

# ─────────────────────────────────────────────────────────────────────────────
# Build MotorConfig from sidebar inputs (validate gracefully)
# ─────────────────────────────────────────────────────────────────────────────

config_error = None
config = None
try:
    config = MotorConfig(
        travel_m=mm(travel_mm),
        magnet_dims_m=(mm(magnet_w_mm), mm(magnet_l_mm), mm(magnet_h_mm)),
        magnet_count=magnet_count,
        magnet_pitch_m=mm(pitch_mm),
        magnet_remanence_t=remanence_t,
        phases=phases,
        target_force_n=target_force_n / 1000.0,
        max_current_a=max_current_a,
        min_trace_m=mils_to_m(min_trace_mil),
        min_space_m=mils_to_m(min_space_mil),
        min_via_drill_m=mm(via_drill_mm),
        min_via_annular_ring_m=mm(0.1),
        board_width_m=mm(board_width_mm),
        air_gap_m=mm(air_gap_mm),
        max_layers=max_layers,
        drive_frequency_hz=500.0,
    )
except ValueError as e:
    config_error = str(e)

# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────

st.title("⚡ PCB Motor Coil Generator")
st.markdown(
    "A tool for designing the copper coil layout of a **linear coreless motor** "
    "for an audio mixing fader. Configure your motor on the left, then explore "
    "each tab to understand what the generator will produce."
)

if config_error:
    st.error(f"⚠️ Invalid configuration: {config_error}")
    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────────────────────

tab_summary, tab_geometry, tab_magnets, tab_force, tab_kicad = st.tabs([
    "📋 Summary",
    "🔀 Coil Geometry",
    "🧲 Magnet Field",
    "📈 Force Preview",
    "🖥️ Write to KiCad",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Summary
# ══════════════════════════════════════════════════════════════════════════════

with tab_summary:
    st.subheader("Configuration Summary")
    st.markdown(
        "This shows what your current settings mean in plain English. "
        "Change any slider on the left and this updates instantly."
    )

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        st.metric("Travel", f"{travel_mm:.0f} mm")
        st.metric("PCB Length (min)", f"{m_to_mm(config.active_length_m):.0f} mm",
                  help="travel + coil span = the minimum board length needed")
        st.metric("Pole pitch", f"{m_to_mm(config.pole_pitch_m):.0f} mm")
        st.metric("Slot pitch", f"{m_to_mm(config.slot_pitch_m):.1f} mm",
                  delta=f"pole / {phases} phases")

    with col_b:
        st.metric("Magnet array span", f"{m_to_mm(config.coil_span_m):.0f} mm",
                  help=f"{magnet_count} magnets × {pitch_mm} mm pitch")
        st.metric("Air gap", f"{air_gap_mm:.1f} mm")
        st.metric("Target force", f"{target_force_n:.0f} mN",
                  help="Minimum continuous thrust required")
        st.metric("Peak current", f"{max_current_a:.1f} A")

    with col_c:
        st.metric("Min trace/space", f"{min_trace_mil} / {min_space_mil} mil",
                  help=f"= {mils_to_m(min_trace_mil)*1e3:.3f} / {mils_to_m(min_space_mil)*1e3:.3f} mm")
        st.metric("Via drill", f"{via_drill_mm} mm")
        st.metric("Max layers", f"{max_layers}")

    st.divider()

    # Conductor count preview
    from pcbstatorgen.geometry.wave_winding import WaveWindingGenerator
    gen = WaveWindingGenerator()
    n_conductors = len(gen.conductor_x_positions(config, 0))
    n_end_turns = n_conductors - 1

    st.subheader("What gets generated")
    col1, col2, col3 = st.columns(3)
    col1.metric("Active conductors / phase", n_conductors,
                help="Segments that cross the magnetic field and produce force")
    col2.metric("End-turns / phase", n_end_turns,
                help="Connecting segments at top/bottom board edges")
    col3.metric("Phases", phases)

    total_conductors = n_conductors * phases
    st.info(
        f"**{total_conductors} active conductor segments total** across {phases} phases. "
        f"Each segment runs the full {board_width_mm:.0f} mm board width. "
        f"Combined active copper length per layer: "
        f"{total_conductors * board_width_mm / 1000:.2f} m"
    )

    st.divider()
    st.subheader("Skin depth (AC loss guide)")
    st.markdown(
        "At high frequencies, current concentrates near the conductor surface — "
        "this is the **skin effect**. The 'skin depth' tells us how thick copper "
        "can be before AC losses become significant."
    )
    delta_500hz = skin_depth_m(500) * 1e6
    delta_1MHz = skin_depth_m(1e6) * 1e6

    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.metric("δ at 500 Hz (drive freq)", f"{delta_500hz:.0f} µm",
                  help="Skin depth at the motor's electrical frequency")
    col_s2.metric("δ at 1 MHz (PWM harmonics)", f"{delta_1MHz:.1f} µm",
                  help="1 oz copper (35 µm) < 66 µm → outer layers stay thin")
    col_s3.metric("1 oz copper", "35 µm",
                  delta="< δ(1 MHz) ✓" if 35 < delta_1MHz else "≥ δ(1 MHz)")

    eli5(
        "At 500 Hz (fader moving speed), the skin depth is millimetres thick — "
        "all copper layers are well within it, so no AC loss from the movement itself. "
        "At 1 MHz (PWM switching frequency harmonics), the skin depth is 66 µm — "
        "1 oz outer layers (35 µm) fit inside it, but 2 oz (70 µm) would stick out. "
        "That's why outer layers stay thin (1 oz) and inner layers go thick (2 oz+)."
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Coil Geometry
# ══════════════════════════════════════════════════════════════════════════════

with tab_geometry:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    st.subheader("Wave Winding Layout")
    st.markdown(
        "The coil is a **serpentine** (zigzag) pattern. Each phase has a separate "
        "serpentine, offset by the slot pitch. Different colours = different phases."
    )
    eli5(
        "Imagine three separate snakes, each slithering back and forth across the PCB, "
        "but starting at slightly different X positions. Each snake is one phase of the motor."
    )

    from pcbstatorgen.geometry.wave_winding import WaveWindingGenerator
    from pcbstatorgen.geometry.via_grid import ViaGridGenerator
    from pcbstatorgen.geometry.end_turn import EndTurnRouter

    gen = WaveWindingGenerator()
    coils = gen.generate(config)

    phase_colors = ["#e74c3c", "#2ecc71", "#3498db"]  # Red, Green, Blue
    phase_names = ["Phase A", "Phase B", "Phase C"]

    fig, ax = plt.subplots(figsize=(14, 4))

    for coil in coils:
        colour = phase_colors[coil.phase_idx % len(phase_colors)]
        pts = coil.polyline
        xs = [p[0] * 1000 for p in pts]  # m → mm
        ys = [p[1] * 1000 for p in pts]
        # Active conductors: solid lines
        for seg in coil.active_segments:
            ax.plot(
                [seg.start[0] * 1000, seg.end[0] * 1000],
                [seg.start[1] * 1000, seg.end[1] * 1000],
                color=colour, linewidth=2, solid_capstyle="round",
            )
        # End-turns: dashed lines
        for seg in coil.end_turn_segments:
            ax.plot(
                [seg.start[0] * 1000, seg.end[0] * 1000],
                [seg.start[1] * 1000, seg.end[1] * 1000],
                color=colour, linewidth=1, linestyle="--", alpha=0.6,
            )

    # Board outline
    board_len_mm = m_to_mm(config.active_length_m)
    ax.set_xlim(-5, board_len_mm + 10)
    ax.set_ylim(-3, m_to_mm(config.board_width_m) + 3)
    ax.axhline(0, color="gray", linewidth=0.5, linestyle=":")
    ax.axhline(m_to_mm(config.board_width_m), color="gray", linewidth=0.5, linestyle=":")

    # Legend
    patches = [
        mpatches.Patch(color=phase_colors[p], label=f"{phase_names[p]} (active)")
        for p in range(min(phases, 3))
    ]
    ax.legend(handles=patches, loc="upper right", fontsize=8)
    ax.set_xlabel("Travel axis X (mm)")
    ax.set_ylabel("Board width Y (mm)")
    ax.set_title(
        f"{phases}-phase wave winding  |  {n_conductors} conductors/phase  |  "
        f"slot pitch = {m_to_mm(config.slot_pitch_m):.1f} mm"
    )
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    st.divider()
    st.subheader("Via Grid Preview")
    st.markdown(
        "Instead of one large via at each layer transition, the generator places "
        "a **grid of small vias**. This spreads the current and keeps things cool."
    )
    eli5(
        "Think of it like splitting a river into many small streams instead of "
        "one big flood channel. Each stream carries a small amount of water "
        "(current), so none of them get hot."
    )

    via_gen = ViaGridGenerator()
    sample_grid = via_gen.generate_for_end_turn(
        center=(config.pole_pitch_m / 2, 0.0),
        available_x_m=config.pole_pitch_m,
        available_y_m=mm(2),
        current_a=config.max_current_a,
        config=config,
    )

    col_v1, col_v2, col_v3, col_v4 = st.columns(4)
    col_v1.metric("Vias per end-turn", sample_grid.count)
    col_v2.metric("Via drill", f"{via_drill_mm} mm")
    col_v3.metric("Via pad", f"{m_to_mm(sample_grid.pad_diameter_m):.2f} mm")
    cap = sample_grid.current_capacity_a()
    margin = cap / config.max_current_a
    icon = good_bad(margin, 4.0, 2.0, higher_is_better=True)
    col_v4.metric("Current margin", f"{margin:.0f}×  {icon}",
                  help=f"{cap:.1f} A capacity / {config.max_current_a} A required")

    eli5(
        f"Each 0.2 mm via can carry ~0.5 A safely. You have {sample_grid.count} vias in "
        f"parallel, giving {cap:.0f} A total capacity — that's {margin:.0f}× your "
        f"peak current of {config.max_current_a} A. Green means lots of headroom."
    )

    # Via grid visualisation
    fig2, ax2 = plt.subplots(figsize=(6, 3))
    positions = sample_grid.positions()
    center_mm = (config.pole_pitch_m / 2 * 1000, 0)
    pad_mm = m_to_mm(sample_grid.pad_diameter_m)
    for (vx, vy) in positions:
        circle = plt.Circle((vx * 1000 - center_mm[0], vy * 1000), pad_mm / 2,
                             color="#f39c12", alpha=0.7)
        drill = plt.Circle((vx * 1000 - center_mm[0], vy * 1000), via_drill_mm / 2,
                            color="#2c3e50", alpha=0.9)
        ax2.add_patch(circle)
        ax2.add_patch(drill)
    box_w = m_to_mm(config.pole_pitch_m)
    ax2.set_xlim(-box_w / 2 - 1, box_w / 2 + 1)
    ax2.set_ylim(-3, 3)
    ax2.set_aspect("equal")
    ax2.set_xlabel("mm (along travel axis)")
    ax2.set_ylabel("mm (across board)")
    ax2.set_title(
        f"{sample_grid.rows}×{sample_grid.cols} via grid  "
        f"({sample_grid.count} vias, {cap:.0f} A capacity)"
    )
    ax2.grid(True, alpha=0.2)
    fig2.tight_layout()
    st.pyplot(fig2)
    plt.close(fig2)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Magnet Field
# ══════════════════════════════════════════════════════════════════════════════

with tab_magnets:
    st.subheader("Magnet B-Field at PCB Surface")
    st.markdown(
        "This shows the magnetic field that the coil conductors 'feel'. "
        "The **vertical (Z) component** is the one that creates thrust — "
        "it flips sign from North to South poles."
    )
    eli5(
        "Imagine laying a thin sheet of paper flat. The magnets are above it, "
        "pointing up (North) or down (South) alternately. The arrows coming "
        "through the paper point up under North poles and down under South poles. "
        "This up/down field is what pushes the current-carrying wires sideways."
    )

    fader_pos_mm = st.slider(
        "Fader position (mm)", 0.0, float(travel_mm), 0.0, 1.0,
        key="fader_mag",
        help="Move the fader to see how the field shifts over the coil",
    )
    eli5("Drag this to see the field pattern move as the fader slides.")

    from pcbstatorgen.magnetic.magnet_model import MagnetArray

    arr = MagnetArray(config)
    x_sample = np.linspace(0, m_to_mm(config.active_length_m), 200)
    B = arr.bfield_at_pcb_surface(
        x_sample * 1e-3, fader_position_m=mm(fader_pos_mm)
    )

    fig3, axes = plt.subplots(2, 1, figsize=(13, 6), sharex=True)

    # Bz — the thrust-generating component
    axes[0].plot(x_sample, B[:, 2] * 1000, color="#e74c3c", linewidth=1.5)
    axes[0].axhline(0, color="gray", linewidth=0.5)
    axes[0].fill_between(x_sample, B[:, 2] * 1000, 0,
                         where=B[:, 2] > 0, alpha=0.15, color="#e74c3c",
                         label="North (up)")
    axes[0].fill_between(x_sample, B[:, 2] * 1000, 0,
                         where=B[:, 2] < 0, alpha=0.15, color="#3498db",
                         label="South (down)")
    axes[0].set_ylabel("Bz (mT)")
    axes[0].set_title("Vertical field Bz — this creates thrust force on conductors")
    axes[0].legend(loc="upper right", fontsize=8)
    axes[0].grid(True, alpha=0.2)

    # Bx — largely cancelled but shows coupling to end-turns
    axes[1].plot(x_sample, B[:, 0] * 1000, color="#9b59b6", linewidth=1.5, label="Bx")
    axes[1].plot(x_sample, B[:, 1] * 1000, color="#27ae60", linewidth=1.0,
                 linestyle="--", label="By", alpha=0.7)
    axes[1].axhline(0, color="gray", linewidth=0.5)
    axes[1].set_ylabel("B (mT)")
    axes[1].set_xlabel("Position along travel axis (mm)")
    axes[1].set_title("Horizontal field components (Bx = end-turn coupling, By ≈ 0 by symmetry)")
    axes[1].legend(loc="upper right", fontsize=8)
    axes[1].grid(True, alpha=0.2)

    fig3.tight_layout()
    st.pyplot(fig3)
    plt.close(fig3)

    # Key numbers
    bz_peak = float(np.max(np.abs(B[:, 2]))) * 1000
    bz_mean = float(np.mean(np.abs(B[:, 2]))) * 1000
    bx_peak = float(np.max(np.abs(B[:, 0]))) * 1000

    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Peak |Bz| at PCB", f"{bz_peak:.0f} mT",
                  help="Peak field the active conductors feel")
    col_m2.metric("Mean |Bz| at PCB", f"{bz_mean:.0f} mT",
                  help="Average field strength — proportional to achievable force")
    col_m3.metric("Peak |Bx| at PCB", f"{bx_peak:.0f} mT",
                  help="Stray field acting on end-turns (mostly cancelled)")

    eli5(
        f"Your magnet array produces a peak field of **{bz_peak:.0f} mT** at the PCB surface. "
        f"For comparison, the Earth's magnetic field is about 0.05 mT — yours is "
        f"{bz_peak / 0.05:.0f}× stronger. A typical fridge magnet is about 10 mT. "
        f"Strong field = more push on the coil = stronger motor."
    )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Force Preview
# ══════════════════════════════════════════════════════════════════════════════

with tab_force:
    st.subheader("Force vs Fader Position")
    st.markdown(
        "This uses **Magpylib's analytical force calculator** to estimate how "
        "much thrust the motor produces at each point along the travel range. "
        "A good motor has smooth, consistent force — low 'ripple'."
    )
    eli5(
        "Imagine pushing a toy car with your finger. If you push evenly all the way, "
        "that's low ripple — the fader feels smooth. If it lurches at some positions, "
        "that's high ripple — you'd feel bumps as you move the fader. "
        "3-phase motors are designed to have nearly zero ripple."
    )

    col_f1, col_f2 = st.columns([1, 3])
    with col_f1:
        n_positions = st.select_slider(
            "Resolution (positions)",
            options=[8, 12, 20, 30, 50], value=12,
            help="More positions = more accurate ripple, but slower",
        )
        meshing = st.select_slider(
            "Meshing accuracy",
            options=[5, 10, 15, 20], value=5,
            help="Higher = more accurate force per conductor, but slower",
        )
        commutation = st.radio(
            "Commutation mode",
            ["max_torque", "phase_a_only"],
            index=0,
            help="max_torque = realistic FOC drive; phase_a_only = simple test",
        )
        run_force = st.button("▶  Calculate Force", type="primary")
        eli5(
            "Resolution and meshing control accuracy vs speed. "
            "Start with low values (8, 5) — takes ~5 seconds. "
            "Increase for a final accurate result."
        )

    with col_f2:
        if run_force:
            from pcbstatorgen.geometry.wave_winding import WaveWindingGenerator
            from pcbstatorgen.magnetic.force_eval import ForceEvaluator

            with st.spinner("Computing magnetic force... this uses real physics!"):
                _gen = WaveWindingGenerator()
                _coils = _gen.generate(config)
                ev = ForceEvaluator(
                    n_positions=n_positions,
                    meshing=meshing,
                    commutation=commutation,
                )
                result = ev.evaluate(config, _coils)

            # Store result in session state so it persists after re-render
            st.session_state["force_result"] = result
            st.session_state["force_config_summary"] = (
                f"{phases}-phase, I={max_current_a}A, "
                f"{magnet_count} magnets, pitch={pitch_mm}mm, "
                f"gap={air_gap_mm}mm"
            )

        if "force_result" in st.session_state:
            result = st.session_state["force_result"]
            summary = st.session_state.get("force_config_summary", "")

            # Metrics
            cm1, cm2, cm3, cm4 = st.columns(4)
            target_n = target_force_n / 1000.0
            mean_mn = result.mean_thrust_n * 1000
            ripple = result.ripple_pct
            target_met = result.mean_thrust_n >= target_n

            cm1.metric(
                "Mean thrust",
                f"{mean_mn:.1f} mN",
                delta=f"{(result.mean_thrust_n - target_n)*1000:+.1f} mN vs target",
                delta_color="normal" if target_met else "inverse",
            )
            cm2.metric("Peak thrust", f"{result.peak_thrust_n*1000:.1f} mN")
            cm3.metric(
                "Ripple",
                f"{ripple:.1f} %  {good_bad(ripple, 5.0, 15.0, higher_is_better=False)}",
                help="< 5% is excellent for a smooth fader feel",
            )
            cm4.metric(
                "Target met",
                "✅ Yes" if target_met else "❌ No",
                delta=f"Need {target_force_n:.0f} mN",
            )

            # Force vs position plot
            fig4, axes4 = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
            pos_mm = result.positions_m * 1000

            axes4[0].plot(pos_mm, result.force_x_n * 1000, color="#e74c3c",
                         linewidth=2, label="Total X thrust")
            axes4[0].axhline(target_force_n, color="#27ae60", linewidth=1.5,
                            linestyle="--", label=f"Target ({target_force_n:.0f} mN)")
            axes4[0].axhline(result.mean_thrust_n * 1000, color="#f39c12",
                            linewidth=1, linestyle=":", label=f"Mean ({mean_mn:.1f} mN)")
            axes4[0].fill_between(pos_mm, result.force_x_n * 1000,
                                 result.mean_thrust_n * 1000, alpha=0.1, color="#e74c3c",
                                 label="Ripple region")
            axes4[0].set_ylabel("Thrust Fx (mN)")
            axes4[0].set_title(f"Thrust force — {summary}")
            axes4[0].legend(fontsize=8, loc="upper right")
            axes4[0].grid(True, alpha=0.2)

            # Per-phase
            for p in range(min(result.per_phase_force_x.shape[1], 3)):
                axes4[1].plot(
                    pos_mm, result.per_phase_force_x[:, p] * 1000,
                    color=["#e74c3c", "#2ecc71", "#3498db"][p],
                    linewidth=1.5, label=f"Phase {'ABC'[p]}",
                )
            axes4[1].axhline(0, color="gray", linewidth=0.5)
            axes4[1].set_ylabel("Per-phase Fx (mN)")
            axes4[1].set_xlabel("Fader position (mm)")
            axes4[1].set_title("Individual phase contributions (they sum to give total thrust)")
            axes4[1].legend(fontsize=8, loc="upper right")
            axes4[1].grid(True, alpha=0.2)

            fig4.tight_layout()
            st.pyplot(fig4)
            plt.close(fig4)

            if result.per_phase_force_x.shape[1] == 3:
                eli5(
                    f"The three phases (red, green, blue) each produce a wavy force. "
                    f"Because they're spaced 120° apart, when one is low, the other two "
                    f"fill in the gap. The total (top plot) should be nearly flat — "
                    f"your ripple is **{ripple:.1f}%**, meaning the force varies by "
                    f"{ripple:.1f}% above and below the average. "
                    + ("That's very smooth! ✅" if ripple < 5 else
                       "Aim for < 5% for a smooth fader feel." if ripple < 15 else
                       "This is quite bumpy — consider adjusting the geometry.")
                )

            with st.expander("📊 Full numeric results"):
                st.text(result.summary())
        else:
            st.info("👆 Click **Calculate Force** to run the Magpylib force model. "
                    "Takes 5–30 seconds depending on settings.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — Write to KiCad
# ══════════════════════════════════════════════════════════════════════════════

with tab_kicad:
    st.subheader("Write Layout to KiCad")
    st.markdown(
        "Once you're happy with the force and geometry, this tab connects to your "
        "running KiCad 10 instance and writes all the tracks and vias to the PCB."
    )
    eli5(
        "This is the 'print' button. Everything else in this app was just a preview. "
        "When you click Generate, the plugin talks to KiCad and draws the actual "
        "copper traces on your PCB file — as if you'd drawn them by hand, but in seconds."
    )

    st.info(
        "**Prerequisites:**\n"
        "1. KiCad 10 is running\n"
        "2. `Preferences → Plugins → Enable IPC API` is checked\n"
        "3. A `.kicad_pcb` file is open in the PCB Editor\n"
        "4. The board stackup is pre-configured (layers, copper weights)"
    )

    # Connection check
    col_k1, col_k2 = st.columns([1, 2])
    with col_k1:
        check_conn = st.button("🔌 Check KiCad Connection", type="secondary")

    if check_conn or "kicad_status" in st.session_state:
        if check_conn:
            with st.spinner("Connecting to KiCad IPC API..."):
                try:
                    from pcbstatorgen.kicad_writer.connection import KiCadConnection
                    conn = KiCadConnection()
                    conn.connect()
                    st.session_state["kicad_status"] = "connected"
                    st.session_state["kicad_board_name"] = conn.board_filename
                    st.session_state["kicad_layers"] = conn.copper_layer_count
                    conn.disconnect()
                except Exception as e:
                    st.session_state["kicad_status"] = f"error: {e}"

        status = st.session_state.get("kicad_status", "")
        if status == "connected":
            board = st.session_state.get("kicad_board_name", "(unknown)")
            layers = st.session_state.get("kicad_layers", "?")
            st.success(
                f"✅ Connected to KiCad  |  Board: **{board}**  |  "
                f"Copper layers: **{layers}**"
            )
            if layers < phases * 2:
                st.warning(
                    f"⚠️ The open board has {layers} copper layers, but {phases} phases "
                    f"need at least {phases * 2} layers (2 per phase). "
                    f"Reconfigure the stackup in KiCad Board Setup first."
                )
        elif status.startswith("error"):
            st.error(f"❌ Could not connect: {status[7:]}")
            st.markdown(
                "**Troubleshooting:**\n"
                "- Make sure KiCad 10 is running (not just open to the project manager)\n"
                "- Open the PCB Editor specifically\n"
                "- Check Preferences → Plugins → Enable IPC API\n"
                "- Run this dashboard from your **system Python**, not inside KiCad\n"
            )

    st.divider()

    # Pipeline preview
    st.subheader("Generation pipeline (not yet fully implemented)")
    steps = [
        ("Phase 1 ✅", "config.py, units.py", "MotorConfig + unit conversions", True),
        ("Phase 2 ✅", "geometry/", "Wave winding paths, via grids, end-turn routing", True),
        ("Phase 3 ✅", "magnetic/", "Magpylib force model, B-field evaluation", True),
        ("Phase 4 🔲", "stackup/", "LayerOptimizer — determines layer count + copper weights", False),
        ("Phase 5 🔲", "kicad_writer/", "Track, Via, Net, BoardStackup placement via IPC API", False),
        ("Phase 6 🔲", "optimization/", "bfieldtools stream function refinement (optional)", False),
        ("Phase 7 🔲", "export/", "GMSH + Elmer FEM case files", False),
    ]
    for phase, module, desc, done in steps:
        col_p1, col_p2, col_p3 = st.columns([1, 1.5, 4])
        col_p1.write(phase)
        col_p2.code(module)
        col_p3.write(desc)

    st.divider()
    st.subheader("Generate Board")
    if st.session_state.get("kicad_status") == "connected":
        st.button("🚀 Generate Coils in KiCad", type="primary", disabled=True,
                  help="Available after Phase 5 (KiCad writer) is implemented")
        st.info("The KiCad writer (Phase 5) is the next implementation phase. "
                "Once complete, this button will write all tracks and vias to your PCB.")
    else:
        st.button("🚀 Generate Coils in KiCad", type="primary", disabled=True)
        st.warning("Connect to KiCad first (button above).")

    # Show config that would be used
    with st.expander("📋 Configuration that will be sent to KiCad"):
        st.code(config.summary(), language="text")
