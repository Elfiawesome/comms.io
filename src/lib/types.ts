export type Num = number | bigint | null | undefined;

export interface ManifestFile {
  path: string;
  rows: number;
  bytes: number;
  sha256: string;
}

export interface ManifestTable {
  rows: number;
  partitions: number;
  files: ManifestFile[];
}

export interface Manifest {
  data_version: number;
  schema_version: number;
  format: string;
  generated_at: string;
  tables: Record<string, ManifestTable>;
  counts: Record<string, number>;
  currency: Record<string, number>;
  notes?: string;
}

export interface Artist {
  artist_id: string;
  site: string;
  site_user_id?: string | null;
  handle: string;
  display_name?: string | null;
  profile_url?: string | null;
  avatar_url?: string | null;
  header_url?: string | null;
  bio?: string | null;
  tags?: string[] | null;
  nsfw?: boolean | null;
  accepts_commissions?: boolean | null;
  works_count?: Num;
  followers_count?: Num;
  rating?: Num;
  offerings_count?: Num;
  price_min_usd?: Num;
  price_max_usd?: Num;
  price_min_jpy?: Num;
  price_max_jpy?: Num;
  first_seen?: Num;
  last_updated?: Num;
  last_seen?: Num;
  status?: string | null;
  search_text?: string | null;
}

export interface Offering {
  offering_id: string;
  artist_id: string;
  site: string;
  handle?: string | null;
  title?: string | null;
  kind?: string | null;
  description?: string | null;
  price_min?: Num;
  price_max?: Num;
  currency?: string | null;
  price_usd?: Num;
  price_min_usd?: Num;
  price_max_usd?: Num;
  turnaround_days?: Num;
  slots?: Num;
  available?: boolean | null;
  tags?: string[] | null;
  source_url?: string | null;
  first_seen?: Num;
  last_updated?: Num;
  active?: boolean | null;
}

export interface Work {
  work_id: string;
  artist_id: string;
  site: string;
  handle?: string | null;
  title?: string | null;
  thumb_url?: string | null;
  image_urls?: string[] | null;
  tags?: string[] | null;
  created_at?: Num;
  source_url?: string | null;
  first_seen?: Num;
  last_updated?: Num;
}

export interface PricePoint {
  id?: Num;
  offering_id: string;
  artist_id: string;
  amount?: Num;
  currency?: string | null;
  amount_usd?: Num;
  observed_at?: Num;
}

export interface Facet {
  value: string;
  count: number;
}

export type SortKey = 'price_asc' | 'price_desc' | 'updated' | 'works' | 'name';

export interface ArtistFilters {
  search: string;
  site: string;
  tag: string;
  nsfw: string;
  accepts: string;
  minPrice: string;
  maxPrice: string;
  sort: SortKey;
}

export interface ArtistPage {
  rows: Artist[];
  total: number;
}

export interface ArtistBundle {
  artist: Artist;
  offerings: Offering[];
  works: Work[];
  priceHistory: PricePoint[];
}
