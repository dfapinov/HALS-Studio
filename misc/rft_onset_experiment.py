"""Offline RFT-onset research. Reads sibling projects; writes only artifacts/rft_onset.

Run from repository root: .venv/Scripts/python.exe misc/rft_onset_experiment.py
No production settings are changed. Cached solves are keyed by input content.
"""
from pathlib import Path
import os
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[key] = '1'
import sys, json, hashlib, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'process_engine')]
from utils import load_and_parse_npz, translate_coordinates, get_grid_limit, get_kr_limit
from she_solver_core import _solve_one_frequency
from stage3_optimize_she_settings import select_stage3_frequency_indices
from sound_power import degree_power
from scipy.signal import savgol_filter
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter

OUT = ROOT / 'artifacts/rft_onset'
OUT.mkdir(parents=True, exist_ok=True)


def solve(path, order):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    cache = OUT / f'{digest[:16]}_N{order}_v1.npz'
    if cache.exists():
        with np.load(cache) as z:
            return dict(z), digest
    started = time.perf_counter()
    d = load_and_parse_npz(path)
    indices = select_stage3_frequency_indices(d['freqs'], 100, 20000, 48)
    speed = float(d['speed_of_sound_mps'] or 343.)
    grid, _ = get_grid_limit(d['th_arr'], d['ph_arr'])
    def one(i):
        f = d['freqs'][i]
        origin = d['origins_mm'][i]/1000 if d['origins_mm'] is not None else np.zeros(3)
        coords = translate_coordinates(d['r_arr'], d['th_arr'], d['ph_arr'], origin)
        n = min(order, grid, max(2, get_kr_limit(f, coords[0], speed, 2.)))
        p = np.array([d['complex_data'][fn][i] for fn in d['filenames']])
        c, metrics = _solve_one_frequency(f, p, coords, n, 2*np.pi*f/speed,
                                          max_lambda=0., CONDITION_METRICS=True)
        return c, metrics, np.linalg.norm(p)
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(one, indices))
    freq = d['freqs'][indices]
    orders = np.array([r[1]['final_N'] for r in rows])
    coeff = np.zeros((len(rows), 2*(order+1)**2), complex)
    for i, row in enumerate(rows):
        coeff[i, :len(row[0])] = row[0]
    result = dict(freq=freq, orders=orders,
        external=degree_power(freq, coeff, orders, speed, field='External field').sum(axis=1),
        internal=degree_power(freq, coeff, orders, speed).sum(axis=1),
        condition=np.array([r[1]['cond_pre'] for r in rows]),
        residual=np.array([r[1]['residual_norm']/r[2] for r in rows]),
        seconds=np.array(time.perf_counter()-started), points=np.array(len(d['filenames'])))
    np.savez_compressed(cache, **result)
    print(f'{path.parent.parent.name} N{order}: {len(freq)} bins, {result["seconds"]:.1f}s', flush=True)
    return result, digest


def smooth_curve(freq, level, lo=300, hi=12000, width=.5):
    x = np.arange(np.log2(max(lo, freq.min())), np.log2(min(hi, freq.max())), 1/48)
    y = np.interp(x, np.log2(freq), level)
    window = int(round(width*48))//2*2+1
    return x, y, savgol_filter(y, window, 2)


