import type { Artist } from './types';

export interface WatchEntry {
  artist_id: string;
  site: string;
  handle: string;
  display_name?: string | null;
  avatar_url?: string | null;
  tags?: string[] | null;
  price_min_usd?: number | null;
  price_max_usd?: number | null;
  added_at: number;
  note?: string;
}

const STORAGE_KEY = 'comms.watchlist.v1';

export function loadWatchlist(): WatchEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is WatchEntry => Boolean(item && item.artist_id));
  } catch {
    return [];
  }
}

export function saveWatchlist(entries: WatchEntry[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Private browsing or a full quota should not break the UI.
  }
}

export function watchEntryFromArtist(artist: Artist): WatchEntry {
  return {
    artist_id: artist.artist_id,
    site: artist.site,
    handle: artist.handle,
    display_name: artist.display_name,
    avatar_url: artist.avatar_url,
    tags: artist.tags,
    price_min_usd: artist.price_min_usd === null || artist.price_min_usd === undefined ? null : Number(artist.price_min_usd),
    price_max_usd: artist.price_max_usd === null || artist.price_max_usd === undefined ? null : Number(artist.price_max_usd),
    added_at: Date.now() / 1000
  };
}

export function toggleWatchlist(entries: WatchEntry[], artist: Artist): WatchEntry[] {
  const exists = entries.some((entry) => entry.artist_id === artist.artist_id);
  if (exists) {
    return entries.filter((entry) => entry.artist_id !== artist.artist_id);
  }
  return [watchEntryFromArtist(artist), ...entries];
}

export function mergeWatchlist(entries: WatchEntry[], incoming: WatchEntry[]): WatchEntry[] {
  const merged = new Map<string, WatchEntry>();
  for (const entry of [...entries, ...incoming]) {
    if (!entry || !entry.artist_id) continue;
    const existing = merged.get(entry.artist_id);
    merged.set(entry.artist_id, existing ? { ...existing, ...entry } : entry);
  }
  return [...merged.values()];
}
