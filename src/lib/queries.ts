import type { AsyncDuckDBConnection } from '@duckdb/duckdb-wasm';
import type {
  Artist,
  ArtistBundle,
  ArtistFilters,
  ArtistPage,
  Facet,
  Manifest,
  Offering,
  PricePoint,
  Work
} from './types';

let DATA_BASE = ensureTrailingSlash(new URL('data/v1/', document.baseURI).toString());
let currentBuildId = '';

export async function resolveDataBase(): Promise<string> {
  const override = new URLSearchParams(location.search).get('data');
  if (override) {
    DATA_BASE = ensureTrailingSlash(new URL(override, location.href).toString());
    return DATA_BASE;
  }

  try {
    const configUrl = new URL('data-config.json', document.baseURI);
    configUrl.searchParams.set('t', String(Date.now()));
    const response = await fetch(configUrl, { cache: 'no-store' });
    if (response.ok) {
      const config = (await response.json()) as { base?: unknown };
      if (typeof config.base === 'string' && config.base) {
        DATA_BASE = ensureTrailingSlash(new URL(config.base, document.baseURI).toString());
        return DATA_BASE;
      }
    }
  } catch {
    // Same-origin data is the local-development fallback.
  }

  DATA_BASE = ensureTrailingSlash(new URL('data/v1/', document.baseURI).toString());
  return DATA_BASE;
}

export function getDataBase(): string {
  return DATA_BASE;
}

export async function loadManifest(): Promise<Manifest> {
  const manifestUrl = new URL('manifest.json', DATA_BASE);
  manifestUrl.searchParams.set('t', String(Date.now()));
  const response = await fetch(manifestUrl, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(
      `No data manifest found at ${DATA_BASE} (HTTP ${response.status}). Run the archiver and publish the data branch.`
    );
  }
  const manifest = (await response.json()) as Manifest;
  currentBuildId = String(manifest.build_id || manifest.generated_ts || manifest.generated_at || '');
  return manifest;
}

export async function prepareViews(
  conn: AsyncDuckDBConnection,
  manifest: Manifest
): Promise<void> {
  for (const table of ['artists', 'offerings', 'works', 'price_history']) {
    const files = manifest.tables?.[table]?.files ?? [];
    if (!files.length) {
      throw new Error(`Manifest has no files for table "${table}".`);
    }
    const urls = files.map((file) => {
      const url = new URL(file.path, DATA_BASE).toString();
      return sqlString(
        currentBuildId
          ? `${url}${url.includes('?') ? '&' : '?'}v=${encodeURIComponent(currentBuildId)}`
          : url
      );
    });
    await conn.query(
      `CREATE OR REPLACE VIEW v_${table} AS SELECT * FROM read_parquet([${urls.join(', ')}])`
    );
  }
  // The artist list is queried for every filter/sort/page action. Materializing
  // this small table avoids re-reading remote Parquet metadata on every query.
  await conn.query('CREATE OR REPLACE TABLE artists AS SELECT * FROM v_artists');
}

export async function queryFacets(
  conn: AsyncDuckDBConnection,
  manifest: Manifest
): Promise<{ sites: Facet[]; tags: Facet[] }> {
  const from = fromClause(manifest, 'artists');
  const siteRows = await runQuery<{ site: string; n: number | bigint }>(
    conn,
    `SELECT site, count(*) AS n FROM ${from} GROUP BY site ORDER BY n DESC`
  );
  const tagRows = await runQuery<{ tag: string; n: number | bigint }>(
    conn,
    `SELECT tag, count(*) AS n
     FROM ${from}, UNNEST(tags) AS u(tag)
     WHERE tags IS NOT NULL AND len(tags) > 0
     GROUP BY 1
     ORDER BY n DESC
     LIMIT 80`
  );
  return {
    sites: siteRows.map((row) => ({ value: row.site, count: Number(row.n) })),
    tags: tagRows.map((row) => ({ value: row.tag, count: Number(row.n) }))
  };
}

export async function queryArtists(
  conn: AsyncDuckDBConnection,
  manifest: Manifest,
  filters: ArtistFilters,
  page: number,
  pageSize: number
): Promise<ArtistPage> {
  const from = fromClause(manifest, 'artists');
  const where = buildWhere(filters);
  const order = orderClause(filters.sort);
  const offset = Math.max(0, (page - 1) * pageSize);

  const countRows = await runQuery<{ n: number | bigint }>(
    conn,
    `SELECT count(*) AS n FROM ${from}${where.sql}`,
    where.params
  );
  const total = Number(countRows[0]?.n ?? 0);

  const rows = await runQuery<Artist>(
    conn,
    `SELECT *
     FROM ${from}${where.sql}
     ORDER BY ${order}
     LIMIT ? OFFSET ?`,
    [...where.params, pageSize, offset]
  );
  return { rows, total };
}

