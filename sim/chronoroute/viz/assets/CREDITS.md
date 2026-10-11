# Earth texture used by the viewer: source and credit

**Credit: NASA Earth Observatory.** NASA imagery is generally not subject to copyright in the
United States and may be used with credit
(<https://www.nasa.gov/nasa-brand-center/images-and-media/>).

| File | Size | Source image | Credit |
|---|---|---|---|
| `earth-day-2048.jpg` | 2048 x 1024, 247,132 bytes, sha256 `5b0183e6a575c048a811643a83a842c34e56f6276fb80304f78fe4e026b48d25` | Blue Marble: Next Generation with Topography and Bathymetry, October 2004 (MODIS-based composite) | NASA Earth Observatory |

This is a byte-identical copy of the website's `public/textures/earth-day-2048.jpg`
(see that folder's `CREDITS.md`). It was made from

| Downloaded file | URL | Bytes | sha256 |
|---|---|---|---|
| `world.topo.bathy.200410.3x5400x2700.jpg` (5400 x 2700) | <https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73826/world.topo.bathy.200410.3x5400x2700.jpg> | 2,459,484 | `f9ad745c780281dbfdda9769f10b161aacb0a03c83888ab24d4be16575aa4a7c` |

(downloaded 2026-10-10; catalogue page: Visible Earth record 73826, which now redirects to
<https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-topography-bathymetry/>).
It was only resized (Lanczos, 2048 x 1024) and recompressed as JPEG; nothing was painted,
cropped, shifted or recoloured.

## Orientation

The image is an equirectangular (plate carree) map: longitude -180 at the left edge, the prime
meridian in the middle, latitude +90 at the top. The viewer maps a point at geodetic latitude
`lat` and longitude `lon` to texture coordinates `u = (lon + 180) / 360`, `v = (lat + 90) / 180`
(`sim/chronoroute/viz/globe.py`), and `sim/tests/test_viz_globe.py` checks the result by
rendering markers at Greenwich, Chennai, New York and Sydney.

The image is a 2004 composite: clouds, snow and season do not follow the simulated date.