def methods(freq, level, lo=300, hi=12000, width=.5):
    x, raw, y = smooth_curve(freq, level, lo, hi, width)
    # Continuous two-line fit on log2 frequency. Robust IRLS limits isolated peaks.
    fits = []
    for j in range(36, len(x)-48):
        A = np.column_stack([np.ones(len(x)), x-x[j], np.maximum(x-x[j], 0)])
        weights = np.ones(len(x))
        for _ in range(5):
            b = np.linalg.lstsq(A*weights[:, None]**.5, y*weights**.5, rcond=None)[0]
            res = y-A@b
            scale = max(.5, 1.4826*np.median(abs(res-np.median(res))))
            weights = np.minimum(1., 1.5*scale/np.maximum(abs(res), 1e-12))
        if b[1] < -1e-6 and b[2] > 1e-6:
            fits.append((np.mean(np.minimum(res**2, 3*scale*abs(res))), j, b, A@b))
    best = min(fits, key=lambda z:z[0]) if fits else None
    # Normalized chord-distance comparator, not a full Kneedle implementation.
    chord = np.linspace(y[0], y[-1], len(y))-y
    chord[:36] = chord[-48:] = -np.inf
    j = int(np.argmax(chord))
    result = {'chord': float(2**x[j]) if chord[j]>1e-6 else None,
              'hinge': float(2**x[best[1]]) if best else None,
              'sustained': None, 'local_fit': None}
    # Earliest half-octave sustained flattening after a full octave of descent.
    # Relative slope (25% of previous descent), with a 2 dB/oct tolerance;
    # preceding descent >= 4 dB/oct. No absolute modal level threshold.
    slopes = np.gradient(y, x)
    for j in range(48, len(x)-48):
        before = np.polyfit(x[j-48:j], y[j-48:j], 1)[0]
        after = np.polyfit(x[j:j+48], y[j:j+48], 1)[0]
        local = slopes[j:j+24]
        tolerance = max(2., .25*abs(before))
        if before < -4 and abs(after) <= tolerance and np.mean(abs(local)<=tolerance) >= .8:
            result['sustained'] = float(2**x[j]); break
    # Less ripple-sensitive variant: fit each half of the following octave.
    for j in range(48, len(x)-48):
        before = np.polyfit(x[j-48:j], y[j-48:j], 1)[0]
        after = np.polyfit(x[j:j+48], y[j:j+48], 1)[0]
        halves = [np.polyfit(x[a:b], y[a:b], 1)[0]
                  for a,b in ((j,j+24),(j+24,j+48))]
        tolerance = max(2., .3*abs(before))
        if before < -5 and abs(after) < tolerance and max(abs(np.array(halves))) < 1.5*tolerance:
            result['local_fit'] = float(2**x[j]); break
    return result, (x, raw, y, best, slopes)


def main():
    records = []
    for path in sorted(ROOT.parent.glob('*/outputs/*complex_data.npz')):
        name = path.parent.parent.name
        curves = {}
        for order in (6, 4, 8):
            curves[order], digest = solve(path, order)
        projects = list(path.parent.parent.glob('*project.json'))
        project = json.loads(projects[0].read_text()) if projects else {}
        parsed = load_and_parse_npz(path)
        settings = parsed['stage1_settings']
        rft = project.get('stage3_vars', {}).get('fdw_rft_ms', project.get('stage1_vars', {}).get('fdw_rft_ms'))
        resolution = settings.get('fdw_oct_res', project.get('stage1_vars', {}).get('fdw_oct_res'))
        from rft_range import transition_frequency_hz
        reference = transition_frequency_hz(rft, resolution) if rft and resolution else None
        records.append(dict(name=name, path=str(path), digest=digest, curves=curves,
                            reference=reference, settings=settings, project_rft_ms=rft,
                            resolution=resolution, usable_upper=project.get('stage3_vars',{}).get('freq_end_hz')))
    summary=[]
    fig, axes = plt.subplots(4, 2, figsize=(16, 17), layout='constrained')
    for rec, ax in zip(records, axes.flat):
        d=rec['curves'][6]; f=d['freq']; y=10*np.log10(d['external'])
        found, detail=methods(f,y)
        x,raw,sm,best,slopes=detail
        ax.semilogx(f,y,color='#147d92',lw=1,alpha=.65,label='N6 total external')
        ax.semilogx(2**x,sm,color='#064f63',lw=2,label='1/2-oct smoothing')
        if best is not None:
            ax.plot(2**x,best[3],color='#a94442',alpha=.6,lw=1)
        for key,color in [('chord','#d98a00'),('hinge','#ba4242'),('local_fit','#318844')]:
            if found[key]: ax.axvline(found[key],color=color,ls='--',label=f'{key}: {found[key]:.0f} Hz')
        if rec['reference']: ax.axvline(rec['reference'],color='gray',ls=':',label=f'RFT setting: {rec["reference"]:.0f} Hz')
        ax.set(title=rec['name'],xlim=(100,20000),xlabel='Frequency (Hz)',ylabel='External modal power (relative dB)')
        ax.set_xticks([100,300,1000,3000,10000,20000]); ax.xaxis.set_major_formatter(ScalarFormatter())
        ax.grid(alpha=.25); ax.legend(fontsize=8,loc='best')
        sensitivities=[]
        for order in (4,6,8):
            dd=rec['curves'][order]
            for lo,hi in [(200,8000),(300,12000),(500,16000)]:
                for width in (.3333,.5,.75):
                    estimates,_=methods(dd['freq'],10*np.log10(dd['external']),lo,hi,width)
                    sensitivities.append(dict(order=order,lo=lo,hi=hi,width=width,**estimates))
        normalized,_=methods(f,10*np.log10(d['external']/d['internal']))
        summary.append({k:v for k,v in rec.items() if k!='curves'} | dict(methods=found,sensitivity=sensitivities,
            normalized_methods=normalized,
            seconds_N6=float(d['seconds']),samples=len(f),points=int(d['points']),
            hinge_slopes=[float(best[2][1]),float(best[2][1]+best[2][2])] if best else None))
        diagnostic(rec, found)
    fig.suptitle('External-field total modal power: N <= 6, nearest 1/48-octave bins\nShape detectors fitted over 300 Hz–12 kHz; RFT settings are context, not ground truth',fontsize=16)
    fig.savefig(OUT/'external_power_comparison.png',dpi=150)
    plt.close(fig)
    (OUT/'results.json').write_text(json.dumps(summary,indent=2))
    write_report(summary)
    print(json.dumps([{k:r[k] for k in ('name','methods','hinge_slopes','seconds_N6')} for r in summary],indent=2))


