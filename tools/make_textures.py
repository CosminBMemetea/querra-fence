"""Generates the tileable grass textures for the "rich" pasture look (no downloaded assets, no licence questions).

    ~/PX4-Autopilot/Tools/setup/macos/.pixi/envs/default/bin/python tools/make_textures.py

Writes models/pasture_ground/materials/textures/grass_albedo.png and grass_normal.png (1024x1024, seamless).
The noise is built in the frequency domain, so it tiles by construction. The mean colour is kept close to the
"classic" flat green, so the inspection camera sees roughly the same ground the detector was trained on.
"""
import os
import struct
import zlib

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "models", "pasture_ground", "materials", "textures")
N = 1024


def periodic_noise(rng, beta, lo=1.0, hi=None):
    """Tileable noise with a 1/f^beta spectrum between frequencies lo and hi (cycles per tile), scaled to 0..1."""
    f = np.fft.fftfreq(N) * N
    fx, fy = np.meshgrid(f, f)
    r = np.hypot(fx, fy)
    amp = np.zeros_like(r)
    m = (r >= lo) & ((r <= hi) if hi else True)
    amp[m] = r[m] ** (-beta / 2.0)
    spec = amp * np.exp(2j * np.pi * rng.random((N, N)))
    n = np.real(np.fft.ifft2(spec))
    n -= n.min()
    return n / n.max()


def write_png(path, rgb):
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[i].tobytes() for i in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                 chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    rng = np.random.default_rng(7)
    os.makedirs(OUT, exist_ok=True)
    patches = periodic_noise(rng, 3.2, 1, 24)          # large lighter / darker patches of grass
    dry = periodic_noise(rng, 2.6, 2, 60)              # dry, yellowish areas
    blades = periodic_noise(rng, 1.0, 60, None)        # fine blade texture
    soil = periodic_noise(rng, 1.4, 30, None)          # rare bare-soil specks

    # sRGB 0..1. Renders come out at about 0.9x the texture, so a mean near (150, 178, 104) renders close to the
    # classic ground (about 141, 163, 104 in the inspection view; checked with tools/snap_world.sh).
    base = np.array([0.60, 0.71, 0.42])
    darker = np.array([0.50, 0.62, 0.34])
    straw = np.array([0.74, 0.72, 0.46])
    dirt = np.array([0.50, 0.43, 0.30])
    # large patches stay subtle: strong ones repeat visibly across a tiled ground
    t = np.clip((patches - 0.35) * 2.2, 0, 1)[..., None] * 0.22
    col = base * (1 - t) + darker * t
    d = np.clip((dry - 0.62) * 3.0, 0, 1)[..., None] * 0.28
    col = col * (1 - d) + straw * d
    col *= (0.86 + 0.28 * blades)[..., None]
    s = (soil > 0.88)[..., None] * 0.5
    col = col * (1 - s) + dirt * s
    rgb = (np.clip(col, 0, 1) * 255).astype(np.uint8)
    write_png(os.path.join(OUT, "grass_albedo.png"), rgb)

    # normal map from a height field of blades + small clumps (tangent space, +Z up)
    hgt = 0.65 * blades + 0.35 * periodic_noise(rng, 2.0, 20, 200)
    gx = (np.roll(hgt, -1, 1) - np.roll(hgt, 1, 1)) * 6.0
    gy = (np.roll(hgt, -1, 0) - np.roll(hgt, 1, 0)) * 6.0
    nz = np.ones_like(gx)
    norm = np.sqrt(gx * gx + gy * gy + nz * nz)
    nrm = np.stack([-gx / norm, -gy / norm, nz / norm], -1)
    nrm = nrm.reshape(N // 2, 2, N // 2, 2, 3).mean((1, 3))           # 512 px is enough for the bumps; ~4x smaller file
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
    write_png(os.path.join(OUT, "grass_normal.png"), ((nrm * 0.5 + 0.5) * 255).astype(np.uint8))
    print("textures: mean albedo (sRGB) %s" % np.round(rgb.reshape(-1, 3).mean(0)).astype(int).tolist())


if __name__ == "__main__":
    main()
