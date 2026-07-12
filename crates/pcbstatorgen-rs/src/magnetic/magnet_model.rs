//! `MagnetArray` — builds and manages the magnet source assembly for all
//! four `MagnetArrangement` configurations.
//!
//! Ports `pcbstatorgen/magnetic/magnet_model.py`.
//!
//! ## Arrangement overview
//!
//! `Alternating` — Simple alternating ±Z poles.
//!
//! `Halbach` — X-polarised interleave cuboids inserted in the gap between
//! every adjacent pair of Z-polarised main magnets. The interleave magnets
//! concentrate flux on the stator face and self-cancel on the rear face,
//! giving ≈ 1.35–1.55× field boost.
//!
//! `AlternatingBackIron` / `HalbachBackIron` — Steel keeper (back-iron)
//! simulation via the method of images. Mirror-image copy of every magnet
//! placed on the other side of the steel–magnet interface with the same
//! polarisation, scaled by `_K_IRON = 0.85` (calibrated for CRS steel µ_r ≈ 2000).

use nalgebra::UnitQuaternion;

use crate::config::{LinearMotorConfig, MagnetArrangement};
use crate::physics;

/// Empirical correction for finite CRS steel permeability (µ_r ≈ 2 000).
/// Reduces the image-method overestimate by ~15%.
const K_IRON: f64 = 0.85;

/// Builds and manages the magnet source assembly for all four arrangements.
///
/// All four arrangements share the same Z-polarised alternating base. Halbach
/// adds X-polarised interleave magnets. Back-iron arrangements add method-of-
/// images mirror copies scaled by `K_IRON`.
pub struct MagnetArray<'a> {
    config: &'a LinearMotorConfig,
}

impl<'a> MagnetArray<'a> {
    /// Create a new `MagnetArray` bound to the given config.
    pub fn new(config: &'a LinearMotorConfig) -> Self {
        Self { config }
    }

    /// Build a `SourceAssembly` for the configured arrangement at the given
    /// mover position.
    ///
    /// Dispatches to the appropriate builder based on `config.magnet_arrangement`.
    pub fn build_assembly(&self, mover_position_m: f64) -> physics::MagbaSourceAssembly {
        let arr = self.config.magnet_arrangement;
        let mut magnets = self.build_alternating(mover_position_m);
        match arr {
            MagnetArrangement::Alternating => {}
            MagnetArrangement::Halbach => {
                magnets.extend(self.build_halbach_interleave(mover_position_m));
            }
            MagnetArrangement::AlternatingBackIron => {
                let images = self.build_image_magnets(&magnets);
                magnets.extend(images);
            }
            MagnetArrangement::HalbachBackIron => {
                let interleave = self.build_halbach_interleave(mover_position_m);
                magnets.extend(interleave.clone());
                let all_magnets = magnets.clone();
                let images = self.build_image_magnets(&all_magnets);
                magnets.extend(images);
            }
        }
        physics::make_source_assembly(magnets)
    }

    /// Build the base Z-polarised alternating magnet list.
    fn build_alternating(&self, mover_position_m: f64) -> Vec<physics::MagbaCuboidMagnet> {
        let cfg = self.config;
        let z_center = cfg.air_gap_m + cfg.magnet_dims_m[2] / 2.0;
        let y_center = cfg.board_width_m / 2.0;
        let br = cfg.magnet_remanence_t;

        (0..cfg.magnet_count)
            .map(|k| {
                let x = mover_position_m + k as f64 * cfg.magnet_pitch_m;
                let pol_z = br * if k % 2 == 0 { 1.0 } else { -1.0 };
                physics::make_cuboid_magnet(
                    [x, y_center, z_center],
                    UnitQuaternion::identity(),
                    [0.0, 0.0, pol_z],
                    cfg.magnet_dims_m,
                )
            })
            .collect()
    }