def diagnostic(rec,found):
    fig, axes=plt.subplots(3,1,figsize=(12,10),sharex=True,layout='constrained')
    for n,color in [(4,'#b08b35'),(6,'#147d92'),(8,'#8c61b0')]:
        d=rec['curves'][n]; f=d['freq']
        axes[0].semilogx(f,10*np.log10(d['external']),color=color,label=f'N <= {n}')
        axes[1].semilogx(f,10*np.log10(d['external']/d['internal']),color=color,label=f'N <= {n}')
        axes[2].semilogx(f,100*d['residual'],color=color,label=f'N <= {n}')
    axes[0].set_title(rec['name']+' — order sensitivity and source-normalized check')
    axes[0].set_ylabel('External modal power (dB)')
    axes[1].set_ylabel('External / internal (dB)')
    axes[2].set_ylabel('Relative fit residual (%)'); axes[2].set_xlabel('Frequency (Hz)')
    for ax in axes:
        for key,color in [('chord','#d98a00'),('hinge','#ba4242'),('local_fit','#318844')]:
            if found[key]: ax.axvline(found[key],color=color,ls='--',alpha=.8,
                                     label=f'{key}: {found[key]:.0f} Hz' if ax is axes[0] else None)
        ax.set_xlim(100,20000); ax.grid(alpha=.25); ax.legend(fontsize=9)
    axes[2].set_xticks([100,300,1000,3000,10000,20000]); axes[2].xaxis.set_major_formatter(ScalarFormatter())
    fig.savefig(OUT/(rec['name']+'_diagnostics.png'),dpi=130); plt.close(fig)


