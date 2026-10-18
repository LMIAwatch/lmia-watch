import type { FC } from "hono/jsx";

// A small static map for the profile's location card: a few OpenStreetMap
// tiles placed so the postal area's centroid sits at the centre, with a pin
// drawn in CSS. No script and no map library on the profile page; the tiles
// are the only outside request, the same host the map page already uses.

export const MINIMAP_ZOOM = 11;
export const MINIMAP_W = 360;
export const MINIMAP_H = 180;
const TILE = 256;

export type TilePlacement = { url: string; left: number; top: number };

// Web Mercator tile coordinates of a point at a zoom level.
export function tilePoint(lat: number, lon: number, zoom: number): { x: number; y: number } {
  const n = 2 ** zoom;
  const rad = (lat * Math.PI) / 180;
  return {
    x: ((lon + 180) / 360) * n,
    y: ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * n,
  };
}

// The tiles that cover a `width` by `height` window centred on the point, each
// with its pixel offset inside that window.
export function tileFrame(lat: number, lon: number, zoom = MINIMAP_ZOOM, width = MINIMAP_W, height = MINIMAP_H): TilePlacement[] {
  const n = 2 ** zoom;
  const p = tilePoint(lat, lon, zoom);
  const px = p.x * TILE;
  const py = p.y * TILE;
  const x0 = px - width / 2;
  const y0 = py - height / 2;
  const out: TilePlacement[] = [];
  for (let tx = Math.floor(x0 / TILE); tx * TILE < x0 + width; tx++) {
    for (let ty = Math.floor(y0 / TILE); ty * TILE < y0 + height; ty++) {
      if (ty < 0 || ty >= n) continue;
      const wrapped = ((tx % n) + n) % n;
      out.push({
        url: `https://tile.openstreetmap.org/${zoom}/${wrapped}/${ty}.png`,
        left: Math.round(tx * TILE - x0),
        top: Math.round(ty * TILE - y0),
      });
    }
  }
  return out;
}

export const MiniMap: FC<{ lat: number; lon: number; label: string }> = ({ lat, lon, label }) => {
  const tiles = tileFrame(lat, lon);
  return (
    <div class="minimap" role="img" aria-label={label}>
      <div class="minimap-tiles">
        {tiles.map((t) => (
          <img src={t.url} alt="" width={TILE} height={TILE} loading="lazy" decoding="async" style={`left:${t.left}px;top:${t.top}px`} />
        ))}
        <span class="minimap-pin" aria-hidden="true"></span>
      </div>
    </div>
  );
};
