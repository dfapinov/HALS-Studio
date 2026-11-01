# Extracting Pressures: Evaluating the 3D Sound Field

The purpose of this script is to take the mathematical description of the 3D sound field (stored in the .h5 coefficients file) and translate it into actionable acoustic measurements. By utilizing wave propagation physics, the script can reconstruct the sound field and extract complex pressure data (magnitude and phase) at any coordinate in 3D space. Whether you need to evaluate the response 1 meter in front of the speaker or 100 meters above it, the underlying mathematical model allows for precise virtual microphone placement.

---

## Core Operations
Before generating measurements, the script must define what it is evaluating and where.

### 1. Field Selection
The **Spherical Harmonic Expansion (SHE)** solver separates the sound field into distinct mathematical components. You can choose which portion to evaluate:

* **Internal Source:** Extracts the purely anechoic data originating from the Device Under Test (DUT), stripped of room reflections.
* **External Source:** Extracts the room field and reflection data (typically used for analysis and inspection of solve quality rather than speaker evaluation).
* **Full:** Evaluates both fields combined. This effectively reconstructs the raw measurement in the room and is mostly used for debugging or verification.

### 2. Frame of Reference
To ensure your virtual measurements align with the physical reality of the speaker, you must define the correct frame of reference.

Export automatically uses optimized Stage 2 origins when available and falls
back to the original origins otherwise.

**Cartesian Offset (XYZ)**
This applies a physical shift to the virtual microphone relative to the measurement origin. For example, if your physical measurement grid was centered on the midrange driver of a 3-way speaker, but you want to perform an arc sweep rotating around the tweeter's acoustic center, you can apply a Z-axis (height) offset to raise the measurement origin accordingly.

**Spherical Orientation**
Spherical harmonic mathematics rely on a specific coordinate system where **Theta = 0** aims "straight up" vertically (the North Pole of the sphere). However, in acoustic measurements, a loudspeaker is typically facing "forwards" toward the equator, not pointing at the ceiling.

* **Zero Theta:** Setting this to 90 degrees rotates the primary measurement axis from the North Pole down to the equator, aligning measurement arcs sweeps with the front of the DUT.
* **Zero Phi:** Functions similarly, allowing you to rotate the frame of reference horizontally around the equator.

---

## Evaluation Modes
The script offers three primary methods for placing virtual microphones to extract data:

### Arc Sweep
This mode allows for automated polar measurements. You can define a radius (distance), an angular range (e.g., +/- 90 degrees), and an increment step (e.g., 10 degrees). The sweep can be performed horizontally, vertically, or both simultaneously to generate a comprehensive polar map.

### CTA-2034 Mode
This fully automates the evaluation of the 70 specific spatial coordinates required by the CTA-2034 standard (commonly known as the **"Spinorama"**). The script automatically extracts the complex pressures at these 70 points, calculates the standard curves (On-Axis, Listening Window, Early Reflections, Sound Power, Predicted In-Room Response (PIR), and Directivity Indices (DI)), and outputs the final standardized response data. To keep the output clean, the original 70 raw measurement files used for the calculation are discarded.

### Custom Coordinate Table
For specific, non-standard evaluations, you can input a custom list of spherical coordinates, and the script will extract the data exactly at those points.

---

## Exporting the Data
The script provides several ways to format and export the results.

### FRD Export
This exports standard Frequency Response Data (FRD) files containing magnitude and phase.

* **Linear Resolution:** Unlike typical FRD files from acoustic software that use logarithmically spaced frequency bins, this script exports the full linear frequency axis data from the original input set. This preserves maximum resolution in the mid and high frequencies and significantly reduces phase wrapping artifacts.
* **Subtract TOF:** You can choose to subtract the phase slope caused by the Time of Flight (TOF) propagation delay. This pure delay removal makes the phase response much easier to analyze visually. (Note: If more than one mic distance is used in the evaluation set, only the shortest TOF delay will be subtracted from all files equally to preserve relative phase differences).

### Impulse Response (IR) WAV
The extracted data can be used to generate impulse response WAV files by means of an Inverse Fast Fourier Transform (IFFT).

* These files always include the full TOF propagation delay, exactly like a physical impulse response measurement.
* They can be imported into acoustic viewing software, crossover simulators, or used directly in a convolution engine to auralize the measured system.
* **Sample Rates:** If the input data for the SHE was 44.1kHz, the IR generation will be 44.1kHz. If the input was 48kHz or higher, the IR export is capped at 48kHz, as the SHE processing is inherently limited to a 24kHz bandwidth.

---

## Microphone Calibration
If you utilized a measurement microphone that requires correction, a calibration file can be applied during extraction to improve the accuracy of the final data. This correction is applied to both the FRD and IR WAV exports.

### Complex Phase Derivation
Standard calibration files only provide magnitude adjustments. However, this script automatically derives the minimum-phase response that directly corresponds to those magnitude adjustments. This ensures that the system corrects not just the amplitude, but the phase of your measurements as well, maintaining magnitude and phase coherence.

* **Add vs. Subtract:** Depending on the source, some files contain the raw microphone response (requiring subtraction), while others contain the inverted correction curve itself (requiring addition). You can toggle the script to "add" or "subtract" to accommodate either format.

* **Fade-Out:** Microphone calibration files rarely cover the entire frequency spectrum. To prevent a sudden "step" or shelf in the measurement data where the calibration file ends, the script automatically applies a fade-out to the correction above and below the limits of the provided file. The bandwidth of this fade can be user-set, but by default is 1-octave.