def write_report(summary):
    import html, base64
    assessments = {
        'ELAC-Debut2.0': 'Transition spans roughly 1.7–3.3 kHz. The early external knee is not the settled plateau: normalized power bends around 3.0 kHz. A provisional conservative Stage 3 lower edge is about 3.3 kHz.',
        'Genelec-8010a-04': 'Clearest case. Knee around 2.5–2.7 kHz, broadly supported by normalized power and N4/N8. Provisional lower edge about 2.7–3.0 kHz.',
        'Genelec-8010a-04 - Copy': 'Same practical conclusion as Genelec original; this is a related copy, not independent validation.',
        'PTT40M04NAC04-SN002117-S05': 'Local shoulder around 1.4–1.8 kHz; decline resumes around 3 kHz. The global 6 kHz minimum is not a sustained plateau. Tentative local candidate only; configured usable upper limit is 2 kHz, leaving insufficient in-band plateau for a strong automatic decision.',
        'PTT40M04NAC04-SN002117-S05 - Copy': 'Local shoulder around 1.4–1.8 kHz, but later descent and a deep 6 kHz minimum remain. Tentative candidate only. Related measurement/processing variant, not independent validation.',
        'PTT_woofer': 'Absolute power does not establish a sustained plateau. Normalized local detector suggests about 1.2 kHz, but absolute/normalized evidence disagrees. No confident automatic onset.',
        'Tweeter': 'Reject automatic onset from this solve. No global falling-to-flat knee; a local detector can be fooled near 1.1 kHz. Relative fit residual approaches 100% at HF and external/internal is positive. Current NPZ has no saved optimized origins; cause of poor fit is not diagnosed here.',
        'Woofer': 'Global methods pick a 5.1–5.5 kHz valley followed by strong rising power, not a plateau. Beyond configured 3 kHz usable upper limit. No confident automatic onset.',
    }
    fmt=lambda value: '—' if value is None else f'{value/1000:.2f}'
    lines=['# External-field plateau / RFT-onset experiment', '',
        'Research results, 11 October 2026. These are candidate frequency boundaries, not independently verified reflection-arrival times. Production behavior and source projects were not modified.', '',
        '## Findings', '',
        'The proposed presolve is fast and useful, but a single global knee is not robust across these sets. Genelec supports a clear estimate; ELAC has a broad transition; PTT shows multiple shoulders; the woofer has a valley; the current tweeter solve is unsuitable for this diagnostic.', '',
        '| Dataset | Chord knee kHz | Two-line knee kHz | Local plateau kHz |',
        '|---|---:|---:|---:|']
    for r in summary:
        m=r['methods']; lines.append(f'| {r["name"]} | {fmt(m["chord"])} | {fmt(m["hinge"])} | {fmt(m["local_fit"])} |')
    lines += ['', '![All external-power curves](external_power_comparison.png)', '', '## Reproducible setup', '',
        '- Eight sibling project folders with processed Stage 1 NPZ files; copied/related sets are not eight independent environments. Raw-only folders and historical repository archives were not reprocessed.',
        '- 100 Hz–20 kHz, nearest distinct bins to 1/48-octave targets: 332 actual frequency samples per set. This sampling does not increase the original windowing resolution.',
        '- Max N=6, plus N=4 and N=8 checks. Existing grid and kr limits apply; N is not forced to 6 at LF. Optimized origins are used where saved, zero translation otherwise. Saved sound speed is used, with 343 m/s fallback.',
        '- Existing unregularized solver (max_lambda=0), matching the initial Stage 3 order sweep. Same degree_power routine as the UI: sum |D_nm|²/k², then 10 log10. External modal power is not net radiated sound power or calibrated SPL.',
        '- N6 elapsed load/solve/aggregation time: '+f'{min(r["seconds_N6"] for r in summary):.1f}–{max(r["seconds_N6"] for r in summary):.1f} s with six worker threads, excluding the prior file-hash pass, cache save, detector sweep and plotting. Warm filesystem cache may affect these timings.',
        '- Baseline detector band 300 Hz–12 kHz, interpolated onto a uniform log2-frequency grid, quadratic Savitzky–Golay smoothing over roughly 1/2 octave. Broad exploratory band intentionally exposes out-of-band false detections; it is not the production usable band.',
        '- Sensitivity sweep: N4/N6/N8 × bands 200–8000, 300–12000, 500–16000 Hz × smoothing widths 1/3, 1/2, 3/4 octave = 27 configurations per dataset.',
        '- Gray RFT lines use project RFT and recorded FDW resolution where available, otherwise project resolution. Legacy provenance is incomplete; these lines are context, not labels or ground truth. RFT is not supplied to any detector.', '',
        '## Methods tried', '',
        '1. **Chord distance:** greatest distance below the endpoint chord in dB versus log2(f). Simple geometric comparator, not the full Kneedle algorithm. Sensitive to endpoints, response notches and multiple knees.',
        '2. **Robust continuous two-line regression:** scan breakpoints with at least 3/4 octave before and one octave after; five Huber-style reweighting iterations. Select the smallest robust error among slope-increase fits. This deliberately reports raw candidates, including valleys: a positive post-knee slope must not be accepted as a plateau.',
        '3. **Strict sustained derivative:** prior octave falls faster than 4 dB/oct; next octave slope lies within max(2 dB/oct, 25% of previous slope magnitude); at least 80% of the next half-octave derivatives must lie within that tolerance. No baseline set passed: local ripple makes this too strict.',
        '4. **Local regression plateau:** prior octave falls faster than 5 dB/oct; next octave slope is within max(2 dB/oct, 30% of prior magnitude); both following half-octave slopes stay within 1.5 times that tolerance. Earliest passing frequency is reported. More tolerant of ripple, but can accept temporary shoulders or poor solves.',
        'All thresholds concern slopes or shape, never an absolute SPL/modal-power level. These exploratory constants were not independently calibrated. On an ideal 2 kHz knee, chord/two-line/strict methods return 1.989 kHz and the permissive local method returns 1.722 kHz: the local method can lead the actual transition.', '',
        'Smoothing uses [SciPy Savitzky–Golay filtering](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html). The [Kneedle paper](https://raghavan.usc.edu/papers/kneedle-simplex11.pdf) provides background for normalized geometric knee detection; no claim is made that the chord comparator implements that full algorithm.', '',
        '## Suggested Stage 3 design', '',
        'Use this as an automatic frequency-band suggestion with confidence and an explicit unresolved result, rather than convert a knee into an assumed physical RFT in milliseconds. Search within the source’s usable band, generate local falling-to-flatter breakpoints, and require roughly an octave of supporting data. Check the external/internal curve to expose source-response effects, require persistence across modest band/smoothing changes, and confirm with a nearby order. Reject rising valleys, order-transition artifacts, poor-fit data and insufficient usable bandwidth. Existing Stage 3 separation/order checks must still run.', '',
        'For these data I would provisionally use about 2.7–3.0 kHz for Genelec and about 3.3 kHz for ELAC. Keep the PTT S05 shoulder as a low-confidence 1.4–1.8 kHz candidate, and abstain for the other sets. These are analyst judgments, not a validated automatic classifier.', '',
        'Before replacing manual entry, validate against raw-IR reflection evidence or known reflection times and reprocess the same measurements with several FDW widths: a reflection-related onset should respond coherently to window length. Current Stage 1 still uses RFT in its taper schedule, so this experiment only addresses Stage 3 band selection, not removal of RFT from the entire pipeline.', '',
        '## Per-dataset evidence and sensitivity', '']
    for r in summary:
        lines += [f'### {r["name"]}', '', assessments[r['name']], '',
                  f'External/internal candidates (chord, two-line, local), kHz: {fmt(r["normalized_methods"]["chord"])}, {fmt(r["normalized_methods"]["hinge"])}, {fmt(r["normalized_methods"]["local_fit"])}.', '',
                  '| Method | Valid / 27 | 10th–90th percentile, kHz |', '|---|---:|---:|']
        for key in ('chord','hinge','sustained','local_fit'):
            values=[v[key] for v in r['sensitivity'] if v[key] is not None]
            interval='—' if not values else '–'.join(f'{v/1000:.2f}' for v in np.percentile(values,[10,90]))
            lines.append(f'| {key} | {len(values)} | {interval} |')
        lines += ['', 'These are parameter-sensitivity ranges, not statistical confidence intervals.', '',
                  f'![Order, normalized-power and residual checks]({r["name"]}_diagnostics.png)', '',
                  f'Input: `{r["path"]}`; SHA-256 `{r["digest"]}`. Configured usable upper limit: {r["usable_upper"]} Hz.', '']
    lines += ['## Artifacts and validation', '',
              '`results.json` records metadata, candidates and all sensitivity runs. Content-keyed NPZ caches contain frequency, external/internal linear power, actual order, raw matrix condition and relative pressure-fit residual. Re-run from the repository root with `.venv\\Scripts\\python.exe misc/rft_onset_experiment.py`.', '',
              'Synthetic known-knee, flat-line and straight-decline checks were run, including a +37 dB offset to verify level invariance. Flat and straight-decline inputs return no candidate after a numerical-tolerance guard. The actual curves and diagnostic figures were visually inspected. This is an exploratory comparison, not a measured detection-accuracy benchmark.']
    (OUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    # Standalone gallery: embeds every PNG so the HTML can be moved or shared.
    cards=[]
    for r in summary:
        data=base64.b64encode((OUT/(r['name']+'_diagnostics.png')).read_bytes()).decode()
        cards.append(f'<details><summary>{html.escape(r["name"])}</summary><p>{html.escape(assessments[r["name"]])}</p><img src="data:image/png;base64,{data}"></details>')
    overview=base64.b64encode((OUT/'external_power_comparison.png').read_bytes()).decode()
    content='<html><meta charset="utf-8"><title>RFT onset experiment</title><style>body{font:16px system-ui;max-width:1250px;margin:40px auto;padding:0 20px;background:#f5f7fa;color:#182c40}img{width:100%}details{background:white;padding:20px;margin:12px 0;border-radius:10px}summary{font-weight:650;cursor:pointer}pre{white-space:pre-wrap;background:white;padding:24px;line-height:1.5}</style><h1>External-field plateau / RFT onset</h1><p>N ≤ 6 · 1/48-octave samples · eight processed sets · 11 October 2026</p><p>Clear candidate for Genelec; broad transition for ELAC; ambiguous shoulders or unsuitable evidence elsewhere. Expand a dataset for order and fit-quality checks.</p><img src="data:image/png;base64,'+overview+'">'+''.join(cards)+'<details><summary>Full methods, findings and sensitivity results</summary><pre>'+html.escape('\n'.join(line for line in lines if not line.startswith('![')))+'</pre></details></html>'
    (OUT/'report.html').write_text(content,encoding='utf-8')


if __name__=='__main__': main()
