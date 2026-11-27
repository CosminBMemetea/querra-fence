"""Supersampled dataset cameras (tools/make_dataset.py for the drone, tools/make_ground_dataset.py for the ground robot).

The colour camera renders K times wider and taller, and each K x K block is averaged in linear light, as a sensor's
pixel collects the light that falls on it: a wire thinner than a pixel becomes the faint line a real camera records,
not a line that is there or not depending on where it falls."""
import numpy as np


def cam_rate(ss, w=640, h=400):
    """Frames per second of a w x h camera rendered ss times larger: 30 up to 640x400 pixels, fewer above, so the frames
    stay near 40 MB/s (55 MB/s at most, from 3840x2400). At 30 per second, 2560x1600 frames (12 MB each) arrived faster
    than Python read them: memory and swap filled up."""
    n = w * h * ss * ss / (640 * 400)
    return 30 if n <= 1 else max(2, int(60 / n))


# sRGB <-> linear light, to average supersampled pixels as a sensor would
_SRGB = np.arange(256) / 255.0
TO_LINEAR = np.where(_SRGB <= 0.04045, _SRGB / 12.92, ((_SRGB + 0.055) / 1.055) ** 2.4).astype(np.float32)


def downsample(a, k):
    """(H*k, W*k, 3) uint8 sRGB -> (H, W, 3): each k x k block averaged in linear light."""
    lin = TO_LINEAR[a].reshape(a.shape[0] // k, k, a.shape[1] // k, k, 3).mean(axis=(1, 3))
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)


def rgb(data, step, w, h):
    """A gz Image's bytes (rows of `step` bytes, maybe padded) -> (h, w, 3) uint8, without a copy."""
    return np.frombuffer(data, dtype=np.uint8)[: h * step].reshape(h, step)[:, : w * 3].reshape(h, w, 3)
