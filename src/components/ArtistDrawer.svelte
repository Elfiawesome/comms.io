<script lang="ts">
  import type { Artist, Offering, PricePoint, Work } from '../lib/types';
  import { fmtCompact, fmtDate, fmtInt, fmtOriginal, fmtUsd, offeringPrice, siteLabel } from '../lib/format';
  import PriceChart from './PriceChart.svelte';

  export let artist: Artist | null = null;
  export let offerings: Offering[] = [];
  export let works: Work[] = [];
  export let priceHistory: PricePoint[] = [];
  export let loading = false;
  export let watched = false;
  export let onClose: () => void = () => {};
  export let onToggleWatch: (artist: Artist) => void = () => {};

  $: tags = artist?.tags || [];
  $: gallery = buildGallery(works, offerings);

  function buildGallery(workItems: Work[], offeringItems: Offering[]) {
    const seen = new Set<string>();
    const items: { src: string; href: string | null | undefined; label: string }[] = [];
    for (const work of workItems) {
      if (!work.thumb_url || seen.has(work.thumb_url)) continue;
      seen.add(work.thumb_url);
      items.push({ src: work.thumb_url, href: work.source_url, label: work.title || 'Work' });
    }
    for (const offering of offeringItems) {
      if (!offering.cover_url || seen.has(offering.cover_url)) continue;
      seen.add(offering.cover_url);
      items.push({
        src: offering.cover_url,
        href: offering.source_url,
        label: offering.title || offering.kind || 'Commission'
      });
    }
    return items.slice(0, 32);
  }
</script>