    /// Build X-polarised interleave cuboids for the Halbach arrangement.
    ///
    /// One interleave magnet is placed in the gap between each adjacent pair
    /// of main (Z-polarised) magnets. The interleave magnet width equals the
    /// inter-magnet gap; all other dimensions match the main magnet.
    /// Skipped silently if the gap is too small (< 0.1 mm).
    fn build_halbach_interleave(&self, mover_position_m: f64) -> Vec<physics::MagbaCuboidMagnet> {
        let cfg = self.config;
        let interleave_width = cfg.magnet_pitch_m - cfg.magnet_dims_m[0];
        if interleave_width < 1e-4 {
            return Vec::new();
        }

        let z_center = cfg.air_gap_m + cfg.magnet_dims_m[2] / 2.0;
        let y_center = cfg.board_width_m / 2.0;
        let br = cfg.magnet_remanence_t;
        let dim = [
            interleave_width,
            cfg.magnet_dims_m[1],
            cfg.magnet_dims_m[2],
        ];

        (0..cfg.magnet_count - 1)
            .map(|k| {
                let x = mover_position_m + k as f64 * cfg.magnet_pitch_m + cfg.magnet_pitch_m / 2.0;
                let pol_x = br * if k % 2 == 0 { 1.0 } else { -1.0 };
                physics::make_cuboid_magnet(
                    [x, y_center, z_center],
                    UnitQuaternion::identity(),
                    [pol_x, 0.0, 0.0],
                    dim,
                )
            })
            .collect()
    }

    /// Build method-of-images copies for back-iron simulation.
    ///
    /// Each real magnet is mirrored about the steel–magnet interface
    /// (bottom face of back-iron = top face of magnets). Image magnets have
    /// the same polarisation as the originals, scaled by `K_IRON = 0.85`.
    fn build_image_magnets(
        &self,
        real_magnets: &[physics::MagbaCuboidMagnet],
    ) -> Vec<physics::MagbaCuboidMagnet> {
        let cfg = self.config;
        let z_mirror = cfg.air_gap_m + cfg.magnet_dims_m[2];

        real_magnets
            .iter()
            .map(|mag| {
                let orig_pos = mag.position();
                let z_image = 2.0 * z_mirror - orig_pos.z;
                // Image polarisation: same as original, scaled by K_IRON
                let orig_pol = mag.polarization();
                let scaled_pol = orig_pol * K_IRON;
                let dim = mag.dimensions();
                physics::make_cuboid_magnet(
                    [orig_pos.x, orig_pos.y, z_image],
                    UnitQuaternion::identity(),
                    [scaled_pol.x, scaled_pol.y, scaled_pol.z],
                    [dim.x, dim.y, dim.z],
                )
            })
            .collect()
    }

    // ------------------------------------------------------------------
    // Geometry accessors
    // ------------------------------------------------------------------

    /// Z position of main magnet centres above PCB [m].
    pub fn magnet_z_center_m(&self) -> f64 {
        self.config.air_gap_m + self.config.magnet_dims_m[2] / 2.0
    }

    /// X positions of all main magnet centres [m].
    pub fn magnet_x_centers_m(&self, mover_position_m: f64) -> Vec<f64> {
        (0..self.config.magnet_count)
            .map(|k| mover_position_m + k as f64 * self.config.magnet_pitch_m)
            .collect()
    }

    /// Z-polarisation of main magnets, shape `(magnet_count, 3)` [T].
    pub fn polarizations_t(&self) -> Vec<[f64; 3]> {
        let br = self.config.magnet_remanence_t;
        (0..self.config.magnet_count)
            .map(|k| {
                let pol_z = br * if k % 2 == 0 { 1.0 } else { -1.0 };
                [0.0, 0.0, pol_z]
            })
            .collect()
    }

    /// X positions of Halbach interleave magnets [m].
    /// Returns empty vec if not Halbach or HalbachBackIron.
    pub fn interleave_x_centers_m(&self, mover_position_m: f64) -> Vec<f64> {
        let arr = self.config.magnet_arrangement;
        if !matches!(arr, MagnetArrangement::Halbach | MagnetArrangement::HalbachBackIron) {
            return Vec::new();
        }
        let cfg = self.config;
        (0..cfg.magnet_count - 1)
            .map(|k| mover_position_m + k as f64 * cfg.magnet_pitch_m + cfg.magnet_pitch_m / 2.0)
            .collect()
    }

    /// Z position of image magnet centres [m] (back-iron arrangements only).
    pub fn image_z_center_m(&self) -> f64 {
        let cfg = self.config;
        let z_mirror = cfg.air_gap_m + cfg.magnet_dims_m[2];
        let z_original = cfg.air_gap_m + cfg.magnet_dims_m[2] / 2.0;
        2.0 * z_mirror - z_original
    }

    // ------------------------------------------------------------------
    // B-field sampling
    // ------------------------------------------------------------------

