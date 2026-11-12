"""Standalone Tkinter raw-IR review app. Run directly, or use ir_scan.bat."""
import os
for _key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_key] = '1'

import argparse
import csv
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import NullFormatter
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from ir_capture_quality import FREQUENCIES, robust_predict, scan_directory, rename_reviewed
from capture_diagnostics import REPORT_COLUMNS, read_audio, capture_path


HELP = """Capture evidence and categories

When debug captures and a single compatible shared reference are present, the scanner reads the declared loopback/microphone channels and timing. It builds a median loopback from up to 31 spread-out captures (at least nine), checks majority agreement, aligns constant latency and gain, and checks 10 ms residual blocks at 24 kHz plus full-rate amplitude envelopes. Digital clipping and silent channels are checked at the original sample rate. Electrical/capture means the fault is visible electrically; it does not prove an audio driver fault.

Microphone pre-silence (after the first 50 ms of settling) and the final 200 ms tail are compared with robust session and spatial-neighbour baselines. Full IRs are matched to their actual crop; far-prefix energy is compared locally. These checks produce review findings, since background noise, room decay and legitimate distortion need interpretation. The first 50 ms level is reported for inspection only.

The main plots show the full captures and full IR alongside the LF response and measurement locations. The category and coverage fields explain which evidence was available. Missing optional files retain the original IR-only checks. Multiple references without an explicit capture association are not guessed. CSV exports include all metrics and issue details. Suspect/Okay correspond to the existing repeat/pass report codes. The LF score and LF band refer only to the spatial check; capture issue scores are separate in the evidence.

How the spatial scan works

1. Read coordinates from each *_r..._ph..._z..._ir.wav filename and the first 0.35 seconds of its IR. Report unreadable, short, silent, constant or non-finite leading data separately.
2. Downsample to 4 kHz and calculate 37 complex response samples from 40 to 320 Hz. Use a 200 ms taper after the detected arrival, preserving timing between recordings.
3. Predict each response from its nearest 12 and 24 measurement positions. A small local spatial fit reduces the influence of inconsistent neighbours.
4. Flag a repeat candidate when BOTH neighbourhoods exceed the discrepancy threshold in the SAME frequency band. 'Review' means only one neighbourhood exceeds it. The threshold is the larger of 10% of local pressure and eight times the local prediction-error scale, adjusted for prediction uncertainty.

Score 1 is the repeat threshold; a score is not a probability of corruption. For 'review' rows the maximum single-neighbourhood score can exceed 1 even when the displayed consensus score does not.

The spatial check needs at least 25 unique valid positions and covers 40–320 Hz. It does not run SHE or need driver locations. Optional capture checks extend coverage as described above. Genuine localized behaviour, wrong coordinates, gain or timing changes can also trigger flags. Shared errors across the whole scan can pass.

Inspect and re-measure suspects when possible. Mark only files you want excluded, then confirm Rename marked. This adds .blacklisted after .wav, preserving the original bytes. Restore selected removes that suffix, unless a replacement capture already occupies the original name.

After renaming, re-run Stage 1 and subsequent stages to rebuild existing HALS data. Renaming does not alter an already-created NPZ or coefficient file. Alternatively, Export blacklist lists excluded original names for the Stage 2 blacklist setting.
"""


def draw_capture_evidence(axes, folder, row):
    for ax, title in zip(axes, ('Electrical loopback', 'Microphone capture', 'Full IR before cropping')):
        ax.set(title=title, xlabel='Time (s)', ylabel='Amplitude')
    try:
        fs, raw = read_audio(capture_path(folder, row))
        if raw.ndim != 2 or raw.shape[1] != 2:
            raise ValueError('Expected a two-channel capture')
        # Min/max envelopes preserve short glitches when drawing long captures.
        for channel in range(2):
            plot_envelope(axes[channel], raw[:, channel], fs)
        event = row.get('metrics', {}).get('loopback_event_s')
        if event is not None:
            axes[0].axvline(event, color='tab:red', ls=':', label='Largest residual')
            axes[0].legend()
    except (OSError, ValueError, EOFError) as error:
        axes[0].text(.02, .8, str(error), transform=axes[0].transAxes)
    try:
        name = row['filename'].replace('_ir.wav', '_ir_dist.wav')
        fs, full = read_audio(folder/'Distortion'/name)
        plot_envelope(axes[2], full, fs)
        origin = row.get('metrics', {}).get('full_ir_origin_s')
        if origin is not None:
            axes[2].axvline(origin, color='tab:red', ls=':', label='Verified crop origin')
            axes[2].legend()
    except (OSError, ValueError, EOFError) as error:
        axes[2].text(.02, .8, str(error), transform=axes[2].transAxes)


