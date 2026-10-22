from dataclasses import dataclass, replace
import numpy as np

from optimus_swarm.rgbd_perception import RGBDFrame


@dataclass(frozen=True)
class FaultConfig:
    depth_noise_sigma_m: float = 0.0
    missing_depth_fraction: float = 0.0
    occlusion_fraction: float = 0.0
    seed: int = 7

    def validate(self) -> None:
        if self.depth_noise_sigma_m < 0:
            raise ValueError("depth_noise_sigma_m must be >= 0")

        for name, value in (
            ("missing_depth_fraction", self.missing_depth_fraction),
            ("occlusion_fraction", self.occlusion_fraction),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class FaultResult:
    frame: RGBDFrame
    injected_faults: tuple[str, ...]
    seed: int


def inject_sensor_faults(frame: RGBDFrame, config: FaultConfig) -> FaultResult:
    """
    Returns a modified copy of a synthetic frame.

    Only the depth image is modified here. The occlusion operation
    creates a rectangular invalid-depth region; it does not simulate
    realistic light transport or RGB image formation.
    """
    config.validate()
    rng = np.random.default_rng(config.seed)
    depth = np.array(frame.depth_m, dtype=np.float32, copy=True)
    faults = []

    valid = np.isfinite(depth) & (depth > 0)

    if config.depth_noise_sigma_m > 0:
        noise = rng.normal(0.0, config.depth_noise_sigma_m, size=depth.shape)
        depth[valid] += noise[valid]
        depth[valid & (depth <= 0)] = np.nan
        faults.append("DEPTH_GAUSSIAN_NOISE")

    if config.missing_depth_fraction > 0:
        candidates = np.flatnonzero(np.isfinite(depth))
        count = int(round(len(candidates) * config.missing_depth_fraction))
        if count:
            selected = rng.choice(candidates, size=count, replace=False)
            depth.flat[selected] = np.nan
        faults.append("MISSING_DEPTH")

    if config.occlusion_fraction > 0:
        height, width = depth.shape
        occ_h = max(1, int(height * np.sqrt(config.occlusion_fraction)))
        occ_w = max(1, int(width * np.sqrt(config.occlusion_fraction)))
        occ_h = min(height, occ_h)
        occ_w = min(width, occ_w)

        y0 = int(rng.integers(0, height - occ_h + 1))
        x0 = int(rng.integers(0, width - occ_w + 1))
        depth[y0 : y0 + occ_h, x0 : x0 + occ_w] = np.nan
        faults.append("RECTANGULAR_DEPTH_OCCLUSION")

    return FaultResult(
        frame=replace(frame, depth_m=depth),
        injected_faults=tuple(faults),
        seed=config.seed,
    )
