//! Unit conversion helpers. All internal calculations use SI (metres, Tesla,
//! Amperes, Ohms, Watts). Ports `pcbstatorgen/units.py`.

/// Electrical resistivity of annealed copper at 20 °C [Ω·m].
pub const RHO_CU: f64 = 1.724e-8;
/// Magnetic permeability of free space [H/m].
pub const MU_0: f64 = 4.0 * std::f64::consts::PI * 1e-7;
/// Nominal copper thickness for 1 oz/ft² [m].
pub const CU_1OZ_M: f64 = 35.0e-6;

/// Convert millimetres → metres.
pub fn mm(value: f64) -> f64 {
    value * 1e-3
}
/// Convert mils (thou) → metres.
pub fn mils_to_m(value: f64) -> f64 {
    value * 25.4e-6
}
/// Convert micrometres → metres.
pub fn um(value: f64) -> f64 {
    value * 1e-6
}
/// Convert metres → millimetres.
pub fn m_to_mm(value: f64) -> f64 {
    value * 1e3
}
/// Convert PCB copper weight (oz/ft²) → nominal thickness [m].
pub fn oz_to_m(oz: f64) -> f64 {
    oz * CU_1OZ_M
}
/// Convert copper thickness [m] → equivalent weight [oz/ft²].
pub fn m_to_oz(thickness_m: f64) -> f64 {
    thickness_m / CU_1OZ_M
}
/// Convert metres → KiCad IPC nanometres (int64).
pub fn m_to_nm(metres: f64) -> i64 {
    (metres * 1_000_000_000.0) as i64
}
/// Convert KiCad IPC nanometres → metres.
pub fn nm_to_m(nanometres: i64) -> f64 {
    nanometres as f64 / 1_000_000_000.0
}
/// Skin depth δ = sqrt(ρ / (π·f·µ_r·µ_0)) [m].
pub fn skin_depth_m(frequency_hz: f64, rho: f64, mu_r: f64) -> f64 {
    (rho / (std::f64::consts::PI * frequency_hz * mu_r * MU_0)).sqrt()
}
/// DC resistance per unit length of rectangular trace [Ω/m]: ρ / (w·t).
pub fn cu_resistance_per_length(width_m: f64, thickness_m: f64, rho: f64) -> f64 {
    rho / (width_m * thickness_m)
}
