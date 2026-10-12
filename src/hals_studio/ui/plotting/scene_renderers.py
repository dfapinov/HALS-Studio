"""3D field geometry renderers used by analysis panes."""
import numpy as np
import pyvista as pv
from hals_studio.analysis import acoustics as ac
from hals_studio.analysis.analysis_metrics import contour_levels
from hals_studio.ui.plotting.plots import (balloon_mesh, volume_mesh, beam_tunnel_mesh,
    coverage_surface, audio_ticks, audio_frequency, FREQUENCY_STRETCH)


def balloon(self, s, rel, i):
    c, p = self.config, self.plotter
    mesh = balloon_mesh(s, rel[i], c['span'], c['geometry'])
    self.mesh = mesh
    scalar, cmap, clim = 'Relative level / dB', 'PColor', (-c['span'], 0)
    if c['phase_colour']:
        phase = np.angle(s.pressure[i]*np.exp(2j*np.pi*s.freqs[i]*self.delay_ms()/1000), deg=True)
        scalar, cmap, clim = 'Phase / degrees', 'twilight', (-180, 180)
        mesh[scalar] = np.column_stack((phase, phase[:, 0])).ravel(order='F')
    if p.scalar_bars: p.remove_scalar_bar(render=False)
    field_actor = p.add_mesh(mesh, name='field', scalars=scalar, cmap=cmap, clim=clim, show_edges=c['edges'],
               edge_color='#314d62', smooth_shading=True, reset_camera=False, **self.material(),
               scalar_bar_args=dict(title=scalar, color='#bed0e0', vertical=True, position_x=.88,
                                    position_y=.23, height=.5, width=.04, title_font_size=9, label_font_size=9))
    field_actor.GetProperty().SetSpecularColor(1., 1., 1.)
    if c['reference_sphere']:
        xyz = ac.directions(np.arange(-90, 91, 10), np.arange(-180, 181, 15))*1.005
        p.add_mesh(pv.StructuredGrid(*np.moveaxis(xyz, -1, 0)), name='reference', style='wireframe',
                   color='#678296', opacity=.16, reset_camera=False)
    else: p.remove_actor('reference', reset_camera=False)
    point = ac.directions([self.owner.elevation.value()], [self.owner.azimuth.value()])[0, 0]*1.06
    if self.handle is None:
        self.handle = p.add_sphere_widget(self.drag, center=point, radius=.055, color='#90ffbf',
            selected_color='white', pass_widget=True, test_callback=False, interaction_event='always')
        self.handle.SetScale(False)
    else: self.handle.SetCenter(point)
    p.add_mesh(pv.Line((0, 0, 0), point), name='probe', color='#90ffbf', line_width=2, reset_camera=False)
    p.render(); self.note.setText('Drag green handle to probe · Drag to orbit · Wheel to zoom')