def draw_inspection(figure, folder, row, rows):
    """Render full capture evidence, LF predictions and measurement locations."""
    figure.clear()
    grid = figure.add_gridspec(6, 2, width_ratios=(1.35, 1))
    loopback = figure.add_subplot(grid[0:2, 0])
    microphone = figure.add_subplot(grid[2:4, 0], sharex=loopback)
    full_ir = figure.add_subplot(grid[4:6, 0])
    spectrum = figure.add_subplot(grid[0:3, 1])
    spatial = figure.add_subplot(grid[3:6, 1])
    axes = (loopback, microphone, full_ir, spectrum, spatial)
    draw_capture_evidence(axes[:3], folder, row)
    spectrum.set(title='LF response and local predictions', xlabel='Frequency (Hz)', ylabel='Magnitude (dB, common reference)')
    spatial.set(title='Measurement locations', xlabel='Azimuth (degrees)', ylabel='Height (mm)')
    lookup = {r['filename']: r for r in rows}
    neighbours = [lookup[name] for name in row.get('neighbours', [])]
    if 'response' in row:
        level = lambda response: 20*np.log10(np.maximum(abs(response), 1e-30))
        for neighbour in neighbours:
            spectrum.semilogx(FREQUENCIES, level(neighbour['response']), color='0.75', alpha=.5, lw=.6)
        spectrum.semilogx(FREQUENCIES, level(row['response']), color='tab:red', label='Selected', lw=1.6)
        if neighbours:
            local = [row]+neighbours
            xyz = np.array([r['xyz'] for r in local])
            response = np.array([r['response'] for r in local])
            for count, color in ((12, 'tab:blue'), (24, 'tab:green')):
                # Fit separately in each octave, exactly as the detector does.
                prediction = np.empty(len(FREQUENCIES), complex)
                for low, high in ((40, 80), (80, 160), (160, 321)):
                    band = (FREQUENCIES >= low-1e-8) & (FREQUENCIES < high-1e-8)
                    prediction[band] = robust_predict(xyz, response[:, band], 0, np.arange(1, count+1))[0]
                spectrum.semilogx(FREQUENCIES, level(prediction), color=color, ls='--', label=f'{count}-neighbour prediction')
        spectrum.legend(fontsize=8)
        spectrum.set_xticks([40, 60, 80, 120, 160, 240, 320], labels=['40','60','80','120','160','240','320'])
        spectrum.xaxis.set_minor_formatter(NullFormatter())
    located = [r for r in rows if 'cylindrical' in r]
    if located:
        spatial.scatter([r['cylindrical'][1] for r in located], [r['cylindrical'][2] for r in located], s=7, c='0.8')
    if neighbours:
        spatial.scatter([r['cylindrical'][1] for r in neighbours], [r['cylindrical'][2] for r in neighbours], s=16, c='tab:blue', label='Neighbours')
    if 'cylindrical' in row:
        spatial.scatter([row['cylindrical'][1]], [row['cylindrical'][2]], s=65, c='tab:red', marker='x', label='Selected')
        spatial.legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=.2)
    return axes


