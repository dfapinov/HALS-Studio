"""Backend-independent plotting views shared by Studio and standalone viewers."""
import functools
import warnings
import numpy as np
import matplotlib.pyplot as pyplot
import matplotlib.ticker as ticker
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


class FigureFactory:
    """Create unregistered figures; the embedding UI owns their canvas/lifetime."""
    def figure(self, *args, **kwargs):
        return Figure(*args, **kwargs)

    def subplots(self, *args, **kwargs):
        size = kwargs.pop('figsize', None)
        figure = Figure(figsize=size)
        return figure, figure.subplots(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(pyplot, name)


plt = FigureFactory()


def silence_log_warnings(func):
    """Decorator to suppress persistent Matplotlib log-scale layout warnings."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*non-positive.*")
            warnings.simplefilter("ignore", category=UserWarning)
            return func(*args, **kwargs)
    return wrapper


class FDWView:
    """Pure MVC View for Stage 1 FDW Analysis."""
    def __init__(self, figsize=(12, 10)):
        self.fig = plt.figure(figsize=figsize)
        self.gs = self.fig.add_gridspec(3, 1, hspace=0.35, height_ratios=[3, 2, 1])
        self.ax1 = self.fig.add_subplot(self.gs[0])
        self.ax2 = self.fig.add_subplot(self.gs[1]) 
        self.ax3 = self.fig.add_subplot(self.gs[2], sharex=self.ax1)
        self.fig.subplots_adjust(bottom=0.08, right=0.79, left=0.08, top=0.91)

    @staticmethod
    def _first_non_dc_freq(freqs):
        positive = np.asarray(freqs)[np.asarray(freqs) > 0]
        return float(positive[0]) if positive.size else 1.0

    @staticmethod
    def _audio_ticks(f_min, f_max):
        base_ticks = (10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000)
        return [float(tick) for tick in base_ticks if f_min <= tick <= f_max]

    @staticmethod
    def _format_audio_tick(freq_hz):
        if freq_hz >= 1000:
            value = freq_hz / 1000.0
            return f"{value:g} kHz"
        return f"{freq_hz:g} Hz"

    def _set_frequency_axis(self, ax, f_min, f_max):
        ax.set_xlim(f_min, f_max)
        ticks = self._audio_ticks(f_min, f_max)
        if ticks:
            ax.xaxis.set_major_locator(ticker.FixedLocator(ticks))
            ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: self._format_audio_tick(x)))

    @silence_log_warnings
    def update_view(self, fname, index, freqs, H_raw, H_smooth, meta_dict, wav_data, fs, fdw_rft_ms):
        m = meta_dict
        plot_f_min = self._first_non_dc_freq(freqs)
        plot_f_max = fs / 2
        
        self.ax1.clear()

        mag_db_raw = 20 * np.log10(np.abs(H_raw) + 1e-12)
        
        if H_smooth is not None:
            mag_db_smooth = 20 * np.log10(np.abs(H_smooth) + 1e-12)
            self.ax1.semilogx(freqs, mag_db_raw, color='silver', lw=1.0, alpha=0.6, label="FDW Raw")
            self.ax1.semilogx(freqs, mag_db_smooth, 'r', lw=1.5, zorder=15, label="FDW Smoothed")
            self.ax1.legend(loc="upper right", fontsize=9)
        else:
            self.ax1.semilogx(freqs, mag_db_raw, 'k', lw=2, zorder=10, label="FDW Raw")

        window_labels = []
        
        f_trans = m['f_trans']
        f_anchor = m.get('f_lf_anchor', 200.0)
        
        if m.get('rft_supplied', True):
            self.ax1.axvspan(f_trans, fs/2, color='#E0F7FA', alpha=0.5)
            self.ax1.text(1, 1.02, "Reflection free range",
                         color='#006064', fontsize=9, fontweight='bold', va='bottom', ha='right',
                         transform=self.ax1.transAxes,
                         bbox=dict(facecolor='white', alpha=0.7, edgecolor='none'), zorder=20)
        
        cmap = plt.get_cmap('YlOrRd')
        num_octaves = np.log2(plot_f_max / plot_f_min) if plot_f_max > plot_f_min else 1
        
        self.ax2.clear()
        
        if wav_data is not None:
            t_ms = np.linspace(0, len(wav_data)/fs * 1000, len(wav_data))
            self.ax2.plot(t_ms, wav_data, color='#333333', lw=1, zorder=1, label="Raw IR")
            local_max = np.max(np.abs(wav_data))
            if local_max > 0: self.ax2.set_ylim(-local_max/0.9, local_max/0.9)
            peak_time_ms = m['t_peak'] * 1000
            self.ax2.axvline(peak_time_ms, color='red', linestyle='-', linewidth=1.5, label='Detected Peak')
        else:
            self.ax2.text(0.5, 0.5, "Error loading wav", ha='center', va='center')
            t_ms, local_max, peak_time_ms = np.array([]), 0, 0

        valid_indices = [i for i, fc in enumerate(m['f_centers']) if plot_f_min <= fc <= f_trans]
        valid_centers = m['f_centers'][valid_indices]
        
        boundaries = [f_trans]
        if len(valid_centers) > 0 and abs(valid_centers[0] - f_trans) > 1.0: boundaries.append(valid_centers[0])
        if len(valid_centers) > 0: boundaries.extend(valid_centers[1:])
        boundaries.append(plot_f_min)
        
        for k in range(len(boundaries) - 1 if m.get('rft_supplied', True) else 0):
            high_bound, low_bound = boundaries[k], boundaries[k+1]
            f_mid = np.sqrt(high_bound * low_bound)
            norm_pos = np.log2(f_trans / f_mid) / num_octaves
            c_val = 0.1 + (0.5 * np.clip(norm_pos, 0, 1))
            self.ax1.axvspan(low_bound, high_bound, color=cmap(c_val), alpha=0.4)

        valid_band_idx = 0 
        for i, fc in enumerate(m['f_centers']):
            if fc < plot_f_min or fc > plot_f_max: continue
            
            norm_pos = np.log2(plot_f_max / fc) / num_octaves
            line_color = cmap(0.1 + (0.5 * np.clip(norm_pos, 0, 1)))
            self.ax1.axvline(fc, color=line_color, ls='-', alpha=0.8, linewidth=1.2)
            
            t_win_ms = m['t_windows'][i] * 1000
            label_y = .08 + (valid_band_idx % 3) * .14
            label_va = 'center'
            window_labels.append(self.ax1.text(fc, label_y, f"{fc:.0f}Hz\n{t_win_ms:.1f}ms", ha='right' if np.isclose(fc, plot_f_max) else 'center', va=label_va, fontsize=8, transform=self.ax1.get_xaxis_transform(), clip_on=True, bbox=dict(facecolor='white', alpha=0.6, edgecolor='none'), zorder=20))
            
            if len(t_ms) > 0:
                win_len_ms = t_win_ms
                alpha = m['alpha_sched'][i]
                t_end_abs = peak_time_ms + win_len_ms
                t_taper_len = win_len_ms * alpha
                t_taper_start_abs = t_end_abs - t_taper_len
                
                t_flat = np.array([0, t_taper_start_abs])
                y_flat = np.array([local_max, local_max])
                
                if t_taper_len > 0:
                    t_curve = np.linspace(t_taper_start_abs, t_end_abs, 50)
                    norm_t = (t_curve - t_taper_start_abs) / t_taper_len
                    y_curve = local_max * 0.5 * (1 + np.cos(np.pi * norm_t))
                else:
                    t_curve, y_curve = np.array([t_end_abs, t_end_abs]), np.array([local_max, 0])

                t_full = np.concatenate((t_flat, t_curve))
                y_full = np.concatenate((y_flat, y_curve))
                valid = t_full <= t_ms[-1]
                
                self.ax2.plot(t_full[valid], y_full[valid], color=line_color, lw=2, alpha=0.8, zorder=10, label=f"{fc:.0f}Hz: {win_len_ms:.1f}ms")
            valid_band_idx += 1

        from .plot_annotations import StackedWindowLabels
        self.window_labels = StackedWindowLabels(self.ax1, window_labels)

        self.ax2.legend(loc='upper left', bbox_to_anchor=(0.80, 0.90),
                        bbox_transform=self.fig.transFigure, fontsize=8, labelspacing=0.3)
        self.ax2.set_ylabel("Amplitude")
        self.ax2.set_xlabel("Time (ms)")
        self.ax2.set_title("Impulse Response Waveform & FDW Envelopes")
        self.ax2.grid(True, alpha=0.3)

        self.ax3.clear()
        f_raw, a_raw = m['f_centers'], m['alpha_sched']
        sort_idx = np.argsort(f_raw)
        f_plot, a_plot = f_raw[sort_idx], a_raw[sort_idx]
        
        if f_plot[0] > plot_f_min:
            f_plot = np.insert(f_plot, 0, plot_f_min)
            a_plot = np.insert(a_plot, 0, a_plot[0]) 
            
        self.ax3.semilogx(f_plot, a_plot, 'b-', lw=3)
        a_min, a_max = np.min(a_plot), np.max(a_plot)
        y_range = max(1e-3, a_max - a_min)
        
        self.ax3.axvline(f_trans, color='green', linestyle='--', alpha=0.7)
        self.ax3.text(f_trans, a_max - (y_range * 0.05), f" Alpha HF: {f_trans:.0f} Hz", color='green', fontsize=8, ha='left', va='top')
        self.ax3.axvline(f_anchor, color='green', linestyle='--', alpha=0.7)
        self.ax3.text(f_anchor, a_min + (y_range * 0.05), f"Alpha LF: {f_anchor:.0f} Hz ", color='green', fontsize=8, ha='right', va='bottom')

        self.ax3.set_ylabel("Alpha")
        self._set_frequency_axis(self.ax3, plot_f_min, fs/2)
        self.ax3.grid(True, which='both', alpha=0.3)

        self.ax1.set_title(f"File [{index}]: {fname}\nFDW Magnitude", pad=24)
        self.ax1.set_ylabel("Magnitude (dB)")
        self._set_frequency_axis(self.ax1, plot_f_min, fs/2)
        self.ax1.grid(True, which='both', alpha=0.3)
        
        self.fig.canvas.draw_idle()


class FrequencyBrowser3DView:
    """Pure MVC View for full 3D grid scan validation."""
    def __init__(self, cfg, figsize=(10, 8)):
        # Match the Stage 5 viewer: azimuth/elevation orbiting allows the
        # camera to move freely while keeping Z upright (no camera roll).
        plt.rcParams['axes3d.mouserotationstyle'] = 'azel'
        self.fig = plt.figure(figsize=figsize)
        self.ax = self.fig.add_subplot(111, projection='3d')
        # Reserve space for the three-line heading independently of 3D axes placement.
        self.fig.subplots_adjust(left=0.05, bottom=0.05, right=0.85, top=0.84)
        self.cbar_ax = self.fig.add_axes([0.88, 0.2, 0.03, 0.6])
        self.cbar = None
        
        self.ax.set_xlim(cfg['x_bounds'])
        self.ax.set_ylim(cfg['y_bounds'])
        self.ax.set_zlim(cfg['z_bounds'])
        self.ax.set_box_aspect((cfg['x_bounds'][1]-cfg['x_bounds'][0], cfg['y_bounds'][1]-cfg['y_bounds'][0], cfg['z_bounds'][1]-cfg['z_bounds'][0]))
        self.ax.set_xlabel('X (Depth) mm')
        self.ax.set_ylabel('Y (Width) mm')
        self.ax.set_zlabel('Z (Height) mm')

        self.ax.view_init(elev=30, azim=-45, roll=0, vertical_axis='z')

    def update_view(self, f, grid_3d, xv, yv, zv, final_c, plane, val):
        while self.ax.collections: self.ax.collections[0].remove()
        for line in self.ax.lines: line.remove()
            
        actual_val = val
        if grid_3d is not None:
            vmin, vmax = grid_3d.min(), grid_3d.max()
            norm = plt.Normalize(vmin=vmin, vmax=vmax)
            sm = plt.cm.ScalarMappable(cmap='viridis', norm=norm)
            sm.set_array([])
            
            if plane == 'YZ (X Depth)':
                idx = (np.abs(xv - val)).argmin()
                actual_val = xv[idx]
                slice_2d = grid_3d[idx, :, :]
                Y_grid, Z_grid = np.meshgrid(yv, zv, indexing='ij')
                X_grid = np.full_like(Y_grid, actual_val)
            elif plane == 'XZ (Y Width)':
                idx = (np.abs(yv - val)).argmin()
                actual_val = yv[idx]
                slice_2d = grid_3d[:, idx, :]
                X_grid, Z_grid = np.meshgrid(xv, zv, indexing='ij')
                Y_grid = np.full_like(X_grid, actual_val)
            else:
                idx = (np.abs(zv - val)).argmin()
                actual_val = zv[idx]
                slice_2d = grid_3d[:, :, idx]
                X_grid, Y_grid = np.meshgrid(xv, yv, indexing='ij')
                Z_grid = np.full_like(X_grid, actual_val)

            colors = plt.cm.viridis(norm(slice_2d))
            self.ax.plot_surface(X_grid, Y_grid, Z_grid, facecolors=colors, rstride=1, cstride=1, shade=False, alpha=0.85)
            
            if self.cbar is None: self.cbar = self.fig.colorbar(sm, cax=self.cbar_ax)
            else: self.cbar.update_normal(sm)
            self.cbar.set_label('Residual Error (%)')
            grid_min_text = f"{np.min(grid_3d):.2f}%"
        else:
            grid_min_text = "N/A (Bypassed)"
            if self.cbar is not None:
                self.cbar.remove()
                self.cbar = None

        if final_c is not None:
            self.ax.scatter(final_c[0], final_c[1], final_c[2], c='yellow', marker='D', s=100, edgecolors='black', label='Simplex Final')

        self.ax.legend(loc='upper right', bbox_to_anchor=(1.25, 1.0), fontsize=9)
        fc_str = f"({final_c[0]:.1f}, {final_c[1]:.1f}, {final_c[2]:.1f})" if final_c is not None else "None"
        self.fig.suptitle(f"Frequency: {f:.1f} Hz | Grid Scan Minima: {grid_min_text}\nSearch Final: {fc_str}\nPlane: {plane} @ {actual_val:.1f} mm",
                          x=0.45, y=0.98, va='top', fontsize=11, fontweight='bold')
        self.fig.canvas.draw_idle()


class CloudBrowser3DView:
    """Pure MVC View for 3D Coordinate Cloud."""
    def __init__(self, cfg, figsize=(8, 6)):
        # Match the Stage 5 viewer: azimuth/elevation orbiting allows the
        # camera to move freely while keeping Z upright (no camera roll).
        plt.rcParams['axes3d.mouserotationstyle'] = 'azel'
        self.fig = plt.figure(figsize=figsize)
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.fig.subplots_adjust(bottom=0.1, left=0.05, right=0.95, top=0.9)
        
        self.ax.set_xlabel('X (Depth) mm')
        self.ax.set_ylabel('Y (Width) mm')
        self.ax.set_zlabel('Z (Height) mm')

        self.ax.view_init(elev=30, azim=-45, roll=0, vertical_axis='z')
        self.scatter_all, self.scatter_hi = None, None

    def update_view(self, freqs, pts_x, pts_y, pts_z, active_idx):
        if not freqs: return
        if self.scatter_all is not None: self.scatter_all.remove()
        if self.scatter_hi is not None: self.scatter_hi.remove()
        
        self.scatter_all = self.ax.scatter(pts_x, pts_y, pts_z, c='blue', s=30, alpha=0.6, label='Nelder Final')
        
        f = freqs[active_idx]
        pt = (pts_x[active_idx], pts_y[active_idx], pts_z[active_idx])
        self.scatter_hi = self.ax.scatter([pt[0]], [pt[1]], [pt[2]], c='red', s=120, alpha=1.0, label='Highlighted')
        
        # Auto-scale cubic bounds based on the actual point cloud
        max_range = np.array([
            np.max(pts_x) - np.min(pts_x),
            np.max(pts_y) - np.min(pts_y),
            np.max(pts_z) - np.min(pts_z)
        ]).max() / 2.0
        
        if max_range == 0: max_range = 10.0  # Fallback if all points are identical
        
        mid_x = (np.max(pts_x) + np.min(pts_x)) * 0.5
        mid_y = (np.max(pts_y) + np.min(pts_y)) * 0.5
        mid_z = (np.max(pts_z) + np.min(pts_z)) * 0.5
        
        self.ax.set_xlim(mid_x - max_range, mid_x + max_range)
        self.ax.set_ylim(mid_y - max_range, mid_y + max_range)
        self.ax.set_zlim(mid_z - max_range, mid_z + max_range)
        self.ax.set_box_aspect((1, 1, 1))

        self.ax.legend(loc='upper right')
        self.ax.set_title(f"Frequency: {f:.1f} Hz\nCoordinate: ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f})", fontweight='bold')
        self.fig.canvas.draw_idle()


class ValidationView:
    """Pure MVC View for Origin Search validation plotting."""
    def __init__(self, figsize=(10, 10)):
        self.fig, (self.ax_x, self.ax_y, self.ax_z) = plt.subplots(3, 1, figsize=figsize, sharex=True)
        self.fig.subplots_adjust(bottom=0.1, top=0.95, right=0.95, left=0.1)

    @silence_log_warnings
    def update_view(self, history_freq, history_search, history_orig, history_err_search, history_err_orig):
        axes = [self.ax_x, self.ax_y, self.ax_z]
        labels = ['X (Depth)', 'Y (Width)', 'Z (Height)']
               
        for ax in axes: 
            ax.clear()
        
        for i, sax in enumerate(axes):
            sax.format_xdata = lambda x: f"{x:.1f} Hz"
            sax.format_ydata = lambda y: f"{y:.2f} mm"

            sax.plot(history_freq, history_search[i], 'b-', alpha=0.5, label='Search Path' if i == 0 else "")
            
            sax.plot(history_freq, history_search[i], 'bo', alpha=0.8,
                     label='Current Result' if i == 0 else '')
            for j, f in enumerate(history_freq):
                offset=7 if j % 2 == 0 else -7
                sax.annotate(f"{history_err_search[j]:.0f}%",
                             (f, history_search[i][j]), xytext=(0, offset),
                             textcoords='offset points', color='blue', fontsize=7,
                             ha='center', va='bottom' if offset>0 else 'top', alpha=0.85)

            sax.margins(y=0.2)
            sax.set_xscale('log')
            sax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f"{int(x/1000)}kHz" if x >= 1000 else f"{int(x)}Hz"))
            sax.set_xticks([20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000])
            sax.set_ylabel(f'{labels[i]} (mm)')
            sax.grid(True, which='both', ls='--', alpha=0.3)
            if i == 0:
                sax.set_title('Frequency Sweep Validation: Coordinates & Residual Error Labels', fontweight='bold')

        self.ax_z.set_xlabel('Frequency (Hz)')
        self.fig.canvas.draw_idle()


class SHEResultsView:
    """Pure MVC View for Stage 4 SHE Results."""
    def __init__(self, figsize=(10, 6)):
        self.fig, self.ax_err = plt.subplots(figsize=figsize)
        self.fig.subplots_adjust(bottom=0.2)
        
        self.line_err, = self.ax_err.plot([], [], 'b-', linewidth=1.5, alpha=0.8, label='Fit Error')
        self.line_thresh = self.ax_err.axhline(y=-20.0, color='red', linestyle='--', alpha=0.7, label='10% or -20dB Error')
        
        self.ax_err.set_xscale('log')
        self.ax_err.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f"{int(x/1000)}kHz" if x >= 1000 else f"{int(x)}Hz"))
        self.ax_err.set_xticks([20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000])
        self.ax_err.grid(True, which='both', ls='--', alpha=0.5)
        self.ax_err.set_xlabel('Frequency')
        
        self.ax_n = self.ax_err.twiny()
        self.ax_n.set_xscale('log')
        
        self.fig_cond = None
        self.ax_cond = None
        self.ax_cond_n = None

    @silence_log_warnings
    def update_view(self, f_sel, pct_error, db_error, boundaries, tick_locs, tick_labels, min_n, max_n, is_db=True):
        self.ax_err.set_xlim(f_sel[0], f_sel[-1])
        self.ax_n.set_xlim(self.ax_err.get_xlim())
        
        if is_db:
            self.line_err.set_data(f_sel, db_error)
            self.line_thresh.set_ydata([-20.0, -20.0])
            self.ax_err.set_ylabel('Fit Error (dB)')
            self.ax_err.format_ydata = lambda y: f"{y:.1f} dB"
            self.ax_err.set_ylim(auto=True)
        else:
            self.line_err.set_data(f_sel, pct_error)
            self.line_thresh.set_ydata([10.0, 10.0])
            self.ax_err.set_ylabel('Fit Error (%)')
            self.ax_err.format_ydata = lambda y: f"{y:.2f}%"
            self.ax_err.set_ylim(bottom=0, top=max(20.0, np.max(pct_error) * 1.1))

        self.ax_err.relim()
        self.ax_err.autoscale_view()
        
        for p in reversed(self.ax_err.patches):
            p.remove()
            
        cmap = plt.get_cmap('YlOrRd')
        for (f_start, f_end, n) in boundaries:
            norm_n = (n - min_n) / max(1, max_n - min_n)
            c_val = 0.1 + (0.5 * np.clip(norm_n, 0, 1))
            self.ax_err.axvspan(f_start, f_end, facecolor=cmap(c_val), alpha=0.4, edgecolor='none', linewidth=0)

        self.ax_n.set_xticks(tick_locs)
        self.ax_n.set_xticklabels(tick_labels)
        self.ax_n.set_xlabel('Order N')
        self.ax_n.minorticks_off()
        
        self.ax_err.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=2)
        self.fig.canvas.draw_idle()

    @silence_log_warnings
    def update_cond_view(self, f_sel, res_cond, order_ticks=None, order_labels=None):
        if self.fig_cond is None:
            self.fig_cond, self.ax_cond = plt.subplots(figsize=(10, 6))
            self.fig_cond.subplots_adjust(bottom=0.2)
            self.line_cond, = self.ax_cond.plot([], [], 'g-', linewidth=1.5, alpha=0.8, label='Condition Number')
            self.ax_cond.set_xscale('log')
            self.ax_cond.set_yscale('log')
            self.ax_cond.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f"{int(x/1000)}kHz" if x >= 1000 else f"{int(x)}Hz"))
            self.ax_cond.set_xticks([20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000])
            self.ax_cond.grid(True, which='both', ls='--', alpha=0.5)
            self.ax_cond.set_xlabel('Frequency')
            self.ax_cond.set_ylabel('Condition Number')
            self.ax_cond.set_title('SHE Solver: Matrix Condition Number vs Frequency')
            self.ax_cond.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=1)
            self.ax_cond_n = self.ax_cond.twiny()
            self.ax_cond_n.set_xscale('log')
            self.ax_cond_n.set_xlabel('Order N')
        
        self.ax_cond.set_xlim(f_sel[0], f_sel[-1])
        self.ax_cond_n.set_xlim(f_sel[0], f_sel[-1])
        self.line_cond.set_data(f_sel, res_cond)
        self.ax_cond.relim()
        self.ax_cond.autoscale_view()
        if order_ticks is not None:
            self.ax_cond_n.set_xticks(order_ticks)
            self.ax_cond_n.set_xticklabels(order_labels or [])
            self.ax_cond_n.minorticks_off()
        self.fig_cond.canvas.draw_idle()


class SpatialErrorView:
    """
    Pure MVC View class for Spatial Error. Handles Matplotlib rendering.
    """
    def __init__(self, figsize=(10, 8)):
        self.fig = plt.figure(figsize=figsize)
        from hals_studio.ui.plotting.spatial_axes import SpatialAxes3D
        self.ax = self.fig.add_subplot(111, axes_class=SpatialAxes3D)
        self.fig.subplots_adjust(left=0, right=0.85, bottom=0.05, top=0.95)
        self.cbar_ax = self.fig.add_axes([0.85, 0.15, 0.03, 0.7])
        self.cbar = None
        self.scatter = None
        
        self.ax.set_xlabel("X (m)")
        self.ax.set_ylabel("Y (m)")
        self.ax.set_zlabel("Z (m)")

    def update_view(self, x_coords, y_coords, z_coords, freq, n_used, p_measured, p_reconstructed, threshold_db):
        eps = np.finfo(float).eps
        mags_db = 20 * np.log10(np.abs(p_measured) + eps)
        max_mag_db = np.max(mags_db)
        cutoff_db = max_mag_db + threshold_db

        with np.errstate(divide='ignore', invalid='ignore'):
            error = np.abs(p_reconstructed - p_measured)
            norm_p = np.abs(p_measured)
            pct_error = np.where(norm_p > 1e-9, (error / norm_p) * 100.0, 0)

        pct_error_clipped = np.clip(pct_error, 0, 25).astype(float)
        
        mask_below_thresh = mags_db < cutoff_db
        pct_error_clipped[mask_below_thresh] = np.nan

        if self.scatter is not None:
            self.scatter.remove()

        cmap = plt.get_cmap('viridis_r').copy()
        cmap.set_bad(color='lightgray', alpha=0.2)
        self.scatter = self.ax.scatter(x_coords, y_coords, z_coords, c=pct_error_clipped, cmap=cmap, vmin=0, vmax=25)
        
        if self.cbar is None:
            self.cbar = self.fig.colorbar(self.scatter, cax=self.cbar_ax)
            self.cbar.set_label('Fit Error (%)')
            
            max_range = np.array([x_coords.max()-x_coords.min(), y_coords.max()-y_coords.min(), z_coords.max()-z_coords.min()]).max() / 2.0
            mid_x = (x_coords.max()+x_coords.min()) * 0.5
            mid_y = (y_coords.max()+y_coords.min()) * 0.5
            mid_z = (z_coords.max()+z_coords.min()) * 0.5
            self.ax.set_xlim(mid_x - max_range, mid_x + max_range)
            self.ax.set_ylim(mid_y - max_range, mid_y + max_range)
            self.ax.set_zlim(mid_z - max_range, mid_z + max_range)
            self.ax.set_box_aspect((1, 1, 1))

        self.ax.set_title(f'Fit Error at {freq:.1f} Hz (Order N = {n_used})')
        self.fig.canvas.draw_idle()