    /// Sample B along the board centre-line at the PCB surface.
    ///
    /// - `x_sample`: X positions [m]
    /// - `mover_position_m`: mover position [m]
    /// - `z_observer`: Z of observation plane [m] (default 0 = PCB surface)
    ///
    /// Returns `Vec<[f64; 3]>` of B vectors [T], one per x_sample.
    pub fn bfield_at_pcb_surface(
        &self,
        x_sample: &[f64],
        mover_position_m: f64,
        z_observer: f64,
    ) -> Vec<[f64; 3]> {
        let y_center = self.config.board_width_m / 2.0;
        let observers: Vec<nalgebra::Point3<f64>> = x_sample
            .iter()
            .map(|&x| nalgebra::Point3::new(x, y_center, z_observer))
            .collect();

        let assembly = self.build_assembly(mover_position_m);
        let b_vec = physics::compute_b_batch_parallel(&assembly, &observers);

        b_vec.into_iter().map(|b| [b.x, b.y, b.z]).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::LinearMotorConfig;

    fn test_config() -> LinearMotorConfig {
        LinearMotorConfig::default()
    }

    #[test]
    fn test_alternating_magnet_count() {
        let cfg = test_config();
        let arr = MagnetArray::new(&cfg);
        let assembly = arr.build_assembly(0.0);
        // 10 main magnets, no interleave/images for Alternating
        assert_eq!(assembly.iter().count(), 10);
    }

    #[test]
    fn test_halbach_magnet_count() {
        let cfg = test_config();
        let mut cfg = cfg;
        cfg.magnet_arrangement = MagnetArrangement::Halbach;
        let arr = MagnetArray::new(&cfg);
        let assembly = arr.build_assembly(0.0);
        // 10 main + 9 interleave = 19
        assert_eq!(assembly.iter().count(), 19);
    }

    #[test]
    fn test_back_iron_magnet_count() {
        let cfg = test_config();
        let mut cfg = cfg;
        cfg.magnet_arrangement = MagnetArrangement::AlternatingBackIron;
        let arr = MagnetArray::new(&cfg);
        let assembly = arr.build_assembly(0.0);
        // 10 main + 10 images = 20
        assert_eq!(assembly.iter().count(), 20);
    }

    #[test]
    fn test_halbach_back_iron_magnet_count() {
        let cfg = test_config();
        let mut cfg = cfg;
        cfg.magnet_arrangement = MagnetArrangement::HalbachBackIron;
        let arr = MagnetArray::new(&cfg);
        let assembly = arr.build_assembly(0.0);
        // 10 main + 9 interleave + 19 images = 38
        assert_eq!(assembly.iter().count(), 38);
    }

    #[test]
    fn test_magnet_z_center() {
        let cfg = test_config();
        let arr = MagnetArray::new(&cfg);
        // air_gap + height/2 = 0.0005 + 0.002 = 0.0025
        assert!((arr.magnet_z_center_m() - 0.0025).abs() < 1e-9);
    }

    #[test]
    fn test_magnet_x_centers() {
        let cfg = test_config();
        let arr = MagnetArray::new(&cfg);
        let xs = arr.magnet_x_centers_m(0.0);
        assert_eq!(xs.len(), 10);
        assert!((xs[0] - 0.0).abs() < 1e-9);
        assert!((xs[1] - 0.012).abs() < 1e-9);
        assert!((xs[9] - 0.108).abs() < 1e-9);
    }

    #[test]
    fn test_bfield_at_pcb_surface() {
        let cfg = test_config();
        let arr = MagnetArray::new(&cfg);
        let xs = vec![0.0, 0.006, 0.012, 0.018];
        let b = arr.bfield_at_pcb_surface(&xs, 0.0, 0.0);
        assert_eq!(b.len(), 4);
        // B should be finite and non-trivial
        for bi in &b {
            assert!(bi[0].is_finite());
            assert!(bi[1].is_finite());
            assert!(bi[2].is_finite());
            // |B| should be > 0
            let mag = (bi[0] * bi[0] + bi[1] * bi[1] + bi[2] * bi[2]).sqrt();
            assert!(mag > 1e-6, "B magnitude too small: {}", mag);
        }
        // Bz should alternate sign between magnet centres
        // x=0 is centre of magnet 0 (Z+), x=0.012 is centre of magnet 1 (Z-)
        assert!(b[0][2] > 0.0, "Bz at x=0 should be positive (Z+ pole)");
        assert!(b[1][2] < 0.0, "Bz at x=6mm should be negative (between poles)");
    }

    #[test]
    fn test_image_z_center() {
        let cfg = test_config();
        let arr = MagnetArray::new(&cfg);
        // z_mirror = 0.0005 + 0.004 = 0.0045
        // z_original = 0.0025
        // z_image = 2*0.0045 - 0.0025 = 0.0065
        assert!((arr.image_z_center_m() - 0.0065).abs() < 1e-9);
    }
}
