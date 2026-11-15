<script lang="ts">
  import type { Artist } from '../lib/types';
  import { fmtCompact, fmtDate, jpyRange, priceRange, siteLabel } from '../lib/format';

  export let artists: Artist[] = [];
  export let total = 0;
  export let page = 1;
  export let pageSize = 50;
  export let loading = false;
  export let watchIds = new Set<string>();
  export let onSelect: (artist: Artist) => void = () => {};
  export let onToggleWatch: (artist: Artist) => void = () => {};
  export let onPage: (page: number) => void = () => {};

  $: totalPages = Math.max(1, Math.ceil(total / pageSize));

  function initials(artist: Artist): string {
    const value = (artist.display_name || artist.handle || '?').trim();
    return value.slice(0, 1).toUpperCase();
  }
</script>

<div class="table-shell" class:loading>
  <table>
    <thead>
      <tr>
        <th class="star-col" aria-label="Watchlist"></th>
        <th>Artist</th>
        <th class="site-col">Site</th>
        <th class="tags-col">Tags</th>
        <th class="price-col">Price</th>
        <th class="num-col works-col">Works</th>
        <th class="updated-col">Updated</th>
      </tr>
    </thead>
    <tbody>
      {#if artists.length === 0 && !loading}
        <tr>
          <td colspan="7" class="empty">
            No artists match these filters yet. If the archive is new, run the crawler and publish the data branch.
          </td>
        </tr>
      {/if}
      {#each artists as artist (artist.artist_id)}
        <tr class="clickable" on:click={() => onSelect(artist)} on:keydown={(event) => event.key === 'Enter' && onSelect(artist)} tabindex="0">
          <td class="star-col">
            <button
              class="star"
              class:active={watchIds.has(artist.artist_id)}
              aria-label={watchIds.has(artist.artist_id) ? 'Remove from watchlist' : 'Add to watchlist'}
              on:click|stopPropagation={() => onToggleWatch(artist)}
            >
              {watchIds.has(artist.artist_id) ? '★' : '☆'}
            </button>
          </td>
          <td>
            <div class="artist-cell">
              {#if artist.avatar_url}
                <img src={artist.avatar_url} alt="" loading="lazy" referrerpolicy="no-referrer" />
              {:else}
                <span class="avatar-fallback">{initials(artist)}</span>
              {/if}
              <div class="artist-name">
                <strong>{artist.display_name || artist.handle}</strong>
                <span>@{artist.handle}</span>
              </div>
            </div>
          </td>
          <td class="site-col"><span class={`badge site-${artist.site}`}>{siteLabel(artist.site)}</span></td>
          <td class="tags-col">
            <div class="tags">
              {#each (artist.tags || []).slice(0, 3) as tag}
                <span class="tag">{tag}</span>
              {/each}
              {#if (artist.tags || []).length > 3}
                <span class="tag more">+{(artist.tags || []).length - 3}</span>
              {/if}
            </div>
          </td>
          <td class="price-col">
            <strong>{priceRange(artist)}</strong>
            {#if jpyRange(artist)}<span class="sub">{jpyRange(artist)}</span>{/if}
          </td>
          <td class="num-col works-col">{fmtCompact(artist.works_count)}</td>
          <td class="updated-col">{fmtDate(artist.last_updated)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if loading}
    <div class="table-loading">Querying archive…</div>
  {/if}
</div>

<div class="pager">
  <span>{total ? `${((page - 1) * pageSize + 1).toLocaleString()}–${Math.min(page * pageSize, total).toLocaleString()} of ${total.toLocaleString()}` : '0 results'}</span>
  <div class="pager-buttons">
    <button class="ghost" disabled={page <= 1} on:click={() => onPage(page - 1)}>Previous</button>
    <span>Page {page} / {totalPages}</span>
    <button class="ghost" disabled={page >= totalPages} on:click={() => onPage(page + 1)}>Next</button>
  </div>
</div>

<style>
  .table-shell {
    position: relative;
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: var(--panel);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    min-width: 840px;
  }
  th,
  td {
    padding: 12px 14px;
    border-bottom: 1px solid var(--border);
    text-align: left;
    vertical-align: middle;
  }
  th {
    position: sticky;
    top: 0;
    z-index: 2;
    background: var(--panel-strong);
    color: var(--muted);
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-weight: 700;
  }
  tbody tr:last-child td {
    border-bottom: 0;
  }
  tr.clickable {
    cursor: pointer;
    outline: none;
  }
  tr.clickable:hover td {
    background: var(--hover);
  }
  tr.clickable:focus-visible td {
    background: var(--hover);
    box-shadow: inset 0 0 0 1px var(--accent);
  }
  .star-col {
    width: 42px;
    text-align: center;
  }
  .star {
    border: 0;
    background: transparent;
    color: var(--muted);
    font-size: 20px;
    line-height: 1;
    cursor: pointer;
    padding: 2px;
  }
  .star:hover,
  .star.active {
    color: #fbbf24;
  }
  .artist-cell {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 190px;
  }
  .artist-cell img,
  .avatar-fallback {
    width: 38px;
    height: 38px;
    border-radius: 50%;
    object-fit: cover;
    background: var(--panel-strong);
    border: 1px solid var(--border);
    flex: none;
  }
  .avatar-fallback {
    display: grid;
    place-items: center;
    color: var(--accent);
    font-weight: 700;
  }
  .artist-name {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .artist-name strong {
    color: var(--text);
    font-size: 14px;
  }
  .artist-name span {
    color: var(--muted);
    font-size: 12px;
  }
  .badge {
    display: inline-flex;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    border: 1px solid var(--border);
    background: var(--panel-strong);
  }
  .badge.site-skeb {
    color: #7dd3fc;
    border-color: rgba(56, 189, 248, 0.35);
  }
  .badge.site-crepe {
    color: #f9a8d4;
    border-color: rgba(244, 114, 182, 0.35);
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    max-width: 260px;
  }
  .tag {
    padding: 2px 7px;
    border-radius: 6px;
    background: var(--tag);
    color: #cbd5e1;
    font-size: 11px;
    white-space: nowrap;
  }
  .tag.more {
    color: var(--muted);
  }
  .price-col strong {
    display: block;
    color: #86efac;
    font-size: 13px;
    white-space: nowrap;
  }
  .sub {
    display: block;
    color: var(--muted);
    font-size: 11px;
    margin-top: 2px;
    white-space: nowrap;
  }
  .num-col {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .updated-col {
    color: var(--muted);
    font-size: 12px;
    white-space: nowrap;
  }
  .empty {
    padding: 38px 18px;
    text-align: center;
    color: var(--muted);
  }
  .table-loading {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    background: rgba(8, 13, 24, 0.55);
    color: var(--muted);
    backdrop-filter: blur(1px);
  }
  .pager {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 12px 2px 0;
    color: var(--muted);
    font-size: 12px;
    flex-wrap: wrap;
  }
  .pager-buttons {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  @media (max-width: 900px) {
    .tags-col,
    .works-col,
    .updated-col {
      display: none;
    }
    table {
      min-width: 560px;
    }
  }
</style>