<div class="backdrop" role="presentation" on:click={onClose}>
  <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    class="drawer"
    role="dialog"
    aria-modal="true"
    aria-label="Artist details"
    tabindex="-1"
    on:click|stopPropagation
    on:keydown|stopPropagation
  >
    <button class="close" aria-label="Close details" on:click={onClose}>Ã—</button>

    {#if artist}
      <header class="drawer-head">
        {#if artist.avatar_url}
          <img src={artist.avatar_url} alt="" referrerpolicy="no-referrer" />
        {:else}
          <div class="avatar-fallback">{(artist.display_name || artist.handle || '?').slice(0, 1).toUpperCase()}</div>
        {/if}
        <div class="identity">
          <div class="eyebrow">
            <span class={`badge site-${artist.site}`}>{siteLabel(artist.site)}</span>
            {#if artist.nsfw}<span class="badge nsfw">NSFW</span>{/if}
            {#if artist.accepts_commissions}<span class="badge open">Open</span>{/if}
          </div>
          <h2>{artist.display_name || artist.handle}</h2>
          <p>@{artist.handle}</p>
          <div class="head-actions">
            <button class="watch" class:active={watched} on:click={() => onToggleWatch(artist)}>
              {watched ? 'â˜… Watching' : 'â˜† Watch'}
            </button>
            {#if artist.profile_url}
              <a href={artist.profile_url} target="_blank" rel="noreferrer">Open profile â†—</a>
            {/if}
          </div>
        </div>
      </header>

      <section class="stats">
        <div><span>Works</span><strong>{fmtCompact(artist.works_count)}</strong></div>
        <div><span>Offerings</span><strong>{fmtInt(artist.offerings_count)}</strong></div>
        <div><span>Followers</span><strong>{fmtCompact(artist.followers_count)}</strong></div>
        <div><span>First seen</span><strong>{fmtDate(artist.first_seen)}</strong></div>
        <div><span>Updated</span><strong>{fmtDate(artist.last_updated)}</strong></div>
        <div><span>Status</span><strong>{artist.status || 'active'}</strong></div>
      </section>

      {#if tags.length}
        <div class="tags">
          {#each tags as tag}
            <span class="tag">{tag}</span>
          {/each}
        </div>
      {/if}

      {#if artist.bio}
        <section class="section">
          <h3>About</h3>
          <p class="bio">{artist.bio}</p>
        </section>
      {/if}

      <section class="section">
        <h3>Price observations</h3>
        <PriceChart points={priceHistory} />
      </section>

      <section class="section">
        <h3>Commission types <span class="count">{offerings.length}</span></h3>
        {#if offerings.length}
          <div class="offering-list">
            {#each offerings as offering}
              <a class="offering" href={offering.source_url || artist.profile_url} target="_blank" rel="noreferrer">
                {#if offering.cover_url}
                  <img
                    class="offering-cover"
                    src={offering.cover_url}
                    alt=""
                    loading="lazy"
                    referrerpolicy="no-referrer"
                    on:error={(event) => ((event.currentTarget as HTMLImageElement).style.visibility = 'hidden')}
                  />
                {:else}
                  <span class="offering-cover offering-cover-empty" aria-hidden="true"></span>
                {/if}
                <div class="offering-main">
                  <strong>{offering.title || offering.kind || 'Commission'}</strong>
                  <div class="offering-tags">
                    {#each (offering.tags || []).slice(0, 4) as tag}<span>{tag}</span>{/each}
                  </div>
                </div>
                <div class="offering-price">
                  <strong>{offeringPrice(offering)}</strong>
                  {#if offering.price_usd !== null && offering.price_usd !== undefined}
                    <span>{fmtUsd(offering.price_usd)}</span>
                  {/if}
                </div>
              </a>
            {/each}
          </div>
        {:else}
          <p class="empty">No commission types stored yet.</p>
        {/if}
      </section>

      <section class="section">
        <h3>Artworks <span class="count">{gallery.length}</span></h3>
        {#if gallery.length}
          <div class="work-grid">
            {#each gallery as item}
              <a href={item.href} target="_blank" rel="noreferrer" title={item.label}>
                <img
                  src={item.src}
                  alt={item.label}
                  loading="lazy"
                  referrerpolicy="no-referrer"
                  on:error={(event) => ((event.currentTarget as HTMLImageElement).style.visibility = 'hidden')}
                />
              </a>
            {/each}
          </div>
        {:else}
          <p class="empty">No artwork previews stored yet.</p>
        {/if}
      </section>
    {:else if loading}
      <p class="empty">Loading detailsâ€¦</p>
    {:else}
      <p class="empty">No artist selected.</p>
    {/if}
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 20;
    background: rgba(3, 7, 18, 0.68);
    backdrop-filter: blur(3px);
    display: flex;
    justify-content: flex-end;
  }
  .drawer {
    width: min(760px, 100vw);
    height: 100%;
    overflow-y: auto;
    background: var(--bg);
    border-left: 1px solid var(--border);
    padding: 26px;
    position: relative;
  }
  .close {
    position: sticky;
    top: 0;
    float: right;
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--text);
    border-radius: 10px;
    width: 36px;
    height: 36px;
    font-size: 22px;
    cursor: pointer;
    z-index: 2;
  }
  .drawer-head {
    display: flex;
    gap: 18px;
    align-items: flex-start;
    padding-right: 44px;
  }
  .drawer-head img,
  .avatar-fallback {
    width: 92px;
    height: 92px;
    border-radius: 20px;
    object-fit: cover;
    border: 1px solid var(--border);
    background: var(--panel);
    flex: none;
  }
  .avatar-fallback {
    display: grid;
    place-items: center;
    font-size: 36px;
    color: var(--accent);
    font-weight: 800;
  }
  .identity h2 {
    margin: 6px 0 2px;
    font-size: 26px;
    line-height: 1.15;
  }
  .identity p {
    margin: 0;
    color: var(--muted);
  }
  .eyebrow {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .badge {
    display: inline-flex;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    border: 1px solid var(--border);
    background: var(--panel);
  }
  .badge.site-skeb {
    color: #b8d8e8;
    border-color: rgba(56, 189, 248, 0.35);
  }
  .badge.site-crepe {
    color: #e8b8d0;
    border-color: rgba(244, 114, 182, 0.35);
  }
  .badge.nsfw {
    color: #f0a0a0;
    border-color: rgba(248, 113, 113, 0.4);
  }
  .badge.open {
    color: var(--text);
    border-color: rgba(74, 222, 128, 0.35);
  }
  .head-actions {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 12px;
    flex-wrap: wrap;
  }
  .head-actions a {
    color: var(--accent);
    font-size: 13px;
    text-decoration: none;
  }
  .watch {
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--text);
    padding: 7px 12px;
    border-radius: 9px;
    cursor: pointer;
    font-weight: 600;
  }
  .watch.active {
    color: #e8e6a8;
    border-color: rgba(251, 191, 36, 0.45);
  }
  .stats {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 8px;
    margin: 22px 0;
  }
  .stats div {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px;
  }
  .stats span {
    display: block;
    color: var(--muted);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 4px;
  }
  .stats strong {
    font-size: 13px;
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-bottom: 18px;
  }
  .tag {
    padding: 3px 8px;
    border-radius: 6px;
    background: var(--tag);
    color: #cbd5e1;
    font-size: 11px;
  }
  .section {
    margin-top: 24px;
  }
  .section h3 {
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin: 0 0 10px;
  }
  .count {
    color: var(--text);
    background: var(--panel-strong);
    border-radius: 999px;
    padding: 1px 7px;
    margin-left: 4px;
  }
  .bio {
    white-space: pre-line;
    line-height: 1.6;
    color: #cbd5e1;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px;
    margin: 0;
  }
  .offering-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .offering {
    display: flex;
    align-items: center;
    gap: 12px;
    text-decoration: none;
    color: var(--text);
    background: var(--panel);
    border: 1px solid var(--border);
    padding: 10px;
  }
  .offering:hover {
    border-color: var(--border-strong);
  }
  .offering-cover {
    width: 64px;
    height: 64px;
    object-fit: cover;
    border: 1px solid var(--border);
    background: #101010;
    flex: none;
  }
  .offering-cover-empty {
    display: block;
  }
  .offering-main {
    flex: 1;
    min-width: 0;
  }
  .offering-tags {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
    margin-top: 5px;
  }
  .offering-tags span {
    font-size: 10px;
    color: var(--muted);
    background: var(--tag);
    border-radius: 5px;
    padding: 1px 5px;
  }
  .offering-price {
    text-align: right;
    flex: none;
  }
  .offering-price strong {
    display: block;
    color: var(--text);
    font-size: 13px;
    white-space: nowrap;
  }
  .offering-price span {
    display: block;
    color: var(--muted);
    font-size: 11px;
    margin-top: 3px;
  }
  .work-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
    gap: 8px;
  }
  .work-grid a {
    display: block;
    aspect-ratio: 1;
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid var(--border);
    background: var(--panel);
  }
  .work-grid img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .work-placeholder {
    display: grid;
    place-items: center;
    height: 100%;
    font-size: 11px;
    color: var(--muted);
    padding: 8px;
    text-align: center;
  }
  .empty {
    color: var(--muted);
    font-size: 13px;
  }
  @media (max-width: 760px) {
    .drawer {
      padding: 18px;
    }
    .stats {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .drawer-head img,
    .avatar-fallback {
      width: 68px;
      height: 68px;
    }
    .identity h2 {
      font-size: 20px;
    }
  }
</style>