export async function queryArtistBundle(
  conn: AsyncDuckDBConnection,
  manifest: Manifest,
  artistId: string
): Promise<ArtistBundle> {
  const artistsFrom = fromClause(manifest, 'artists');
  const offeringsFrom = fromClause(manifest, 'offerings');
  const worksFrom = fromClause(manifest, 'works');
  const historyFrom = fromClause(manifest, 'price_history');

  const artists = await runQuery<Artist>(
    conn,
    `SELECT * FROM ${artistsFrom} WHERE artist_id = ? LIMIT 1`,
    [artistId]
  );
  if (!artists.length) {
    throw new Error('That artist is not in the current database snapshot.');
  }

  const offerings = await runQuery<Offering>(
    conn,
    `SELECT * FROM ${offeringsFrom}
     WHERE artist_id = ?
     ORDER BY COALESCE(price_min_usd, price_usd) ASC NULLS LAST, title ASC`,
    [artistId]
  );
  const works = await runQuery<Work>(
    conn,
    `SELECT * FROM ${worksFrom}
     WHERE artist_id = ?
     ORDER BY created_at DESC NULLS LAST
     LIMIT 120`,
    [artistId]
  );
  const priceHistory = await runQuery<PricePoint>(
    conn,
    `SELECT * FROM ${historyFrom}
     WHERE artist_id = ?
     ORDER BY observed_at ASC`,
    [artistId]
  );

  return { artist: artists[0], offerings, works, priceHistory };
}

export async function queryArtistsByIds(
  conn: AsyncDuckDBConnection,
  manifest: Manifest,
  ids: string[]
): Promise<Artist[]> {
  if (!ids.length) return [];
  const from = fromClause(manifest, 'artists');
  const placeholders = ids.map(() => '?').join(', ');
  return runQuery<Artist>(
    conn,
    `SELECT * FROM ${from} WHERE artist_id IN (${placeholders})`,
    ids
  );
}

function fromClause(manifest: Manifest, table: string): string {
  const files = manifest.tables?.[table]?.files ?? [];
  if (!files.length) {
    throw new Error(`Manifest has no files for table "${table}".`);
  }
  return table === 'artists' ? 'artists' : `v_${table}`;
}

function ensureTrailingSlash(value: string): string {
  return value.endsWith('/') ? value : `${value}/`;
}

function buildWhere(filters: ArtistFilters): { sql: string; params: (string | number)[] } {
  const clauses: string[] = [];
  const params: (string | number)[] = [];

  const search = filters.search.trim();
  if (search) {
    clauses.push('search_text LIKE ?');
    params.push(`%${search.normalize('NFKC').toLowerCase()}%`);
  }
  if (filters.site) {
    clauses.push('site = ?');
    params.push(filters.site);
  }
  if (filters.tag) {
    clauses.push('list_contains(tags, ?)');
    params.push(filters.tag);
  }
  if (filters.nsfw === 'safe') {
    clauses.push('(nsfw IS NULL OR nsfw = false)');
  } else if (filters.nsfw === 'nsfw') {
    clauses.push('nsfw = true');
  }
  if (filters.accepts === 'yes') {
    clauses.push('accepts_commissions = true');
  } else if (filters.accepts === 'no') {
    clauses.push('accepts_commissions = false');
  }
  const minPrice = Number(filters.minPrice);
  if (filters.minPrice && Number.isFinite(minPrice)) {
    clauses.push('COALESCE(price_min_usd, price_max_usd) >= ?');
    params.push(minPrice);
  }
  const maxPrice = Number(filters.maxPrice);
  if (filters.maxPrice && Number.isFinite(maxPrice)) {
    clauses.push('COALESCE(price_min_usd, price_max_usd) <= ?');
    params.push(maxPrice);
  }

  return {
    sql: clauses.length ? ` WHERE ${clauses.join(' AND ')}` : '',
    params
  };
}

function orderClause(sort: ArtistFilters['sort']): string {
  switch (sort) {
    case 'price_desc':
      return 'COALESCE(price_max_usd, price_min_usd) DESC NULLS LAST, lower(handle) ASC';
    case 'updated':
      return 'last_updated DESC NULLS LAST, lower(handle) ASC';
    case 'works':
      return 'works_count DESC NULLS LAST, lower(handle) ASC';
    case 'name':
      return 'lower(handle) ASC';
    case 'price_asc':
    default:
      return 'COALESCE(price_min_usd, price_max_usd) ASC NULLS LAST, lower(handle) ASC';
  }
}

async function runQuery<T>(
  conn: AsyncDuckDBConnection,
  sql: string,
  params: (string | number)[] = []
): Promise<T[]> {
  const statement = await conn.prepare(sql);
  const result = await statement.query(...params);
  return result.toArray().map((row: unknown) => {
    const candidate = row as { toJSON?: () => Record<string, unknown> };
    const value = typeof candidate.toJSON === 'function' ? candidate.toJSON() : candidate;
    return normalizeValue(value) as T;
  });
}

function normalizeValue(value: any): any {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.map(normalizeValue);
  if (typeof value !== 'object') return value;
  if (typeof value.toArray === 'function') return value.toArray().map(normalizeValue);
  if (typeof value.length === 'number' && typeof value.get === 'function') {
    return Array.from({ length: value.length }, (_, index) => normalizeValue(value.get(index)));
  }
  if (typeof value[Symbol.iterator] === 'function' && !(value instanceof Date)) {
    return Array.from(value, normalizeValue);
  }
  const keys = Object.keys(value);
  if (keys.length && keys.every((key) => /^\d+$/.test(key))) {
    return keys
      .sort((a, b) => Number(a) - Number(b))
      .map((key) => normalizeValue(value[key]));
  }
  const result: Record<string, any> = {};
  for (const key of keys) result[key] = normalizeValue(value[key]);
  return result;
}

function sqlString(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}
