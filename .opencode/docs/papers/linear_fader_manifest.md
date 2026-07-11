# Linear Motor Fader KiCad Tool: Literature & Resource Manifest

This document serves as the primary literature index and search matrix for the `@pcb-motor-expert` subagent. Use the verified citations, targeted search strings, and hardware standards listed below to inform electromagnetic calculations, haptic rendering algorithms, and KiCad geometric layouts.

---

## 1. Foundational Papers (High Confidence Citations)

### Halbach Array Fundamentals

- **Citation:** K. Halbach, "Design of Permanent Multipole Magnets with Oriented Rare Earth Cobalt Material," _Nuclear Instruments and Methods_, vol. 169, 1980.
- **Application:** Designing the permanent magnet slider array for maximizing flux concentration downward toward the PCB stator.

### Field Oriented Control (FOC) Origin

- **Citation:** F. Blaschke, "The principle of field orientation as applied to the new transvector closed-loop control system for rotating field machines," _Siemens Review_, vol. 39, no. 5, 1972.
- **Application:** Underpinning FOC logic. The adaptation to permanent magnet linear synchronous motors (PMLSM) is a direct coordinate transformation extension of this work.

---

## 2. Topic Areas & Database Search Matrix

When internal framework constraints or exact equations are required, execute automated database lookups (IEEE Xplore, Semantic Scholar, arXiv) using these exact string groupings.

### Linear Vernier PM Motors

- **Key Authors:** K.T. Chau, Chunhua Liu (Hong Kong Polytechnic University), Z.Q. Zhu (University of Sheffield).
- **Search Strings:**
  - `"Vernier permanent magnet linear motor"`
  - `"linear Vernier machine force ripple"`
  - `"flux modulation linear motor"`

### PCB Stator / Coreless Motors

- **Key Entities:** Infinitum Electric (commercial white papers).
- **Search Strings:**
  - `"PCB stator axial flux motor"`
  - `"printed circuit board winding motor"`
  - `"coreless PCB coil Lorentz force actuator"`
  - `"ironless linear motor PCB trace"`

### Lorentz-Type Precision Linear Actuators

- **Key Authors/Labs:** David Trumper (MIT Precision Motion Lab).
- **Search Strings:**
  - `"Lorentz actuator precision positioning"`
  - `"short stroke linear Lorentz force"`
  - `Trumper linear motor precision IEEE`

### Cogging / Force Ripple Minimisation

- **Application:** Eliminating notchiness to optimize smooth haptic textures for motorized audio faders.
- **Search Strings:**
  - `"cogging force reduction permanent magnet linear motor"`
  - `"detent force PMLSM slot pitch optimization"`
  - `"force ripple minimization linear synchronous motor"`

### FOC Applied to Linear PM Motors

- **Search Strings:**
  - `"field oriented control permanent magnet linear synchronous motor"`
  - `"PMLSM FOC position sensorless"`
  - `"linear motor thrust ripple FOC compensation"`

### Haptic Rendering and Motor Faders

- **Databases:** _IEEE Transactions on Haptics_, ICRA proceedings.
- **Search Strings:**
  - `"motor fader haptic feedback audio"`
  - `"impedance control haptic actuator"`
  - `"haptic texture synthesis linear motor"`
  - `"flying fader motor control"`

### PCB Coil Design and Trace Inductance

- **Key References:** Ned Mohan's _Power Electronics_ textbook, Würth Elektronik application notes.
- **Search Strings:**
  - `"planar spiral coil inductance PCB"`
  - `"multilayer PCB coil actuator design"`
  - `"trace inductance calculation PCB motor"`

---

## 3. Engineering Standards & Application Notes

Enforce compliance with these references during automated design verification rule checks:

| Resource ID      | Document Target                                                    | Primary Engineering Use Case                                                                   |
| :--------------- | :----------------------------------------------------------------- | :--------------------------------------------------------------------------------------------- |
| **IPC-2221B**    | Generic Standard on Printed Board Design                           | Historical calculation framework for PCB trace current-carrying capacity.                      |
| **IPC-2152**     | Standard for Determining Current Carrying Capacity in Board Design | Core standard for defining trace width vs. copper weight decisions relative to thermal limits. |
| **JLCPCB-DRU**   | Manufacturer Design Rules (DRU)                                    | Hard boundaries for minimum trace width, trace-to-trace clearance, and minimum via sizing.     |
| **TI-SLVA321**   | Texas Instruments Application Note                                 | Reference architecture for 3-phase BLDC commutation and foundational FOC principles.           |
| **TMC6300-DS**   | Trinamic TMC6300 Datasheet / Eval Notes                            | IC execution constraints for implementing low-voltage FOC at the motor fader physical scale.   |
| **WÜRTH-ANP008** | Würth Elektronik Application Note ANP008                           | Analytical calculations for estimating planar coil inductance profiles.                        |

---

## 4. Architectural Domain Pillars

Maintain all mathematical models, layout scripts, and control code inside this 4-tier structural boundary:

```text
1. MAGNETICS
   ├── Halbach array field distribution
   ├── Flux return / keeper plate effect
   ├── Air gap field decay model
   └── B-H curves for PCB ferrite backing sheets

2. MOTOR PHYSICS
   ├── Lorentz force: F = N · I · L · B
   ├── Vernier step resolution: Δx = |τ_coil - τ_magnet|
   ├── 3-phase commutation geometry
   └── Cogging / force ripple sources

3. PCB COIL DESIGN
   ├── Trace inductance vs. geometry (Neumann formula)
   ├── Spiral coil amp-turns vs. layer count
   ├── Thermal: IPC-2152 current vs. width vs. copper weight
   └── Inter-coil routing (3-phase via placement)

4. CONTROL
   ├── FOC: Clarke + Park transforms
   ├── Position → commutation angle mapping
   ├── Haptic impedance control loop
   └── USB power budgeting / cap bank sizing
```