def plot_envelope(ax, signal, fs):
    if signal.ndim != 1:
        raise ValueError('Expected mono signal')
    size = max(1, len(signal)//2500)
    count = len(signal)//size
    blocks = signal[:count*size].reshape(count, size)
    time = (np.arange(count)+.5)*size/fs
    ax.fill_between(time, blocks.min(axis=1), blocks.max(axis=1), alpha=.7)


class ReviewApp:
    def __init__(self, root, folder=''):
        self.root = root
        self.root.title('HALS IR Capture Review')
        self.root.geometry('1400x1000')
        self.root.minsize(1100, 800)
        self.directory = tk.StringVar(value=str(folder))
        self.status = tk.StringVar(value='Choose the folder containing the raw IR WAVs, then Scan.')
        self.filter = tk.StringVar(value='Needs review')
        self.rows = []
        self.folder = None
        self.busy = False
        self.cancel = threading.Event()
        self.events = queue.Queue()
        self.controls = []
        outer = ttk.Frame(root, padding=10)
        outer.pack(fill='both', expand=True)
        top = ttk.Frame(outer)
        top.pack(fill='x')
        ttk.Label(top, text='IR directory:').pack(side='left')
        self.entry = ttk.Entry(top, textvariable=self.directory)
        self.entry.pack(side='left', fill='x', expand=True, padx=8)
        self.controls.append(self.entry)
        self.button(top, 'Browse…', self.browse)
        self.button(top, 'Scan', self.scan)
        self.cancel_button = ttk.Button(top, text='Cancel', command=self.cancel.set, state='disabled')
        self.cancel_button.pack(side='left', padx=3)
        ttk.Button(top, text='How it works', command=self.help).pack(side='left', padx=3)
        ttk.Label(outer, text='Inspect suspects, mark your choices, then confirm renaming. No file is changed by scanning.').pack(anchor='w', pady=(8, 3))
        tools = ttk.Frame(outer)
        tools.pack(fill='x', pady=4)
        box = ttk.Combobox(tools, textvariable=self.filter, values=('Needs review', 'All recordings', 'Excluded'), state='readonly', width=18)
        box.pack(side='left', padx=(0, 8))
        box.bind('<<ComboboxSelected>>', lambda _: self.populate())
        self.button(tools, 'Mark selected', lambda: self.mark(True))
        self.button(tools, 'Unmark selected', lambda: self.mark(False))
        self.rename_button = self.button(tools, 'Rename marked (0)', self.rename)
        self.button(tools, 'Restore selected', self.restore)
        self.button(tools, 'Export report', self.export_report)
        self.button(tools, 'Export blacklist', self.export_blacklist)
        table = ttk.Frame(outer)
        table.pack(fill='x')
        columns = ('marked', 'status', 'category', 'score', 'band', 'filename')
        self.tree = ttk.Treeview(table, columns=columns, show='headings', selectmode='extended', height=6)
        for column, title, width in zip(columns, ('Exclude?', 'Finding', 'Issue description', 'LF score', 'LF band (Hz)', 'Filename'), (65, 100, 480, 65, 85, 400)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, minwidth=width if column != 'filename' else 200, stretch=column=='filename')
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(outer, orient='horizontal', command=self.tree.xview)
        horizontal.pack(fill='x')
        self.tree.configure(xscrollcommand=horizontal.set)
        self.tree.tag_configure('repeat', foreground='#9b3200')
        self.tree.tag_configure('technical', foreground='#a00000')
        self.tree.bind('<<TreeviewSelect>>', self.inspect)
        self.tree.bind('<Button-1>', self.toggle_mark)
        self.details = tk.StringVar(value='Select a recording to inspect its full capture, full IR, LF response and measurement locations.')
        ttk.Label(outer, textvariable=self.details, wraplength=1200, justify='left').pack(fill='x', pady=5)
        self.figure = Figure(figsize=(12, 6), dpi=100, layout='constrained')
        self.canvas = FigureCanvasTkAgg(self.figure, master=outer)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        NavigationToolbar2Tk(self.canvas, outer, pack_toolbar=False).pack(fill='x')
        self.progress = ttk.Progressbar(outer, mode='determinate')
        self.progress.pack(fill='x', pady=3)
        ttk.Label(outer, textvariable=self.status).pack(anchor='w')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(100, self.poll)

    def button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        button.pack(side='left', padx=3)
        self.controls.append(button)
        return button

    def browse(self):
        folder = filedialog.askdirectory(parent=self.root, title='Choose the raw IR directory', initialdir=self.directory.get() or None)
        if folder:
            self.directory.set(folder)

    def set_busy(self, busy):
        self.busy = busy
        for control in self.controls:
            control.configure(state='disabled' if busy else 'normal')
        self.cancel_button.configure(state='normal' if busy else 'disabled')

    def scan(self):
        if self.busy:
            return
        folder = Path(self.directory.get()).expanduser()
        if not folder.is_dir():
            messagebox.showerror('Cannot scan', 'Choose an existing IR directory.', parent=self.root)
            return
        if any(r['marked'] for r in self.rows) and not messagebox.askyesno('Discard marks?', 'Scanning will clear your unconfirmed marks. Continue?', parent=self.root):
            return
        self.folder = folder.resolve()
        self.rows = []
        self.populate()
        self.figure.clear()
        self.canvas.draw_idle()
        self.details.set('Scanning. The files remain unchanged.')
        self.cancel.clear()
        self.set_busy(True)
        def worker():
            try:
                rows = scan_directory(self.folder, lambda *args: self.events.put(('progress', args)), self.cancel.is_set)
                self.events.put(('done', rows))
            except Exception as error:
                self.events.put(('error', str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'progress':
                    phase, done, total = payload
                    self.status.set(f'{phase}: {done} / {total}')
                    self.progress.configure(maximum=max(total, 1), value=done)
                elif kind == 'done':
                    self.rows = payload
                    self.set_busy(False)
                    self.populate()
                    counts = {status: sum(r['status']==status for r in self.rows) for status in ('repeat', 'review', 'technical', 'excluded')}
                    self.status.set(f"Scan complete: {len(self.rows)} files; {counts['repeat']} repeat candidates, {counts['review']} review, {counts['technical']} technical, {counts['excluded']} excluded. No files changed.")
                    self.details.set('Select a recording. Click Exclude? or Mark selected to choose files for the rename confirmation.')
                    if self.tree.get_children():
                        self.tree.selection_set(self.tree.get_children()[0])
                else:
                    self.set_busy(False)
                    self.status.set(payload)
                    if not self.cancel.is_set():
                        messagebox.showerror('Scan failed', payload, parent=self.root)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def populate(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(self.rows):
            mode = self.filter.get()
            if mode == 'Needs review' and row['status'] in ('pass', 'excluded'):
                continue
            if mode == 'Excluded' and row['status'] != 'excluded':
                continue
            band = f"{row['band_low_hz']:.0f}–{row['band_high_hz']:.0f}" if 'band_low_hz' in row else ''
            score = f"{row['score']:.2f}" if row['status'] in ('repeat', 'review', 'pass') else ''
            self.tree.insert('', 'end', iid=str(i), values=('Yes' if row['marked'] else '', {'repeat': 'Suspect', 'pass': 'Okay'}.get(row['status'], row['status'].replace('_', ' ')), row.get('reason', ''), score, band, row['filename']), tags=(row['status'],))
        self.rename_button.configure(text=f"Rename marked ({sum(r['marked'] for r in self.rows)})")
        self.tree.selection_set([i for i in selected if self.tree.exists(i)])

    def toggle_mark(self, event):
        if self.busy or self.tree.identify_column(event.x) != '#1':
            return
        iid = self.tree.identify_row(event.y)
        if iid and self.rows[int(iid)]['status'] != 'excluded':
            self.rows[int(iid)]['marked'] = not self.rows[int(iid)]['marked']
            self.populate()
            self.tree.selection_set(iid)
            return 'break'

    def mark(self, marked):
        if not self.busy:
            for iid in self.tree.selection():
                if self.rows[int(iid)]['status'] != 'excluded':
                    self.rows[int(iid)]['marked'] = marked
            self.populate()

    def inspect(self, event=None):
        if self.busy or not self.tree.selection():
            return
        row = self.rows[int(self.tree.selection()[0])]
        description = f"{row['filename']} — {row['status'].replace('_', ' ')}. "
        description += row.get('reason', '') + '  Coverage: ' + row.get('coverage', 'Cropped IR') + '. '
        if row.get('bands'):
            description += '  '.join(f"{band['low_hz']:.0f}–{band['high_hz']:.0f} Hz: 12/24-neighbour scores " + '/'.join(f"{check['score']:.2f}" for check in band['checks']) for band in row['bands'])
        if 'cylindrical' in row:
            r, phi, z = row['cylindrical']
            description += f'  Position: r={r:g} mm, azimuth={phi:g}°, z={z:g} mm.'
        metrics = '  '.join(f'{key}: {value:.4g}' for key, value in row.get('metrics', {}).items())
        self.details.set(description+'\n'+metrics)
        try:
            draw_inspection(self.figure, self.folder, row, self.rows)
        except Exception as error:
            self.details.set(description+'  Plot unavailable: '+str(error))
        self.canvas.draw_idle()

    def apply_rename(self, rows, restore=False):
        if self.busy or not rows:
            return
        action = 'Restore' if restore else 'Exclude'
        names = '\n'.join(row['filename'] for row in rows[:15])
        if len(rows) > 15:
            names += f'\n… and {len(rows)-15} more marked files.'
        explanation = ('Remove .blacklisted and make these files available to WAV processing again?' if restore else 'Append .blacklisted so WAV processing ignores these files? Their contents are preserved.')
        if not messagebox.askyesno(f'{action} {len(rows)} recordings?', explanation+'\n\nDirectory: '+str(self.folder)+'\n\n'+names, parent=self.root):
            return
        try:
            renamed = rename_reviewed(self.folder, rows, restore)
        except (OSError, ValueError, KeyError) as error:
            messagebox.showerror('Rename failed', str(error), parent=self.root)
            return
        # Rescan so predictions reflect the remaining neighbours and restored files.
        for row in self.rows:
            row['marked'] = False
        self.directory.set(str(self.folder))
        self.scan()
        messagebox.showinfo('Renaming complete', f'{len(renamed)} files renamed. Re-run Stage 1 and later stages to update existing HALS results.', parent=self.root)

    def rename(self):
        self.apply_rename([row for row in self.rows if row['marked'] and row['status'] != 'excluded'])

    def restore(self):
        self.apply_rename([self.rows[int(i)] for i in self.tree.selection() if self.rows[int(i)]['status'] == 'excluded'], restore=True)

    def export_report(self):
        if not self.rows:
            return
        path = filedialog.asksaveasfilename(parent=self.root, title='Save scan report', defaultextension='.csv', initialfile='ir_quality_report.csv', filetypes=[('CSV', '*.csv')])
        if path:
            try:
                columns = REPORT_COLUMNS + ['marked']
                with open(path, 'w', newline='', encoding='utf-8') as stream:
                    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(self.rows)
            except OSError as error:
                messagebox.showerror('Export failed', str(error), parent=self.root)

    def export_blacklist(self):
        excluded = [r['filename'][:-len('.blacklisted')] for r in self.rows if r['status']=='excluded']
        if not excluded:
            messagebox.showinfo('No confirmed exclusions', 'Confirm exclusions using Rename marked first.', parent=self.root)
            return
        path = filedialog.asksaveasfilename(parent=self.root, title='Save confirmed blacklist', defaultextension='.txt', initialfile='blacklist.txt', filetypes=[('Text', '*.txt')])
        if path:
            try:
                Path(path).write_text(''.join(name+'\n' for name in excluded), encoding='utf-8')
            except OSError as error:
                messagebox.showerror('Export failed', str(error), parent=self.root)

    def help(self):
        window = tk.Toplevel(self.root)
        window.title('How the IR scan works')
        text = tk.Text(window, wrap='word', width=95, height=30, padx=12, pady=12)
        text.pack(fill='both', expand=True)
        text.insert('1.0', HELP)
        text.configure(state='disabled')
        ttk.Button(window, text='Close', command=window.destroy).pack(pady=6)

    def close(self):
        self.cancel.set()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', default='')
    args = parser.parse_args()
    root = tk.Tk()
    ReviewApp(root, args.directory)
    root.mainloop()


if __name__ == '__main__':
    main()
