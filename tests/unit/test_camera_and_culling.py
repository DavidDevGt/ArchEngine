"""Pruebas unitarias de proyeccion analitica de camara y back-face culling (FR-09, FR-11)."""

import numpy as np

from archengine.geometry.primitives import Face
from archengine.render.core import (
    CameraKeyframe,
    CameraTrack,
    Renderer,
    orbit_cam,
)


def test_orbit_cam_target_centered_at_screen() -> None:
    w, h = 1080, 1920
    target = (100.0, -50.0, 25.0)
    cam = orbit_cam(target=target, azimuth=45.0, elevation=35.264, scale=1.0, width=w, height=h)

    # Proyectar el punto objetivo exacto
    screen_pt = cam.project_points(np.array([target], dtype=np.float64))[0]
    # Debe coincidir exactamente con el centro del canvas (w/2, h/2)
    assert abs(screen_pt[0] - (w / 2.0)) < 1e-4
    assert abs(screen_pt[1] - (h / 2.0)) < 1e-4


def test_backface_culling_invariable() -> None:
    """Verifica que caras que apuntan en contra de la camara son descartadas (Invariante 11)."""
    cam = orbit_cam(target=(0.0, 0.0, 0.0), azimuth=0.0, elevation=0.0)
    # Camara mira hacia +Y (forward = [0, 1, 0])
    # Cara con normal [0, -1, 0] mira hacia la camara -> dot = (0)(0) + (-1)(1) = -1 < 0 -> VISIBLE
    facing_face = Face(
        vertices=np.array([[0, 0, 0], [10, 0, 0], [10, 0, 10], [0, 0, 10]], dtype=np.float64),
        normal=np.array([0.0, -1.0, 0.0], dtype=np.float64),
        color_token="mem",
        id="front",
    )
    # Cara con normal [0, 1, 0] mira en la misma direccion de la vista -> dot = 1 > 0 -> CULLED
    back_face = Face(
        vertices=np.array([[0, 10, 0], [10, 10, 0], [10, 10, 10], [0, 10, 10]], dtype=np.float64),
        normal=np.array([0.0, 1.0, 0.0], dtype=np.float64),
        color_token="mem",
        id="back",
    )

    renderer = Renderer(width=100, height=100)
    # Renderizamos ambas
    renderer.render_frame([facing_face, back_face], cam)
    # Comprobar condicion analitica de culling
    assert np.dot(facing_face.normal, cam.d_view) < 0.0
    assert np.dot(back_face.normal, cam.d_view) > 0.0


def test_camera_track_smoothstep_interpolation() -> None:
    track = CameraTrack(
        [
            CameraKeyframe(t_us=0, azimuth=0.0, elevation=0.0, scale=1.0),
            CameraKeyframe(t_us=1_000_000, azimuth=90.0, elevation=45.0, scale=2.0),
        ]
    )

    # En t=0 y t=1s
    c0 = track.camera_at(0)
    assert abs(c0.azimuth - 0.0) < 1e-4

    c1 = track.camera_at(1_000_000)
    assert abs(c1.azimuth - 90.0) < 1e-4

    # En t=0.5s, smoothstep(0.5) = 3*(0.25) - 2*(0.125) = 0.5
    cmid = track.camera_at(500_000)
    assert abs(cmid.azimuth - 45.0) < 1e-4
    assert abs(cmid.elevation - 22.5) < 1e-4
    assert abs(cmid.scale - 1.5) < 1e-4
