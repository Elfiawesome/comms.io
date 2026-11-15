<script lang="ts">
  import { onMount } from 'svelte';
  import type { AsyncDuckDBConnection } from '@duckdb/duckdb-wasm';
  import ArtistTable from './components/ArtistTable.svelte';
  import ArtistDrawer from './components/ArtistDrawer.svelte';
  import { getDuckSession } from './lib/duckdb';
  import {
    loadManifest,
    queryArtistBundle,
    queryArtists,
    queryArtistsByIds,
    queryFacets
  } from './lib/queries';
  import type {
    Artist,
    ArtistBundle,
    ArtistFilters,
    Facet,
    Manifest,
    Offering,
    PricePoint,
    SortKey,
    Work
  } from './lib/types';
  import { fmtDate, priceRange, siteLabel } from './lib/format';
  import {
    listNames,
    loadLists,
    loadWatchlist,
    mergeWatchlist,
    moveWatchlistEntry,
    saveLists,
    saveWatchlist,
    toggleWatchlist,
    watchEntryFromArtist,
    type WatchEntry
  } from './lib/watchlist';

  const defaultFilters = (): ArtistFilters => ({
    search: '',
    site: '',
    tag: '',
    nsfw: 'all',
    accepts: 'all',
    minPrice: '',
    maxPrice: '',
    sort: 'price_asc'
  });

  let manifest: Manifest | null = null;
  let conn: AsyncDuckDBConnection | null = null;
  let status = 'Starting DuckDB…';
  let error = '';
  let loading = true;
  let artists: Artist[] = [];
  let total = 0;
  let page = 1;
  let pageSize = 50;
  let filters: ArtistFilters = defaultFilters();
  let sites: Facet[] = [];
  let tags: Facet[] = [];
  let viewMode: 'browse' | 'watchlist' = 'browse';
  let watchlist: WatchEntry[] = [];
  let watchIds = new Set<string>();
  let customLists: string[] = [];
  let activeList = 'Watchlist';
  let drawerOpen = false;
  let selected: Artist | null = null;
  let selectedOfferings: Offering[] = [];
  let selectedWorks: Work[] = [];
  let selectedPrices: PricePoint[] = [];
  let selectedLoading = false;
  let fileInput: HTMLInputElement | null = null;
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  $: siteOptions = sites.length
    ? sites
    : Array.from(new Set(artists.map((artist) => artist.site))).map((value) => ({ value, count: 0 }));
  $: tagOptions = tags;
  $: manifestDate = manifest ? fmtDate(Date.parse(manifest.generated_at) / 1000) : '—';
  $: listOptions = listNames(watchlist, customLists);
  $: visibleWatchlist =
    activeList === 'All' ? watchlist : watchlist.filter((entry) => (entry.list || 'Watchlist') === activeList);

  onMount(() => {
    window.addEventListener('hashchange', handleHash);
    void init();
    return () => window.removeEventListener('hashchange', handleHash);
  });

  async function init(): Promise<void> {
    watchlist = loadWatchlist();
    customLists = loadLists();
    watchIds = new Set(watchlist.map((entry) => entry.artist_id));
    readUrl();
    try {
      const session = await getDuckSession();
      conn = session.conn;
      status = 'Loading manifest…';
      manifest = await loadManifest();
      status = 'Building facets…';
      const facets = await queryFacets(conn, manifest);
      sites = facets.sites;
      tags = facets.tags;
      await loadArtists();
      status = '';
      await handleHash();
    } catch (err) {
      error = errorMessage(err);
      loading = false;
      status = '';
    }
  }

  async function loadArtists(): Promise<void> {
    if (!conn || !manifest) return;
    loading = true;
    error = '';
    try {
      const result = await queryArtists(conn, manifest, filters, page, pageSize);
      artists = result.rows;
      total = result.total;
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }

  async function loadDetails(artistId: string): Promise<void> {
    if (!conn || !manifest) return;
    selectedLoading = true;
    try {
      const bundle: ArtistBundle = await queryArtistBundle(conn, manifest, artistId);
      selected = bundle.artist;
      selectedOfferings = bundle.offerings;
      selectedWorks = bundle.works;
      selectedPrices = bundle.priceHistory;
      error = '';
    } catch (err) {
      error = errorMessage(err);
    } finally {
      selectedLoading = false;
    }
  }

  function selectArtist(artist: Artist): void {
    selected = artist;
    selectedOfferings = [];
    selectedWorks = [];
    selectedPrices = [];
    drawerOpen = true;
    history.replaceState(null, '', `${location.pathname}${location.search}#artist/${encodeURIComponent(artist.artist_id)}`);
    void loadDetails(artist.artist_id);
  }

  async function openArtistById(artistId: string): Promise<void> {
    if (!artistId) return;
    selected = selected?.artist_id === artistId ? selected : null;
    drawerOpen = true;
    await loadDetails(artistId);
  }

  async function handleHash(): Promise<void> {
    const prefix = '#artist/';
    if (!location.hash.startsWith(prefix)) {
      drawerOpen = false;
      selected = null;
      return;
    }
    const artistId = decodeURIComponent(location.hash.slice(prefix.length));
    if (!conn || !manifest) return;
    await openArtistById(artistId);
  }

  function closeDrawer(): void {
    drawerOpen = false;
    selected = null;
    history.replaceState(null, '', `${location.pathname}${location.search}`);
  }

  function applyFilters(): void {
    page = 1;
    syncUrl();
    void loadArtists();
  }

  function onSearchInput(): void {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applyFilters, 260);
  }

  function resetFilters(): void {
    filters = defaultFilters();
    page = 1;
    syncUrl();
    void loadArtists();
  }

  function goPage(nextPage: number): void {
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (nextPage < 1 || nextPage > totalPages) return;
    page = nextPage;
    syncUrl();
    void loadArtists();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function syncUrl(): void {
    const params = new URLSearchParams();
    if (filters.search) params.set('q', filters.search);
    if (filters.site) params.set('site', filters.site);
    if (filters.tag) params.set('tag', filters.tag);
    if (filters.nsfw !== 'all') params.set('nsfw', filters.nsfw);
    if (filters.accepts !== 'all') params.set('accepts', filters.accepts);
    if (filters.minPrice) params.set('min', filters.minPrice);
    if (filters.maxPrice) params.set('max', filters.maxPrice);
    if (filters.sort !== 'price_asc') params.set('sort', filters.sort);
    if (page > 1) params.set('page', String(page));
    const query = params.toString();
    history.replaceState(null, '', `${location.pathname}${query ? `?${query}` : ''}${location.hash}`);
  }

  function readUrl(): void {
    const params = new URLSearchParams(location.search);
    filters.search = params.get('q') || '';
    filters.site = params.get('site') || '';
    filters.tag = params.get('tag') || '';
    filters.nsfw = params.get('nsfw') || 'all';
    filters.accepts = params.get('accepts') || 'all';
    filters.minPrice = params.get('min') || '';
    filters.maxPrice = params.get('max') || '';
    const sort = params.get('sort');
    filters.sort = isSort(sort) ? sort : 'price_asc';
    page = Math.max(1, Number(params.get('page')) || 1);
  }

  function toggleWatch(artist: Artist): void {
    const targetList = activeList === 'All' ? 'Watchlist' : activeList;
    watchlist = toggleWatchlist(watchlist, artist, targetList);
    saveWatchlist(watchlist);
    watchIds = new Set(watchlist.map((entry) => entry.artist_id));
  }

  function removeWatch(entry: WatchEntry): void {
    watchlist = watchlist.filter((item) => item.artist_id !== entry.artist_id);
    saveWatchlist(watchlist);
    watchIds = new Set(watchlist.map((item) => item.artist_id));
  }

  function moveWatch(entry: WatchEntry, list: string): void {
    watchlist = moveWatchlistEntry(watchlist, entry.artist_id, list);
    saveWatchlist(watchlist);
  }

  function createList(): void {
    const name = window.prompt('New list name', 'Favorites')?.trim();
    if (!name) return;
    if (!listOptions.includes(name)) {
      customLists = [...customLists, name];
      saveLists(customLists);
    }
    activeList = name;
  }

  function openWatchEntry(entry: WatchEntry): void {
    const fallback: Artist = {
      artist_id: entry.artist_id,
      site: entry.site,
      handle: entry.handle,
      display_name: entry.display_name,
      avatar_url: entry.avatar_url,
      tags: entry.tags,
      price_min_usd: entry.price_min_usd,
      price_max_usd: entry.price_max_usd
    };
    selected = fallback;
    selectedOfferings = [];
    selectedWorks = [];
    selectedPrices = [];
    drawerOpen = true;
    history.replaceState(null, '', `${location.pathname}${location.search}#artist/${encodeURIComponent(entry.artist_id)}`);
    void loadDetails(entry.artist_id);
  }

  async function refreshWatchlist(): Promise<void> {
    if (!conn || !manifest || !watchlist.length) return;
    try {
      const rows = await queryArtistsByIds(conn, manifest, watchlist.map((entry) => entry.artist_id));
      const byId = new Map(rows.map((artist) => [artist.artist_id, artist]));
      watchlist = watchlist.map((entry) => {
        const fresh = byId.get(entry.artist_id);
        return fresh
          ? {
              ...watchEntryFromArtist(fresh, entry.list || 'Watchlist'),
              added_at: entry.added_at,
              note: entry.note
            }
          : entry;
      });
      saveWatchlist(watchlist);
      watchIds = new Set(watchlist.map((entry) => entry.artist_id));
    } catch (err) {
      error = errorMessage(err);
    }
  }

  function exportWatchlist(): void {
    const blob = new Blob([JSON.stringify(watchlist, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'comms-watchlist.json';
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function importWatchlist(event: Event): Promise<void> {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      if (!Array.isArray(parsed)) throw new Error('Watchlist file must contain an array.');
      watchlist = mergeWatchlist(watchlist, parsed as WatchEntry[]);
      saveWatchlist(watchlist);
      watchIds = new Set(watchlist.map((entry) => entry.artist_id));
      error = '';
    } catch (err) {
      error = `Could not import watchlist: ${errorMessage(err)}`;
    } finally {
      input.value = '';
    }
  }

  function openImport(): void {
    fileInput?.click();
  }

  function isSort(value: string | null): value is SortKey {
    return value === 'price_asc' || value === 'price_desc' || value === 'updated' || value === 'works' || value === 'name';
  }

  function errorMessage(value: unknown): string {
    return value instanceof Error ? value.message : String(value);
  }
</script>

<svelte:head>
  <title>comms.io — commission archive</title>
</svelte:head>

<main class="app">
  <header class="topbar">
    <div class="brand">
      <h1>comms<span>.io</span></h1>
      <p>
        A static, searchable archive of artist commissions. Metadata is published to the
        <code>data</code> branch and queried in your browser; images stay on the original platforms.
      </p>
    </div>
    <nav class="view-tabs" aria-label="Views">
      <button class:active={viewMode === 'browse'} on:click={() => (viewMode = 'browse')}>Browse</button>
      <button class:active={viewMode === 'watchlist'} on:click={() => (viewMode = 'watchlist')}>
        Watchlist ({watchlist.length})
      </button>
    </nav>
  </header>

  {#if status}
    <div class="banner status">{status}</div>
  {/if}
  {#if error}
    <div class="banner error">
      <span>{error}</span>
      <button class="ghost" on:click={() => void init()}>Retry</button>
    </div>
  {/if}

  {#if viewMode === 'browse'}
    <section class="toolbar" aria-label="Filters">
      <div class="field search-field">
        <label for="search">Search</label>
        <input
          id="search"
          type="search"
          placeholder="handle, display name, tag, bio…"
          bind:value={filters.search}
          on:input={onSearchInput}
          on:keydown={(event) => event.key === 'Enter' && applyFilters()}
        />
      </div>
      <div class="field">
        <label for="site">Site</label>
        <select id="site" bind:value={filters.site} on:change={applyFilters}>
          <option value="">All sites</option>
          {#each siteOptions as option}
            <option value={option.value}>{siteLabel(option.value)} ({option.count})</option>
          {/each}
        </select>
      </div>
      <div class="field">
        <label for="sort">Sort</label>
        <select id="sort" bind:value={filters.sort} on:change={applyFilters}>
          <option value="price_asc">Price: low → high</option>
          <option value="price_desc">Price: high → low</option>
          <option value="updated">Recently updated</option>
          <option value="works">Most works</option>
          <option value="name">Name</option>
        </select>
      </div>
      <div class="field">
        <label for="nsfw">NSFW</label>
        <select id="nsfw" bind:value={filters.nsfw} on:change={applyFilters}>
          <option value="all">All</option>
          <option value="safe">Safe only</option>
          <option value="nsfw">NSFW only</option>
        </select>
      </div>
      <div class="field">
        <label for="accepts">Accepting</label>
        <select id="accepts" bind:value={filters.accepts} on:change={applyFilters}>
          <option value="all">All</option>
          <option value="yes">Open</option>
          <option value="no">Closed</option>
        </select>
      </div>
      <div class="toolbar-row">
        <div class="field">
          <label for="tag">Tag</label>
          <select id="tag" bind:value={filters.tag} on:change={applyFilters}>
            <option value="">All tags</option>
            {#each tagOptions as option}
              <option value={option.value}>{option.value} ({option.count})</option>
            {/each}
          </select>
        </div>
        <div class="field">
          <label for="min">Min USD</label>
          <input id="min" type="number" min="0" step="1" placeholder="0" bind:value={filters.minPrice} on:change={applyFilters} />
        </div>
        <div class="field">
          <label for="max">Max USD</label>
          <input id="max" type="number" min="0" step="1" placeholder="Any" bind:value={filters.maxPrice} on:change={applyFilters} />
        </div>
        <div class="field">
          <label for="page-size">Per page</label>
          <select
            id="page-size"
            bind:value={pageSize}
            on:change={() => {
              page = 1;
              syncUrl();
              void loadArtists();
            }}
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </div>
        <button class="ghost" on:click={resetFilters}>Reset filters</button>
      </div>
    </section>

    <div class="summary-row">
      <span>
        <strong>{total.toLocaleString()}</strong> artists
        {#if manifest}
          · snapshot {manifestDate}
        {/if}
      </span>
      <span>{loading ? 'Querying…' : 'Metadata only — open a profile to view the source.'}</span>
    </div>

    <ArtistTable
      {artists}
      {total}
      {page}
      {pageSize}
      {loading}
      {watchIds}
      onSelect={selectArtist}
      onToggleWatch={toggleWatch}
      onPage={goPage}
    />
  {:else}
    <section class="watchlist-head">
      <div>
        <h2>Lists &amp; watchlist</h2>
        <p>Stored locally in this browser. Create named lists for different moods, then export everything as JSON.</p>
      </div>
      <div class="actions">
        <select class="list-filter" bind:value={activeList} aria-label="Filter by list">
          <option value="All">All lists ({watchlist.length})</option>
          {#each listOptions as list}
            <option value={list}>{list} ({watchlist.filter((entry) => (entry.list || 'Watchlist') === list).length})</option>
          {/each}
        </select>
        <button class="ghost" on:click={createList}>New list</button>
        <button class="ghost" on:click={() => void refreshWatchlist()} disabled={!watchlist.length}>Refresh prices</button>
        <button class="ghost" on:click={exportWatchlist} disabled={!watchlist.length}>Export JSON</button>
        <button class="ghost" on:click={openImport}>Import JSON</button>
        <input class="hidden-input" type="file" accept="application/json" bind:this={fileInput} on:change={importWatchlist} />
      </div>
    </section>

    {#if visibleWatchlist.length}
      <div class="watch-grid">
        {#each visibleWatchlist as entry (entry.artist_id)}
          <article class="watch-card">
            <button class="watch-main" on:click={() => openWatchEntry(entry)}>
              {#if entry.avatar_url}
                <img src={entry.avatar_url} alt="" loading="lazy" referrerpolicy="no-referrer" />
              {:else}
                <span class="avatar-fallback">{(entry.display_name || entry.handle || '?').slice(0, 1).toUpperCase()}</span>
              {/if}
              <span class="watch-body">
                <h3>{entry.display_name || entry.handle}</h3>
                <span class="handle">@{entry.handle} · {siteLabel(entry.site)}</span>
                <span class="price">{priceRange({
                  artist_id: entry.artist_id,
                  site: entry.site,
                  handle: entry.handle,
                  price_min_usd: entry.price_min_usd,
                  price_max_usd: entry.price_max_usd
                })}</span>
                <span class="meta">Added {fmtDate(entry.added_at)}</span>
              </span>
            </button>
            <select
              class="list-select"
              value={entry.list || 'Watchlist'}
              aria-label="Move to list"
              on:click|stopPropagation
              on:change={(event) => moveWatch(entry, (event.currentTarget as HTMLSelectElement).value)}
            >
              {#each listOptions as list}
                <option value={list}>{list}</option>
              {/each}
            </select>
            <button class="remove" aria-label="Remove from watchlist" on:click={() => removeWatch(entry)}>×</button>
          </article>
        {/each}
      </div>
    {:else}
      <div class="empty-panel">
        <strong>{activeList === 'All' ? 'No watched artists yet.' : `“${activeList}” is empty.`}</strong>
        Browse the archive and press the star next to an artist. Use the list selector on a saved card to move it between lists.
      </div>
    {/if}
  {/if}

  <footer>
    <span>comms.io · static archive · built from public commission pages</span>
    <span><a href="https://github.com/Elfiawesome/comms.io" target="_blank" rel="noreferrer">source</a> · metadata only</span>
  </footer>
</main>

{#if drawerOpen}
  <ArtistDrawer
    artist={selected}
    offerings={selectedOfferings}
    works={selectedWorks}
    priceHistory={selectedPrices}
    loading={selectedLoading}
    watched={selected ? watchIds.has(selected.artist_id) : false}
    onClose={closeDrawer}
    onToggleWatch={toggleWatch}
  />
{/if}

<style>
  code {
    font-size: 0.9em;
    color: var(--accent);
  }
  .hidden-input {
    display: none;
  }
</style>
