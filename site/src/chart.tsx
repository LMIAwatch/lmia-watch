// Charts drawn on the server, for the trends pages. The marks (bars, lines,
// gridlines) sit in an inline SVG that stretches to the plot's width
// (preserveAspectRatio="none", strokes held at a fixed width by
// vector-effect), and the words (axis labels, marker numbers) are HTML placed
// by percentage. An SVG scaled to the page would scale its text with it, so a
// 12 px label would read at 6 px on a phone; HTML text keeps its size at any
// width. Colours come from custom properties in the stylesheet, so the charts
// follow the light and dark themes. No script runs: hovering a bar shows its
// SVG <title>, and every figure is in the table under the chart.

import { raw } from "hono/html";
import type { FC } from "hono/jsx";

const W = 1000;
const H = 100;
const DAY = 86_400_000;

// Position on a time axis measured in quarters: 2024-01-01 is 2024 * 4,
// 2024-04-01 one more, and a day inside a quarter falls in proportion. With
// `endOfDay` the position is the day's end, so a quarter's last day ends on
// the next whole number.
export function quarterPos(iso: string, endOfDay = false): number {
  const y = +iso.slice(0, 4);
  const m = +iso.slice(5, 7);
  const d = +iso.slice(8, 10);
  const q = Math.floor((m - 1) / 3);
  const start = Date.UTC(y, q * 3, 1);
  const end = Date.UTC(y, q * 3 + 3, 1);
  return y * 4 + q + (Date.UTC(y, m - 1, d) + (endOfDay ? DAY : 0) - start) / (end - start);
}

// Position on a time axis measured in days (the daily series).
export function dayPos(iso: string): number {
  return Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / DAY;
}

// Gridline values from zero to a round number at or above the largest value:
// steps of 1, 2 or 5 (and 2.5 from 25 up) times a power of ten, never a fraction.
export function niceTicks(max: number, count = 3): number[] {
  if (!(max > 0)) return [0, 1];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const factors = mag >= 10 ? [1, 2, 2.5, 5, 10] : [1, 2, 5, 10];
  const step = Math.max(1, (factors.find((f) => f * mag >= raw) ?? 10) * mag);
  const ticks: number[] = [];
  for (let v = 0; v < max + step; v += step) {
    ticks.push(v);
    if (v >= max) break;
  }
  return ticks;
}

export interface Bar {
  x0: number;
  x1: number;
  value: number;
  // A file covering several quarters, drawn lighter at its average per quarter.
  light?: boolean;
  title: string;
}

export interface LinePoint {
  x: number;
  value: number;
  title: string;
}

export interface Panel {
  title: string;
  bars?: Bar[];
  line?: LinePoint[];
  tone?: "approved" | "refused" | "pending";
}

export interface Marker {
  x: number;
  n: number;
}

export interface AxisLabel {
  x: number;
  text: string;
  // Hidden on a narrow screen, so every other year shows.
  minor?: boolean;
}

const f = (v: number) => (Math.round(v * 100) / 100).toString();

// Marker numbers stagger onto as many rows as it takes to keep them this far
// apart (a share of the plot's width; about 20 px on a phone).
const MARK_GAP = 4.5;

export function markerRows(markers: Marker[], domain: [number, number]): { m: Marker; left: number; row: number }[] {
  const last: number[] = [];
  return [...markers]
    .sort((a, b) => a.x - b.x)
    .map((m) => {
      const left = ((m.x - domain[0]) / (domain[1] - domain[0])) * 100;
      let row = last.findIndex((at) => left - at >= MARK_GAP);
      if (row < 0) row = last.length;
      last[row] = left;
      return { m, left, row };
    });
}

// Labels near either end are anchored to that end, so they stay over the plot.
function anchor(left: number): string | undefined {
  return left < 4 ? "x-start" : left > 96 ? "x-end" : undefined;
}

