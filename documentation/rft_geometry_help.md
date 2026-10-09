# Setting Reflection-Free Time from Measurement Geometry

**Reflection-Free Time (RFT)** is the interval between the direct sound arriving
at the microphone and the earliest reflected sound reaching it. It is measured
in milliseconds and describes the clean part of the impulse response before
boundary reflections begin.

Set RFT in **HALS Control** when creating the measurement set. The value is
saved in the project for later use in HALS Studio. RFT is a property of the
measurement geometry; changing a processing resolution does not change the
physical reflection-free time.

## Choosing the Value for a Measurement Set

1. Identify possible reflecting surfaces: the floor, ceiling, nearby walls,
   and other large surfaces near the speaker or microphone.
2. Calculate the direct and reflected path lengths for each relevant boundary.
   The shortest reflected path determines the first reflection at that position.
3. Check the geometry across the microphone positions used by the scan.
   If one RFT value covers the whole set, use the shortest reflection-free time
   across those positions.
4. Enter that value in the HALS Control RFT setting and save the project.
   Recalculate it if the speaker, scan geometry, or surrounding boundaries change.

The nearest surface alone does not determine RFT: both the speaker and
microphone positions affect the extra distance travelled by the reflection.

## From Measurement Geometry to RFT

RFT is the difference between the shortest reflected path and the direct path,
divided by the speed of sound:

$$\mathrm{RFT}_{\mathrm{ms}} = 1000\, \frac{L_{\mathrm{reflected}}-L_{\mathrm{direct}}}{c}$$

For a speaker and microphone at the same height above a flat reflecting
boundary:

$$\mathrm{RFT}_{\mathrm{ms}} = 1000\, \frac{\sqrt{D^2+4D_r^2}-D}{c}$$

Here, $D$ is the speaker-to-microphone distance, $D_r$ is their distance from
that boundary, and $c$ is the speed of sound (approximately 343 m/s). Distances
are in metres. The earliest reflection from any boundary determines the RFT.
HALS Control provides the calculator and saves the RFT value in the project.

## Geometry Example

Suppose the speaker and microphone are both 1 metre above the floor and are
0.5 metres apart horizontally:

- Direct path: 0.5 m.
- Floor-reflected path: about 2.062 m.
- Extra reflected distance: about 1.562 m.
- RFT at 343 m/s: about **4.55 ms**.

This is the floor-limited value at that microphone position. Check the ceiling,
walls, and other scan positions before using it for the whole measurement set;
an earlier reflection gives a shorter RFT.

## How RFT Affects the Stage 3 Test Range

In HALS Studio, RFT identifies the frequency range in which the FDW windows fit
before the first reflection. It helps select the Stage 3 test range.

For the FDW resolution $1/x$ used when Stage 1 ran, the required number of cycles
is:

$$m = \frac{1}{2^{1/x}-1}$$

The transition frequency occurs where the FDW duration $m/f$ equals RFT:

$$f_{\mathrm{RFT}} = \frac{m}{\mathrm{RFT}_{\mathrm{ms}}/1000}$$

Stage 3 reads $x$ from the Stage 1 NPZ and rounds this frequency up to the next
1,000 Hz to populate **Lower Test Range**. Its own **Octave Resolution** control
sets the test frequency spacing and does not enter this boundary calculation.

| RFT | Stage 1 FDW resolution | Transition frequency (approx.) | Default lower test range |
| --- | --- | --- | --- |
| 5 ms | 1/3 octave | 770 Hz | 1,000 Hz |
| 5 ms | 1/12 octave | 3,363 Hz | 4,000 Hz |
| 10 ms | 1/12 octave | 1,682 Hz | 2,000 Hz |

A longer RFT allows the reflection-free test range to extend to lower
frequencies. Finer FDW resolution requires more cycles and raises its lower
boundary. You can edit the lower test limit manually or use **Set from RFT** to
restore the calculated default. If the source's upper test limit is below the
boundary, Stage 3 uses a two-octave test band: the lower limit becomes one quarter of the upper limit.
For example, an upper limit of 2 kHz gives a lower limit of 500 Hz.
