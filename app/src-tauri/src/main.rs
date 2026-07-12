//! pcbstatorgen Tauri host — entry point.
//!
//! Registers all `#[tauri::command]` async handlers from `commands.rs` and
//! `ipc.rs` with the Tauri v2 `Builder`. The frontend (`app/src/`) calls these
//! via `invoke("command_name", { config })` (see `app/src/lib/tauri.ts`).
//!
//! Linear mode only (PRODUCT_GOALS.md §7.A). No radial commands are exposed.

mod commands;
mod ipc;

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            commands::compute_config_derived,
            commands::validate_config,
            commands::get_magnet_grades,
            commands::compute_height_stack,
            commands::generate_coils,
            commands::evaluate_force_sweep,
            commands::compute_stackup,
            commands::compute_power_budget,
            commands::compute_friction,
        ])
        .run(tauri::generate_context!())
        .expect("error while running pcbstatorgen tauri application");
}
