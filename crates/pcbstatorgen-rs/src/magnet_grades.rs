//! NdFeB magnet grade → remanence lookup. Ports `pcbstatorgen/magnet_grades.py`.

use serde::{Deserialize, Serialize};

pub const CUSTOM_GRADE: &str = "Custom";

/// A single NdFeB magnet grade specification.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MagnetGrade {
    pub name: String,
    pub br_min_t: f64,
    pub br_typ_t: f64,
    pub br_max_t: f64,
}

/// Standard grade table (PRODUCT_GOALS.md §3.C).
pub const MAGNET_GRADES: &[(&str, f64, f64, f64)] = &[
    ("N35", 1.17, 1.19, 1.21),
    ("N38", 1.21, 1.23, 1.25),
    ("N42", 1.28, 1.30, 1.32),
    ("N44", 1.32, 1.34, 1.36),
    ("N48", 1.38, 1.40, 1.42),
    ("N52", 1.43, 1.45, 1.48),
];

/// Typical remanence [T] for a grade name (handles suffixes, e.g. "N44H").
pub fn get_remanence(grade: &str) -> Option<f64> {
    let base = extract_base_grade(grade)?;
    MAGNET_GRADES
        .iter()
        .find(|(n, _, _, _)| *n == base)
        .map(|(_, _, typ, _)| *typ)
}

fn extract_base_grade(grade: &str) -> Option<String> {
    let g = grade.trim();
    let lower = g.to_ascii_lowercase();
    if lower.starts_with('n') {
        let digits: String = lower[1..].chars().take_while(|c| c.is_ascii_digit()).collect();
        if !digits.is_empty() {
            return Some(format!("N{}", digits));
        }
    }
    None
}
