"""Shared dark/blue and light/blue presentation for widgets and plot canvases."""
from matplotlib.colors import to_hex, to_rgb
import colorsys
import re
from PySide6 import QtWidgets as W

NAME = 'Dark'
LIGHT_MAP = {'#0b141e': '#f4f6f9',
 '#101c28': '#ffffff',
 '#101e2b': '#ffffff',
 '#142432': '#ffffff',
 '#122434': '#ffffff',
 '#182b3b': '#e7f0fc',
 '#132432': '#dceaff',
 '#172938': '#d5deeb',
 '#193344': '#edf4fc',
 '#244359': '#c8e0fa',
 '#245d75': '#599bda',
 '#c6d6e5': '#172c48',
 '#c2d1df': '#20324b',
 '#f1f7fd': '#102d52',
 '#eef6ff': '#102d52',
 '#829aaf': '#62758e',
 '#8da8bd': '#526c8d',
 '#91aabe': '#526c8d',
 '#849eb1': '#526c8d',
 '#8ca4b8': '#62758e',
 '#9eb5c8': '#365578',
 '#47d7ec': '#2469d8',
 '#52d9ec': '#2469d8',
 '#61dced': '#2469d8',
 '#4ed6ea': '#3379df',
 '#43c9df': '#599bda',
 '#41c7dc': '#599bda',
 '#071620': '#ffffff',
 '#071721': '#ffffff',
 '#2d4456': '#bdcde2',
 '#263848': '#cbd8e9',
 '#253849': '#cbd8e9',
 '#2a4357': '#bdd0e9',
 '#334555': '#bdcde2',
 '#2b3c4b': '#dbe2ed',
 '#314b60': '#a8c4e7',
 '#20394c': '#599bda',
 '#43d8eb': '#2469d8',
 '#39c5db': '#599bda',
 '#47d9ec': '#2469d8',
 '#4bd4e9': '#599bda',
 '#b1f0f8': '#cce7ff',
 '#baacf8': '#7657ae',
 '#ffba68': '#b66a18',
 '#7ae2b1': '#16836a',
 '#fa7b95': '#bf3d67',
 '#f3e69b': '#816618',
 '#b5cedf': '#365578',
 '#c9f3ff': '#285c99',
 '#aec7d4': '#385774',
 '#7895a8': '#62758e',
 '#54d9e8': '#2469d8'}

# HALS Control primary; every blue/cyan UI tone shares this hue while keeping
# its existing lightness and saturation (and therefore its visual hierarchy).
BASE_BLUE = '#599bda'
BASE_HUE = colorsys.rgb_to_hls(*to_rgb(BASE_BLUE))[0]

def blue_tone(value):
    try:
        h, lightness, saturation = colorsys.rgb_to_hls(*to_rgb(value))
        if 175/360 <= h <= 235/360 and saturation > .08:
            return to_hex(colorsys.hls_to_rgb(BASE_HUE, lightness, saturation))
    except (ValueError, TypeError): pass
    return value


def colour(value):
    try:
        original = to_hex(value).lower()
        return blue_tone(LIGHT_MAP.get(original, original) if NAME == 'Light' else original)
    except (ValueError, TypeError): return value


def stylesheet_colours(stylesheet):
    return re.sub(r'#[0-9a-fA-F]{6}', lambda m: colour(m.group()), stylesheet)


def chart_theme(chart):
    from matplotlib.text import Text
    from matplotlib.lines import Line2D
    light = NAME == 'Light'
    chart.fig.set_facecolor(blue_tone('#ffffff' if light else '#101c28'))
    for ax in chart.fig.axes:
        ax.set_facecolor(blue_tone('#ffffff' if light else '#101c28'))
        for spine in ax.spines.values(): spine.set_edgecolor(blue_tone('#bdcde2' if light else '#334555'))
        if hasattr(ax, '_response_axis_colour'):
            ax.spines['right' if ax.yaxis.get_label_position() == 'right' else 'left'].set_edgecolor(ax._response_axis_colour)
        for line in ax.get_xgridlines()+ax.get_ygridlines(): line.set_color(blue_tone('#dbe2ed' if light else '#2b3c4b'))
    for item in chart.fig.findobj():
        if isinstance(item, (Text, Line2D)):
            try: item.set_color(colour(item.get_color()))
            except (ValueError, TypeError): pass
        if light and isinstance(item, Text) and item.get_bbox_patch() is not None:
            item.get_bbox_patch().set_facecolor('#ffffff')

def scene_theme(plotter):
    if NAME == 'Light':
        plotter.set_background('#ffffff'); plotter.renderer.SetGradientBackground(False)
        for actor in plotter.renderer.actors.values():
            for method in ('GetTextProperty', 'GetTitleTextProperty', 'GetLabelTextProperty'):
                if hasattr(actor, method):
                    try: getattr(actor, method)().SetColor(.16, .28, .43)
                    except (TypeError, AttributeError): pass
    else:
        plotter.set_background(blue_tone('#09151f'), top=blue_tone('#1b3040'))
        for actor in plotter.renderer.actors.values():
            for method in ('GetTextProperty', 'GetTitleTextProperty', 'GetLabelTextProperty'):
                if hasattr(actor, method):
                    try: getattr(actor, method)().SetColor(.72, .84, .91)
                    except (TypeError, AttributeError): pass


def apply_theme(owner, name):
    global NAME
    from app import STYLE
    NAME = name; owner.theme_name = name
    # Native combo-popup frames use the Qt palette even when their item view
    # is styled. Keep those bevel colours in the same theme as the stylesheet.
    from PySide6.QtGui import QPalette,QColor
    palette=QPalette();dark=name=='Dark'
    for role,value in ((QPalette.Window,'#142432' if dark else '#ffffff'),(QPalette.Base,'#142432' if dark else '#ffffff'),(QPalette.Button,'#182b3b' if dark else '#e7f0fc'),(QPalette.WindowText,'#c2d1df' if dark else '#20324b'),(QPalette.Text,'#c2d1df' if dark else '#20324b'),(QPalette.ButtonText,'#c2d1df' if dark else '#20324b'),(QPalette.Light,'#2d4456' if dark else '#bdcde2'),(QPalette.Midlight,'#2d4456' if dark else '#bdcde2'),(QPalette.Dark,'#2d4456' if dark else '#bdcde2')):palette.setColor(role,QColor(value))
    W.QApplication.instance().setPalette(palette)
    stylesheet = stylesheet_colours(STYLE)
    if name == 'Light':
        stylesheet = stylesheet.replace('spin-up.svg', 'spin-up-light.svg').replace('spin-down.svg', 'spin-down-light.svg')
    owner.setStyleSheet(stylesheet)
    for title, action in getattr(owner, 'theme_actions', {}).items(): action.setChecked(title == name)
    # Refresh custom local widget styles as well as the shared stylesheet.
    for widget in owner.findChildren(W.QWidget):
        original = widget.property('theme_original_style')
        if original is None:
            original = widget.styleSheet(); widget.setProperty('theme_original_style', original)
        if original:
            widget.setStyleSheet(stylesheet_colours(original))
    for pane in owner.panes: pane.last_render = None
    owner.refresh()
    export = owner.export_workspace
    if export:
        export.response_panel.key = None; export.ir_panel.key = None; export.draw_response()
        scene_theme(export.plotter); export.plotter.render()
    if getattr(owner,'process_workspace',None):owner.process_workspace.draw()
