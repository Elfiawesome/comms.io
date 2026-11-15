from __future__ import annotations

import pyarrow as pa

TABLE_SCHEMAS: dict[str, pa.Schema] = {
    "artists": pa.schema(
        [
            ("artist_id", pa.string()),
            ("site", pa.string()),
            ("site_user_id", pa.string()),
            ("handle", pa.string()),
            ("display_name", pa.string()),
            ("profile_url", pa.string()),
            ("avatar_url", pa.string()),
            ("header_url", pa.string()),
            ("bio", pa.string()),
            ("tags", pa.list_(pa.string())),
            ("nsfw", pa.bool_()),
            ("accepts_commissions", pa.bool_()),
            ("works_count", pa.int64()),
            ("followers_count", pa.int64()),
            ("rating", pa.float64()),
            ("offerings_count", pa.int64()),
            ("price_min_usd", pa.float64()),
            ("price_max_usd", pa.float64()),
            ("price_min_jpy", pa.int64()),
            ("price_max_jpy", pa.int64()),
            ("latest_thumbnails", pa.list_(pa.string())),
            ("first_seen", pa.float64()),
            ("last_updated", pa.float64()),
            ("last_seen", pa.float64()),
            ("status", pa.string()),
            ("search_text", pa.string()),
        ]
    ),
    "offerings": pa.schema(
        [
            ("offering_id", pa.string()),
            ("artist_id", pa.string()),
            ("site", pa.string()),
            ("handle", pa.string()),
            ("title", pa.string()),
            ("kind", pa.string()),
            ("description", pa.string()),
            ("price_min", pa.int64()),
            ("price_max", pa.int64()),
            ("currency", pa.string()),
            ("price_usd", pa.float64()),
            ("price_min_usd", pa.float64()),
            ("price_max_usd", pa.float64()),
            ("cover_url", pa.string()),
            ("turnaround_days", pa.int64()),
            ("slots", pa.int64()),
            ("available", pa.bool_()),
            ("tags", pa.list_(pa.string())),
            ("source_url", pa.string()),
            ("first_seen", pa.float64()),
            ("last_updated", pa.float64()),
            ("active", pa.bool_()),
            ("search_text", pa.string()),
        ]
    ),
    "works": pa.schema(
        [
            ("work_id", pa.string()),
            ("artist_id", pa.string()),
            ("site", pa.string()),
            ("handle", pa.string()),
            ("title", pa.string()),
            ("thumb_url", pa.string()),
            ("image_urls", pa.list_(pa.string())),
            ("tags", pa.list_(pa.string())),
            ("created_at", pa.float64()),
            ("source_url", pa.string()),
            ("first_seen", pa.float64()),
            ("last_updated", pa.float64()),
        ]
    ),
    "price_history": pa.schema(
        [
            ("id", pa.int64()),
            ("offering_id", pa.string()),
            ("artist_id", pa.string()),
            ("amount", pa.int64()),
            ("currency", pa.string()),
            ("amount_usd", pa.float64()),
            ("observed_at", pa.float64()),
        ]
    ),
}

TABLE_ORDER = ("artists", "offerings", "works", "price_history")

QUERY_HINTS = {
    "artists": {
        "list_columns": [
            "artist_id",
            "site",
            "handle",
            "display_name",
            "avatar_url",
            "tags",
            "nsfw",
            "works_count",
            "offerings_count",
            "price_min_usd",
            "price_max_usd",
            "last_updated",
        ],
        "search_column": "search_text",
        "sort_columns": {
            "price": ["price_min_usd", "price_max_usd"],
            "updated": "last_updated",
            "works": "works_count",
            "name": "handle",
        },
    },
    "offerings": {
        "list_columns": [
            "offering_id",
            "artist_id",
            "site",
            "handle",
            "title",
            "kind",
            "price_min",
            "price_max",
            "currency",
            "price_min_usd",
            "price_max_usd",
            "available",
            "tags",
        ],
        "search_column": "search_text",
    },
}