def volume(self, s, rel, i):
    c, p = self.config, self.plotter
    volume_key = (id(s), c['smoothing'], c['normalization'], c['volume_mode'], c['contour_low'], c['contour_high'],
                  c['contour_step'], c['opacity_low'], c['contour_colours'], c['span'], 'PColor', c['surface_finish'], c['volume_coordinates'], c['beam_extent'])
    tunnel = c['volume_coordinates'] == 'Beam tunnel'
    y_extent, z_extent = (c['beam_extent'], c['beam_extent']) if tunnel else (180., 90.)
    if getattr(self, '_volume_key', None) != volume_key or getattr(self, '_scene_kind', None) != 'volume':
        camera = p.camera_position if getattr(self, '_scene_kind', None) == 'volume' else None
        p.clear(); self.set_lighting()
        grid_key = (id(s), c['smoothing'], c['normalization'], c['volume_coordinates'], c['beam_extent'])
        if getattr(self, '_grid_key', None) != grid_key:
            self._scalar_volume = (beam_tunnel_mesh(s, rel, c['beam_extent']) if tunnel else volume_mesh(s, rel, full_azimuth=True))
            self._grid_key = grid_key
        grid = self._scalar_volume; self.mesh = grid
        if c['volume_mode'] == 'H/V colour slices':
            for j, normal in enumerate(((0, 0, 1), (0, 1, 0))):
                p.add_mesh(grid.slice(normal=normal, origin=(0, 0, 0)), scalars='Relative level / dB',
                           cmap='PColor', clim=(-c['span'], 0), show_scalar_bar=j == 0, **self.material())
        else:
            from matplotlib import colormaps
            contours = contour_levels(c['contour_low'], c['contour_high'], c['contour_step'])
            geometry_key = (*grid_key, c['volume_mode'], tuple(contours))
            if getattr(self, '_contour_cache_key', None) != geometry_key:
                self._contour_geometry = {}; self._contour_cache_key = geometry_key
            self.contour_surfaces = []
            for n, level in enumerate(contours):
                fraction = n/max(1, len(contours)-1)
                opacity = .95*(1-fraction)+c['opacity_low']*fraction
                # Clip the 3D scalar volume, then extract its boundary. This
                # creates closed nested solids, not translucent frequency slices.
                if level not in self._contour_geometry:
                    if c['volume_mode'] != 'Level crossings':
                        surface = grid.clip_scalar(scalars='Relative level / dB', value=level, invert=False).extract_surface(algorithm='dataset_surface').triangulate().clean()
                    else: surface = coverage_surface(grid, level, closed=False)
                    self._contour_geometry[level] = surface
                surface = self._contour_geometry[level]
                if surface.n_points:
                    if c['contour_colours'] == 'Red shades':
                        # Equal green/blue components hold the hue at red,
                        # so alpha-compositing layers cannot create rainbow hues.
                        strong, pale = np.array([.78, .025, .025]), np.array([1., .52, .52])
                        color = tuple(strong*(1-fraction)+pale*fraction)
                    elif c['contour_colours'] == 'Single red':
                        color = (.78, .025, .025)
                    else:
                        color = colormaps['PColor'](.95-.8*fraction)[:3]
                    actor = p.add_mesh(surface, name=f'contour_{level:g}', color=color, opacity=opacity,
                               label=f'{level:g} dB', show_scalar_bar=False, smooth_shading=True,
                               split_sharp_edges=True, feature_angle=45, **self.material())
                    actor.GetProperty().SetSpecularColor(1., 1., 1.)
                    self.contour_surfaces.append((float(level), surface, float(opacity)))
            if self.contour_surfaces: p.add_legend(bcolor='#142331', size=(.2, min(.5, .045*len(contours))))
            else: p.add_text('No surfaces in the selected level range', font_size=10, color='#b5cedf')
            p.enable_depth_peeling(number_of_peels=12, occlusion_ratio=0.)
        p.add_mesh(grid.outline(), color='#6e8798')
        p.show_bounds(xtitle='Frequency / Hz', ytitle='Horizontal angle' if tunnel else 'Azimuth',
                      ztitle='Vertical angle' if tunnel else 'Elevation', show_xlabels=False,
                      color='#b5cedf', axes_ranges=(*np.log10(s.freqs[[0, -1]]), -y_extent, y_extent, -z_extent, z_extent),
                      n_ylabels=3, n_zlabels=3, font_size=9)
        ticks = audio_ticks(*s.freqs[[0, -1]])
        points = np.column_stack((FREQUENCY_STRETCH*np.log10(ticks), np.full(len(ticks), -y_extent/90-.13), np.full(len(ticks), -z_extent/90-.13)))
        p.add_point_labels(points, [audio_frequency(f) for f in ticks], font_size=10, show_points=False,
                           shape_opacity=0, always_visible=True, text_color='#c0d4e3')
        if camera: p.camera_position = camera
        self._volume_key = volume_key
    # A line marker identifies the selected frequency without introducing
    # a translucent slice that obscures the contour surfaces.
    x = FREQUENCY_STRETCH*np.log10(s.freqs[i])
    p.add_mesh(pv.Line((x, -y_extent/90, -z_extent/90), (x, y_extent/90, -z_extent/90)), name='frequency', color='#c9f3ff', line_width=2, reset_camera=False)
    p.render()
    if p.renderer.GetUseDepthPeeling() and not p.renderer.GetLastRenderingUsedDepthPeeling():
        p.disable_depth_peeling(); p.render()
    self.note.setText('Beam tunnel: length = frequency; radius = off-axis angle; around = cut orientation. H/V are perpendicular cuts.' if tunnel else
                      'Frequency × azimuth × elevation; flat caps mark sampled boundaries.')

