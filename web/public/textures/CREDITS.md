# Earth textures: sources and credits

The globe's Earth images come from NASA. NASA imagery is generally not subject to copyright
in the United States and may be used with credit
(<https://www.nasa.gov/nasa-brand-center/images-and-media/>).

**Credit: NASA Earth Observatory.**

| File | Size | Source image | Credit |
|---|---|---|---|
| `earth-day-4096.jpg` | 4096 x 2048, 814,103 bytes | Blue Marble: Next Generation with Topography and Bathymetry, October 2004 (MODIS-based composite) | NASA Earth Observatory |
| `earth-day-2048.jpg` | 2048 x 1024, 247,132 bytes | same | same |
| `earth-night-4096.jpg` | 4096 x 2048, 289,776 bytes | Earth at Night (Black Marble) 2016, colour map, 3 km (Suomi NPP VIIRS composite) | NASA Earth Observatory |
| `earth-night-2048.jpg` | 2048 x 1024, 83,417 bytes | same | same |

Total: 1,434,428 bytes.

## Exact source files (downloaded 2026-10-10)

| Downloaded file | URL | Bytes | sha256 |
|---|---|---|---|
| `world.topo.bathy.200410.3x5400x2700.jpg` (5400 x 2700) | <https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73826/world.topo.bathy.200410.3x5400x2700.jpg> | 2,459,484 | `f9ad745c780281dbfdda9769f10b161aacb0a03c83888ab24d4be16575aa4a7c` |
| `BlackMarble_2016_3km.jpg` (13500 x 6750) | <https://eoimages.gsfc.nasa.gov/images/imagerecords/144000/144898/BlackMarble_2016_3km.jpg> | 8,106,233 | `230aac448ae68c358be433dd518888cccb3a85ccf66f7b44326441c324ad6725` |

Catalogue pages: Visible Earth records 73826 and 144898, which now redirect to
<https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-topography-bathymetry/>
and <https://science.nasa.gov/earth/earth-observatory/earth-at-night/maps/>.

## How the files here were made

Both sources are equirectangular (plate carrée) maps: longitude -180 at the left edge, the
prime meridian in the middle, latitude +90 at the top. They were only resized and recompressed;
nothing was painted, cropped, shifted or recoloured. Resizing used sharp 0.35.4 (libvips 8.18.6),
the version installed by this site's lockfile:

```js
sharp(src, { limitInputPixels: false })
  .resize(width, width / 2, { kernel: 'lanczos3', fit: 'fill' })
  .jpeg({ quality: q, mozjpeg: true, progressive: true, chromaSubsampling: '4:2:0' })
// width 4096 and 2048; q = 82 for the day map, 80 for the night map
```

The globe loads the 4096-pixel pair on desktop screens and the 2048-pixel pair on narrow or
touch screens and on GPUs whose maximum texture size is below 4096.

## How the globe uses them

* The day map is lit by the direction of the Sun at the simulated time (Astronomical Almanac
  low-precision formulas). The night map shows on the dark side; the two blend over about
  plus or minus 6 degrees of solar elevation.
* These are composites from 2004 and 2016, not live imagery. Clouds, snow and city lights do
  not change with the simulated date.
* Orientation is checked in `src/lib/orbit/frames.test.ts` (Greenwich, Chennai, New York and
  Sydney land on their own latitude and longitude on the map) and the mesh samples each map
  at the geodetic latitude of the WGS84 ellipsoid.
