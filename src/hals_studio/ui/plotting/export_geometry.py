"""Physical export geometry rendering with no workspace or table dependencies."""

import numpy as np
import pyvista as pv
from hals_studio.application.export_engine import baffle_geometry, acoustic_origin


def draw_export_geometry(plotter, data, config, baffle_visible, output):
    p = plotter
    for elevation, azimuth, strength in [(30, -40, 0.95), (-20, 45, 0.3), (55, 145, 0.6)]:
        light = pv.Light(light_type="camera light", intensity=strength)
        light.set_direction_angle(elevation, azimuth)
        p.add_light(light)
    xyz = data["xyz"]
    scale = max(0.2, float(np.max(np.linalg.norm(xyz - data["origin"], axis=1))))
    vertices, named, known = baffle_geometry(config)
    if known and baffle_visible:
        # Show only the front baffle plane. Cabinet depth is not part of this view.
        baffle = pv.PolyData(vertices[:4], [4, 0, 1, 2, 3])
        p.add_mesh(
            baffle,
            color="#7199b0",
            opacity=1.0,
            lighting=False,
            culling=False,
            show_edges=True,
            edge_color="#c7e1ed",
            line_width=2,
            name="baffle",
            pickable=False,
        )
    # Mark the actual reference origin at the arrow stem, not the unused
    # world-coordinate zero when the project origin has been offset.
    p.add_mesh(
        pv.Sphere(radius=scale * 0.012, center=data["origin"]), color="#7ae2b1", specular=0.8
    )
    p.add_mesh(
        pv.Arrow(
            start=data["origin"],
            direction=data["forward"],
            scale=scale * 0.7,
            shaft_radius=0.009,
            tip_radius=0.035,
        ),
        color="#7ae2b1",
        specular=0.6,
    )
    from vtkmodules.vtkRenderingCore import vtkBillboardTextActor3D

    camera_pos = np.asarray(p.camera_position[0], float)

    def add_ball_label(point, text, actor_name):
        point = np.asarray(point, float)
        toward_camera = camera_pos - point
        norm = np.linalg.norm(toward_camera)
        if norm:
            point = point + toward_camera / norm * scale * 0.014
        actor = vtkBillboardTextActor3D()
        actor.SetInput(text)
        actor.SetPosition(*point)
        actor.SetDisplayOffset(0, 20)
        prop = actor.GetTextProperty()
        prop.SetFontSize(10)
        prop.SetColor(184 / 255, 214 / 255, 232 / 255)
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToBottom()
        prop.SetBold(True)
        p.add_actor(actor, name=actor_name, reset_camera=False, render=False, pickable=False)

    add_ball_label(data["origin"], "Reference origin", "reference-origin-label")
    colors = np.array(
        [
            [71, 215, 236]
            if name.startswith("H")
            else [255, 186, 104]
            if name.startswith("V")
            else [166, 146, 255]
            for name in data["names"]
        ],
        dtype=np.uint8,
    )
    point_mesh = pv.PolyData(xyz)
    point_mesh["rgb"] = colors
    p.add_mesh(
        point_mesh,
        scalars="rgb",
        rgb=True,
        point_size=11,
        render_points_as_spheres=True,
        name="points",
        pickable=True,
    )
    if config["mode"] != "Manual coordinates":
        forward = data["forward"]
        phi = np.deg2rad(config["zero_phi"])
        right = np.array([-np.sin(phi), np.cos(phi), 0])
        up = np.cross(forward, right)
        for prefix, tangent, color in [("H", right, "#47d7ec"), ("V", up, "#ffba68")]:
            indices = [i for i, name in enumerate(data["names"]) if prefix in name]
            if (
                config["mode"] == "Arc sweep"
                and prefix == "V"
                and config["direction"] == "hor_vert"
            ):
                indices.append(data["reference"])
            if len(indices) < 2:
                continue
            points = xyz[indices]
            angles = np.arctan2(
                (points - data["origin"]) @ tangent, (points - data["origin"]) @ forward
            )
            points = points[np.argsort(angles)]
            if config["mode"] == "CTA-2034":
                points = np.vstack([points, points[0]])
            p.add_mesh(
                pv.lines_from_points(points),
                color=color,
                line_width=2,
                opacity=0.55,
                pickable=False,
            )
    if config["show_stage2_origin"] and (config["project_path"] or config["coeff_path"]):
        try:
            frequency, origin = acoustic_origin(config)
            named.append((f"Acoustic origin · {frequency:g} Hz", origin))
        except (OSError, KeyError, ValueError):
            output("Acoustic origin is unavailable in this coefficient file.")
    from hals_studio.ui.plotting.plots import COLORS

    for index, (name, point) in enumerate(named):
        if name == "Project reference" and np.allclose(point, data["origin"]):
            continue  # Already shown by the green reference-origin marker.
        color = COLORS[index % len(COLORS)]
        p.add_mesh(pv.Sphere(radius=scale * 0.012, center=point), color=color, specular=0.6)
        add_ball_label(point, name, f"waypoint-label-{index}")
    p.add_axes(xlabel="X / forward", ylabel="Y", zlabel="Z / up")
    p.show_grid(
        color="#7895a8",
        xtitle="X / m",
        ytitle="Y / m",
        ztitle="Z / m",
        font_size=9,
        n_xlabels=3,
        n_ylabels=3,
        n_zlabels=3,
        grid="back",
        location="outer",
    )
    return point_mesh, known