## FRD Offset

**FRD Offset (dB)** adds a constant level adjustment to the exported FRD magnitude, bringing it onto the calibrated SPL scale. This value is normally supplied by the project file from the calibration performed in the HALS Control measurement app.

It does not scale the exported IR WAV files, and it is not applied to directivity-index curves, which represent level differences.

---

## Inverse Acoustic Origin Transform
In earlier processing stages, the system shifted the mathematical coordinate system to align with the optimal acoustic origin at every individual frequency. This was necessary to solve the Spherical Harmonic Expansion (SHE) with maximum accuracy.

Evaluating that optimized SHE data "as is" would result in a sound field that no longer aligns with the physical reality of the Device Under Test (DUT). The script notes the exact coordinate transforms applied during the earlier solve and performs the exact opposite shift at every frequency during extraction. 

This restores the true behavior of the DUT, ensuring that each frequency radiates from the correct physical location and the time delay and relative phase relationships are perfectly preserved.

> **Note:** There are no user settings for this function. It operates automatically in the background, but it is a critical mathematical step that curious users may wish to understand.

## Optional WAV set normalisation

Enable **Generate WAV impulse files**, then **Normalise WAV set** in Output.
**Set peak / dBFS** defaults to **-6 dBFS**; normalisation is off by default.
The exporter measures the largest absolute sample peak across all generated IRs,
then applies one common gain to every WAV. This preserves level differences
between positions in manual-coordinate sets and combined horizontal/vertical
sweeps. CTA-2034 exports frequency-response data only; WAV export and WAV
normalisation controls are disabled in that mode.

The target is a sample-peak level, not RMS, loudness, or acoustic SPL. A silent
set stays silent. Normalisation changes only WAV amplitudes: FRDs, complex NPZs,
and their calibration settings are unchanged. The shared gain in dB is recorded
in the export log and settings manifest. When disabled, floating-point WAVs
preserve their original scale, including values above 1.0.


### Export preview plots

For arc sweeps and manual coordinates, the Export pane menus offer Export SPL /
phase, Export CSD / wavelet, Export impulse response, directivity plots and CLI output. Analysis plots stay in the Analysis
workspace. Saved layouts containing an Analysis plot in Export restore that
pane to its default Export plot.

Click the Export SPL / phase plot to place a vertical cursor at the nearest
available frequency bin. The toolbar shows that frequency and the selected
microphone's plotted level and phase, including FRD level offset and delay
compensation. The phase readout follows the wrapped/unwrapped display setting.
The cursor remains at the selected frequency as you change microphones.
Use the previous/next buttons below the 3D viewer to move between export points.


Preview speed depends on the visible plots. Point SPL / phase, impulse response
and decay views need only the selected point and its reference, so offset jogging
is faster with those views. Visible CTA-2034 metrics or directivity plots require
the full export point set and take longer to update. Switch away from these plots
when you want the most responsive point-by-point preview. Run Export always
calculates the complete set required for the output files.


In CTA-2034 mode, two panes default to Spinorama overview and Reflection
breakouts. Their menus offer individual CTA metrics. Directivity plots are available in
Arc sweep and Manual coordinates modes.
These graphs use the exact Stage 5 export results, with the FRD level offset
applied to responses but not directivity indices. The bottom-left pane explains the
70 sampling positions and can also be switched to a CTA metric plot; individual-point SPL, phase and decay plots are not
available in this mode. To inspect those directions individually, use Arc sweep,
`hor_vert`, range +/-180 degrees and 10-degree increments, keeping the same
reference direction, distance and offsets. Shared directions and endpoints can
make the sweep point count differ from the CTA set's 70 unique positions.

Directivity plots include horizontal/vertical sonograms, polars and globes.
They use only evaluated export points, normalized to the strongest export point
at each frequency, with a shared reference for both planes. Rotating a full sweep
changes the angular positions without changing the colour scale. Partial sweeps
use the strongest point within their sampled coverage.
A horizontal-only sweep leaves the vertical view empty. Partial sweeps remain
partial: no Analysis sphere is used to fill missing angles. The polar frequency
and display span controls belong to the Export plot.

Export's Plot settings button uses the same directivity controls as Analysis:
Sonogram or Waterfall display, optional on-axis normalization, fractional-octave
energy smoothing, display span, contours and contour spacing. These settings are
saved with the pane and affect the preview plots only. On-axis normalization uses
the export reference direction; peak normalization remains the default.
Analysis and Export share the normalization, energy smoothing and directivity
renderers. Analysis supplies reconstructed sphere cuts; Export supplies evaluated
export points and retains their sampled angular coverage.
Export plot selectors, readouts, Reset axes and Plot settings share Analysis's
single-row header. Use the gear button for span, fit and overlay controls.

The SPL / Phase menu offers Selected Point, Horizontal SPL sweep and Vertical SPL sweep. The sweeps
use the same SPL curve renderer as Analysis, with one absolute-level trace per
available export direction. Export geometry determines the angles and spacing;
missing planes remain empty, and the rear direction is shown only once. Plot
settings share Analysis's smoothing, phase, wrapping, delay, fit and axis controls.
Double-click a legend trace to select it: both its phase curve and cursor readout
follow that selection, in Analysis and Export. Export sweep angles and spacing
remain controlled by Export geometry.
The Direction setting filters the displayed export traces to positive angles,
negative angles or both, always retaining the on-axis point when available.
The shared rear point is labelled +180 or -180 to match the selected side.

<!-- help-group: export -->
