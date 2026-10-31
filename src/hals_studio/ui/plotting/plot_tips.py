"""Short context-sensitive guidance drawn in the existing canvas margin."""


class PlotTips:
    def __init__(self, host, workspace):
        self.host, self.workspace = host, workspace
        self.label = host.fig.text(.008, .008, '', ha='left', va='bottom', fontsize=8,
                                   color=host.interaction.axes[0].yaxis.label.get_color())
        for name in ('motion_notify_event', 'button_press_event', 'button_release_event',
                     'scroll_event', 'figure_leave_event', 'key_press_event'):
            host.canvas.mpl_connect(name, self.update)
        self.update()

    def update(self, event=None):
        host = self.host
        stage2 = self.workspace.stage == 2
        drawing = stage2 and self.workspace.draw_origin_line.isChecked()
        message = 'Left-drag to draw a line. Esc cancels.' if drawing else 'Middle-drag to pan. Wheel to zoom.'
        if host.interaction.pan:
            message = 'Panning — release the middle button to finish.'
        elif stage2 and host.origin_editor.start:
            message = 'Release to preview the edit. Esc cancels. Save Project to apply.'
        elif event is not None:
            if event.name == 'scroll_event':
                message = 'Zooming — Reset axes restores the full view.'
            elif event.name == 'figure_leave_event':
                message = 'Reset axes restores the full view.'
            elif stage2 and host.origin_selection.nearest(event) is not None:
                message = 'Click to select; drag to draw. Esc cancels.' if drawing else 'Click to show this point on X, Y and Z.'
            elif event.inaxes not in host.interaction.axes and event.x is not None and event.y is not None:
                message = 'Reset axes restores the full view.'
                for ax in host.interaction.axes:
                    box = ax.bbox
                    if box.x0 <= event.x <= box.x1 and box.y0-55 <= event.y < box.y0:
                        message = 'Wheel here to zoom the frequency axis.'
                        break
                    if box.y0 <= event.y <= box.y1 and box.x0-65 < event.x < box.x0:
                        message = 'Wheel here to zoom the vertical axis.'
                        break
        if message != self.label.get_text():
            self.label.set_text(message)
            host.canvas.draw_idle()
