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

  const emptyTiles = [0, 1, 2, 3];
  $: totalPages = Math.max(1, Math.ceil(total / pageSize));

  function thumbnails(artist: Artist): string[] {
    return (artist.latest_thumbnails || []).filter(Boolean).slice(0, 4);
  }

  function initials(artist: Artist): string {
    return (artist.display_name || artist.handle || '?').trim().slice(0, 1).toUpperCase();
  }
</script>

<div class="artist-grid">
  {#if artists.length === 0 && !loading}
    <div class="empty-grid">
      No artists match these filters. If the archive is new, run the crawler and publish the data branch.
    </div>
  {/if}

  {#each artists as artist (artist.artist_id)}
    <article class="artist-card">
      <div class="art-strip">
        {#if thumbnails(artist).length}
          {#each emptyTiles as index}
            {#if thumbnails(artist)[index]}
              <button class="art-tile" on:click={() => onSelect(artist)} aria-label={`Open ${artist.handle}`}>
                <img
                  src={thumbnails(artist)[index]}
                  alt=""
                  loading="lazy"
                  referrerpolicy="no-referrer"
                  on:error={(event) => ((event.currentTarget as HTMLImageElement).style.visibility = 'hidden')}
                />
              </button>
            {:else}
              <span class="art-empty" aria-hidden="true"></span>
            {/if}
          {/each}
        {:else}
          <button class="art-placeholder" on:click={() => onSelect(artist)}>
            NO PREVIEW
          </button>
        {/if}
        <button
          class="star"
          class:active={watchIds.has(artist.artist_id)}
          aria-label={watchIds.has(artist.artist_id) ? 'Remove from watchlist' : 'Add to watchlist'}
          on:click|stopPropagation={() => onToggleWatch(artist)}
        >
          {watchIds.has(artist.artist_id) ? '★' : '☆'}
        </button>
      </div>

      <button class="card-body" on:click={() => onSelect(artist)}>
        <span class="card-top">
          {#if artist.avatar_url}
            <img class="card-avatar" src={artist.avatar_url} alt="" loading="lazy" referrerpolicy="no-referrer" />
          {:else}
            <span class="card-avatar card-avatar-fallback">{initials(artist)}</span>
          {/if}
          <span class="card-name">
            <strong>{artist.display_name || artist.handle}</strong>
            <span>@{artist.handle}</span>
          </span>
          <span class={`site-badge site-${artist.site}`}>{siteLabel(artist.site)}</span>
        </span>

        <span class="card-metrics">
          <span class="card-price">{priceRange(artist)}</span>
          {#if jpyRange(artist)}<span>{jpyRange(artist)}</span>{/if}
          <span>{fmtCompact(artist.works_count)} works</span>
          <span>{fmtDate(artist.last_updated)}</span>
        </span>

        <span class="card-tags">
          {#each (artist.tags || []).slice(0, 4) as tag}
            <span class="card-tag">{tag}</span>
          {/each}
          {#if (artist.tags || []).length > 4}
            <span class="card-tag more">+{(artist.tags || []).length - 4}</span>
          {/if}
        </span>
      </button>
    </article>
  {/each}
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
  .artist-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px;
  }
  .artist-card {
    background: var(--panel);
    border: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .artist-card:hover {
    border-color: var(--border-strong);
  }
  .art-strip {
    position: relative;
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 1px;
    background: var(--border);
    border-bottom: 1px solid var(--border);
  }
  .art-tile,
  .art-empty,
  .art-placeholder {
    display: block;
    position: relative;
    aspect-ratio: 1 / 1;
    padding: 0;
    border: 0;
    background: #101010;
    overflow: hidden;
  }
  .art-tile {
    cursor: pointer;
  }
  .art-tile img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    filter: grayscale(0.18) contrast(1.05);
    transition: filter 160ms ease;
  }
  .art-tile:hover img {
    filter: none;
  }
  .art-placeholder {
    grid-column: 1 / -1;
    aspect-ratio: 4 / 1;
    color: var(--muted);
    font-size: 10px;
    letter-spacing: 0.18em;
    cursor: pointer;
  }
  .star {
    position: absolute;
    top: 7px;
    right: 7px;
    width: 30px;
    height: 30px;
    padding: 0;
    border: 1px solid rgba(255, 255, 255, 0.24);
    background: rgba(0, 0, 0, 0.72);
    color: var(--text);
    font-size: 17px;
    line-height: 1;
    cursor: pointer;
    z-index: 2;
  }
  .star:hover,
  .star.active {
    border-color: #d6d6a0;
    color: #e8e6a8;
  }
  .card-body {
    display: block;
    width: 100%;
    padding: 12px;
    border: 0;
    background: transparent;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  .card-top {
    display: flex;
    align-items: center;
    gap: 9px;
    min-width: 0;
  }
  .card-avatar {
    width: 36px;
    height: 36px;
    object-fit: cover;
    border: 1px solid var(--border);
    background: #101010;
    flex: none;
  }
  .card-avatar-fallback {
    display: grid;
    place-items: center;
    color: var(--muted);
    font-weight: 700;
  }
  .card-name {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    flex: 1;
  }
  .card-name strong {
    font-size: 14px;
    font-weight: 650;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .card-name span {
    color: var(--muted);
    font-size: 11px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .site-badge {
    flex: none;
    border: 1px solid var(--border-strong);
    padding: 2px 6px;
    color: var(--muted);
    font-size: 9px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }
  .site-badge.site-skeb {
    color: #b8d8e8;
  }
  .site-badge.site-crepe {
    color: #e8b8d0;
  }
  .card-metrics {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 12px;
    margin-top: 11px;
    padding-top: 9px;
    border-top: 1px solid var(--border);
    color: var(--muted);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
  .card-price {
    color: var(--text);
    font-weight: 700;
  }
  .card-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 9px;
  }
  .card-tag {
    border: 1px solid var(--border);
    padding: 1px 5px;
    color: var(--muted);
    font-size: 10px;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .card-tag.more {
    color: var(--text);
  }
  .empty-grid {
    grid-column: 1 / -1;
    border: 1px dashed var(--border);
    padding: 48px 20px;
    text-align: center;
    color: var(--muted);
    font-size: 13px;
  }
  .pager {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 14px 0 0;
    color: var(--muted);
    font-size: 11px;
    flex-wrap: wrap;
    font-variant-numeric: tabular-nums;
  }
  .pager-buttons {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  @media (max-width: 520px) {
    .artist-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
