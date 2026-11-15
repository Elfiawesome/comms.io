<script lang="ts">
  import type { PricePoint } from '../lib/types';
  import { fmtDate, fmtUsd, toNum } from '../lib/format';

  export let points: PricePoint[] = [];

  const width = 640;
  const height = 220;
  const pad = { top: 18, right: 18, bottom: 28, left: 58 };

  $: usable = points
    .map((point) => ({
      ...point,
      xValue: toNum(point.observed_at),
      yValue: toNum(point.amount_usd)
    }))
    .filter((point) => point.xValue !== null && point.yValue !== null)
    .sort((a, b) => (a.xValue ?? 0) - (b.xValue ?? 0));

  $: minX = usable.length ? Math.min(...usable.map((point) => point.xValue ?? 0)) : 0;
  $: maxX = usable.length ? Math.max(...usable.map((point) => point.xValue ?? 0)) : 1;
  $: minY = usable.length ? Math.min(...usable.map((point) => point.yValue ?? 0)) : 0;
  $: maxY = usable.length ? Math.max(...usable.map((point) => point.yValue ?? 0)) : 1;
  $: spanX = maxX - minX || 1;
  $: spanY = maxY - minY || 1;
  $: innerWidth = width - pad.left - pad.right;
  $: innerHeight = height - pad.top - pad.bottom;
  $: x = (value: number) => pad.left + ((value - minX) / spanX) * innerWidth;
  $: y = (value: number) => pad.top + innerHeight - ((value - minY) / spanY) * innerHeight;
  $: linePath = usable
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${x(point.xValue ?? 0).toFixed(1)} ${y(point.yValue ?? 0).toFixed(1)}`)
    .join(' ');
  $: areaPath = usable.length
    ? `${linePath} L ${x(maxX).toFixed(1)} ${(pad.top + innerHeight).toFixed(1)} L ${x(minX).toFixed(1)} ${(pad.top + innerHeight).toFixed(1)} Z`
    : '';
  $: last = usable.at(-1);
</script>

{#if usable.length < 2}
  <div class="chart-empty">Not enough price observations yet.</div>
{:else}
  <div class="chart-wrap">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Price history chart">
      <defs>
        <linearGradient id="price-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.32" />
          <stop offset="100%" stop-color="#38bdf8" stop-opacity="0" />
        </linearGradient>
      </defs>
      {#each [0, 0.25, 0.5, 0.75, 1] as ratio}
        <line
          x1={pad.left}
          x2={width - pad.right}
          y1={pad.top + innerHeight * ratio}
          y2={pad.top + innerHeight * ratio}
          class="grid"
        />
        <text x={pad.left - 10} y={pad.top + innerHeight * ratio + 4} text-anchor="end" class="axis-label">
          {fmtUsd(maxY - spanY * ratio)}
        </text>
      {/each}
      <path d={areaPath} fill="url(#price-fill)" />
      <path d={linePath} class="line" />
      {#each usable as point}
        <circle cx={x(point.xValue ?? 0)} cy={y(point.yValue ?? 0)} r="3.5" class="dot">
          <title>{fmtDate(point.observed_at)} · {fmtUsd(point.amount_usd)}</title>
        </circle>
      {/each}
      <text x={pad.left} y={height - 6} class="axis-label">{fmtDate(minX)}</text>
      <text x={width - pad.right} y={height - 6} text-anchor="end" class="axis-label">{fmtDate(maxX)}</text>
    </svg>
    {#if last}
      <div class="chart-last">Latest: {fmtUsd(last.amount_usd)} · {fmtDate(last.observed_at)}</div>
    {/if}
  </div>
{/if}

<style>
  .chart-wrap {
    position: relative;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--panel);
    padding: 8px;
  }
  svg {
    display: block;
    width: 100%;
    height: auto;
  }
  .grid {
    stroke: rgba(148, 163, 184, 0.18);
    stroke-width: 1;
  }
  .axis-label {
    fill: var(--muted);
    font-size: 11px;
  }
  .line {
    fill: none;
    stroke: #38bdf8;
    stroke-width: 2.5;
    stroke-linejoin: round;
    stroke-linecap: round;
  }
  .dot {
    fill: #0b1120;
    stroke: #7dd3fc;
    stroke-width: 2;
  }
  .chart-last {
    padding: 4px 8px 2px;
    color: var(--muted);
    font-size: 12px;
  }
  .chart-empty {
    padding: 30px 16px;
    text-align: center;
    color: var(--muted);
    border: 1px dashed var(--border);
    border-radius: 12px;
  }
</style>