export function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// The inside of one panel's SVG, written as a string: a panel of the
// province view holds about 40 bars and a page 14 panels, and string
// building costs a fraction of rendering each element through JSX.
function marks(p: Panel, ticks: number[], top: number, grid: number[], markers: Marker[], sx: (x: number) => number, gap: number): string {
  const sy = (v: number) => H - (v / top) * H;
  const ns = ' vector-effect="non-scaling-stroke"';
  let out = "";
  for (const v of ticks.slice(1)) out += `<line class="grid" x1="0" x2="${W}" y1="${f(sy(v))}" y2="${f(sy(v))}"${ns}/>`;
  for (const x of grid) out += `<line class="grid grid-x" x1="${f(sx(x))}" x2="${f(sx(x))}" y1="0" y2="${H}"${ns}/>`;
  for (const b of p.bars ?? []) {
    if (!(b.value > 0)) continue;
    const x0 = sx(b.x0 + gap);
    const x1 = sx(b.x1 - gap);
    out += `<rect class="${b.light ? "bar bar-light" : "bar"}" x="${f(x0)}" y="${f(sy(b.value))}" width="${f(Math.max(0.5, x1 - x0))}" height="${f(H - sy(b.value))}"><title>${esc(b.title)}</title></rect>`;
  }
  for (const m of markers) out += `<line class="mark" x1="${f(sx(m.x))}" x2="${f(sx(m.x))}" y1="0" y2="${H}"${ns}/>`;
  const line = p.line ?? [];
  if (line.length > 1) out += `<polyline class="line" points="${line.map((pt) => `${f(sx(pt.x))},${f(sy(pt.value))}`).join(" ")}"${ns}/>`;
  // A zero-length line with round caps draws a round dot at any stretch.
  if (line.length <= 60) {
    for (const pt of line) {
      out += `<line class="dot" x1="${f(sx(pt.x))}" x2="${f(sx(pt.x))}" y1="${f(sy(pt.value))}" y2="${f(sy(pt.value))}"${ns}><title>${esc(pt.title)}</title></line>`;
    }
  }
  return out;
}

export const ChartStack: FC<{
  domain: [number, number];
  panels: Panel[];
  height: number;
  xLabels: AxisLabel[];
  grid?: number[];
  markers?: Marker[];
  fmt: (n: number) => string;
  aria: string;
  // One scale for every panel (the same unit side by side); otherwise each panel has its own.
  shared?: boolean;
}> = ({ domain, panels, height, xLabels, grid = [], markers = [], fmt, aria, shared }) => {
  const span = domain[1] - domain[0];
  const sx = (x: number) => ((x - domain[0]) / span) * W;
  const pct = (x: number) => ((x - domain[0]) / span) * 100;
  const peak = (p: Panel) => Math.max(0, ...(p.bars ?? []).map((b) => b.value), ...(p.line ?? []).map((pt) => pt.value));
  const sharedTicks = shared ? niceTicks(Math.max(...panels.map(peak))) : null;
  const placed = markerRows(markers, domain);
  const rows = placed.reduce((n, p) => Math.max(n, p.row + 1), 0);
  return (
    <div class="chart-stack">
      {rows ? (
        <div class="chart-row" aria-hidden="true">
          <span></span>
          <div class="chart-marks" style={`height:${rows * 1.6}em`}>
            {placed.map(({ m, left, row }) => (
              <span class={anchor(left)} style={`left:${f(left)}%;top:${row * 1.6}em`}>{m.n}</span>
            ))}
          </div>
        </div>
      ) : null}
      {panels.map((p) => {
        const ticks = sharedTicks ?? niceTicks(peak(p));
        const top = ticks[ticks.length - 1] || 1;
        const gap = Math.min(0.12, span / 400);
        return (
          <>
            <div class="chart-row">
              <span></span>
              <div class="chart-title">{p.title}</div>
            </div>
            <div class={`chart-row tone-${p.tone ?? "approved"}`}>
              <div class="chart-y" aria-hidden="true" style={`height:${height}px`}>
                {ticks.map((v) => <span style={`bottom:${f((v / top) * 100)}%`}>{fmt(v)}</span>)}
              </div>
              <div class="chart-plot" style={`height:${height}px`}>
                <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`${p.title}. ${aria}`} focusable="false"
                  >{raw(marks(p, ticks, top, grid, markers, sx, gap))}</svg>
              </div>
            </div>
          </>
        );
      })}
      <div class="chart-row" aria-hidden="true">
        <span></span>
        <div class="chart-x">
          {xLabels.map((l) => {
            const left = pct(l.x);
            return <span class={[anchor(left), l.minor ? "x-minor" : ""].filter(Boolean).join(" ") || undefined} style={`left:${f(left)}%`}>{l.text}</span>;
          })}
        </div>
      </div>
    </div>
  );
};

// One label per calendar year at the middle of the part of it inside the
// domain (quarter units), every other one marked minor; and a gridline at
// each year's start.
export function yearAxis(domain: [number, number]): { labels: AxisLabel[]; grid: number[] } {
  const first = Math.floor(domain[0] / 4);
  const last = Math.ceil(domain[1] / 4) - 1;
  const labels: AxisLabel[] = [];
  const grid: number[] = [];
  for (let y = first; y <= last; y++) {
    const a = Math.max(y * 4, domain[0]);
    const b = Math.min(y * 4 + 4, domain[1]);
    if (b <= a) continue;
    if (y * 4 > domain[0]) grid.push(y * 4);
    labels.push({ x: (a + b) / 2, text: String(y), minor: (last - y) % 2 === 1 });
  }
  return { labels, grid };
}
