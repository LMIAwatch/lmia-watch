import { describe, expect, it } from "vitest";
import { MINIMAP_H, MINIMAP_W, tileFrame, tilePoint } from "../src/minimap";

describe("mini map tiles", () => {
  it("places the centroid at the centre of the frame", () => {
    // Squamish, BC (the V0N fixture): tile 11/325/700 at zoom 11.
    const lat = 49.7, lon = -123.15;
    const p = tilePoint(lat, lon, 11);
    expect(Math.floor(p.x)).toBe(323);
    expect(Math.floor(p.y)).toBeGreaterThan(690);
    expect(Math.floor(p.y)).toBeLessThan(705);
    const tiles = tileFrame(lat, lon);
    expect(tiles.length).toBeGreaterThanOrEqual(2);
    expect(tiles.length).toBeLessThanOrEqual(6);
    for (const t of tiles) {
      expect(t.url).toMatch(/^https:\/\/tile\.openstreetmap\.org\/11\/\d+\/\d+\.png$/);
      // Every tile overlaps the frame.
      expect(t.left).toBeGreaterThan(-256);
      expect(t.left).toBeLessThan(MINIMAP_W);
      expect(t.top).toBeGreaterThan(-256);
      expect(t.top).toBeLessThan(MINIMAP_H);
    }
    // The tile that holds the point covers the frame's centre pixel.
    const centre = tiles.find((t) => t.left <= MINIMAP_W / 2 && t.left + 256 > MINIMAP_W / 2 && t.top <= MINIMAP_H / 2 && t.top + 256 > MINIMAP_H / 2);
    expect(centre?.url).toContain(`/11/${Math.floor(p.x)}/${Math.floor(p.y)}.png`);
  });

  it("never asks for a tile row outside the world", () => {
    const tiles = tileFrame(85, 0);
    for (const t of tiles) expect(Number(t.url.split("/").at(-1)!.replace(".png", ""))).toBeGreaterThanOrEqual(0);
  });
});
