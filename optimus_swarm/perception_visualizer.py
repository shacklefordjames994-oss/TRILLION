import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from optimus_swarm.rgbd_perception import RGBDResult
from optimus_swarm.synthetic_scene import SyntheticScene


def show_perception_overlay(scene: SyntheticScene, result: RGBDResult, save_path: str | None = None):
    """
    Draw the synthetic RGB image with detection boxes.

    Headless runs save the figure instead of blocking on a window.
    The image is a debug overlay, not a camera capture.
    """
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.imshow(scene.frame.rgb)
    ax.set_title(f"SIMULATION ONLY | Scene={scene.scene_id} | Frame={scene.frame.frame_id}")
    ax.set_xlabel("Image X (pixels)")
    ax.set_ylabel("Image Y (pixels)")

    if not result.accepted:
        ax.text(
            0.02,
            0.98,
            f"PERCEPTION REJECTED: {result.code}",
            transform=ax.transAxes,
            va="top",
            color="white",
        )
    else:
        by_id = {obj.object_id: obj for obj in result.objects}

        for detection in scene.detections:
            x1, y1, x2, y2 = detection.bbox_xyxy
            ax.add_patch(
                Rectangle(
                    (x1, y1),
                    x2 - x1,
                    y2 - y1,
                    fill=False,
                    linewidth=2,
                    edgecolor="white",
                )
            )

            obj = by_id.get(detection.object_id)
            if obj is None:
                label = f"{detection.class_name}: depth unavailable"
            else:
                x, y, z = obj.position_world_xyz
                label = (
                    f"{obj.object_id} ({obj.class_name})\n"
                    f"XYZ=({x:.2f}, {y:.2f}, {z:.2f}) m\n"
                    f"conf={obj.confidence:.2f}; "
                    f"depth MAD={obj.depth_spread_m:.3f} m"
                )

            ax.text(x1, max(0, y1 - 4), label, fontsize=8, va="bottom", color="white")

    fig.tight_layout()
    target = save_path
    if target is None and not os.environ.get("DISPLAY"):
        target = os.path.join("artifacts", "warehouse_overlay.png")
    if target:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        fig.savefig(target, dpi=120)
        plt.close(fig)
        return target
    plt.show()
    return None
