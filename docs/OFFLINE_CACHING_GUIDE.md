# Universal Offline Caching Architecture

This guide details the persistent disk caching systems in `OSMExploration`, `IntersectionCategorizer`, and `GoogleMapsExploration`.

---

## 1. Why Default Caching?

Pedestrian navigation and spatial analysis require high-volume data retrieval from external services:
1. **OpenStreetMap Overpass API**: Querying pedestrian ways, crossings, and traffic signals across metropolitan bounding boxes.
2. **Nominatim Geocoding API**: Looking up street intersections and geographic coordinates. Subject to strict OpenStreetMap acceptable use policies (1 request per second max).
3. **Carto Tile Servers**: Rendering high-resolution basemaps (`voyager`, `dark_matter`, `positron`) across interactive map views.
4. **Google Maps Platform**: Elevation, Routes, Places, and Street View metadata.

To prevent redundant network requests, honor third-party rate limits, support completely offline field testing, and deliver near-instantaneous responses, **all network clients enable persistent disk caching by default (`use_cache=True`)**.

---

## 2. Cache Directory Layout

All cache artifacts are stored in organized subdirectories under dedicated `cache/` paths:

```
Capstone/
├── OSMExploration/
│   └── cache/
│       ├── nominatim/          # Geocoded addresses (geo_{hash}.json)
│       ├── overpass/           # Raw Overpass JSON responses
│       └── tiles/              # On-device Carto basemap tiles
│           └── voyager/
│               └── {z}/{x}/{y}.png
│
├── IntersectionCategorizer/
│   └── cache/
│       └── tiles/
│           └── voyager/
│               └── {z}/{x}/{y}.png
│
└── GoogleMapsExploration/
    └── cache/
        ├── routes/             # Google Routes API JSON responses
        ├── elevation/          # Elevation profiles along paths
        ├── places/             # Places API queries
        ├── streetview/         # Street View metadata
        └── osm/                # OSM loader fallback responses
```

> [!NOTE]
> All `cache/` directories are registered in their respective `.gitignore` files to prevent large binary and transient JSON assets from cluttering Git repositories.

---

## 3. Client Implementation Details

### A. Nominatim Geocoder Client ([`OSMExploration/src/clients/nominatim_client.py`](file:///C:/Code/Capstone/OSMExploration/src/clients/nominatim_client.py))
- **Default Parameters**: `use_cache: bool = True`, `force_refresh: bool = False`.
- **Key Generation**: Generates an MD5 digest of the normalized query string:
  ```python
  q_hash = hashlib.md5(query.strip().lower().encode("utf-8")).hexdigest()
  cache_file = self.cache_dir / f"geo_{q_hash}.json"
  ```
- **Behavior**: If `cache_file` exists and `force_refresh` is `False`, the result is loaded instantly from disk without hitting the Nominatim network server.

### B. Overpass API Client ([`OSMExploration/src/clients/overpass_client.py`](file:///C:/Code/Capstone/OSMExploration/src/clients/overpass_client.py))
- **Subfolder**: `cache/overpass/`.
- **Key Generation**: Bounding box coordinates and fixture names are hashed.
- **Mock Mode**: Supports deterministic offline test fixtures via `mock_mode=True`.

### C. Carto Tile Cache ([`OSMExploration/src/clients/carto_tile_cache.py`](file:///C:/Code/Capstone/OSMExploration/src/clients/carto_tile_cache.py))
- **Storage Pattern**: Standard OpenStreetMap Slippy Map tile directory structure:
  `cache/tiles/{style}/{z}/{x}/{y}.png`
- **Features**:
  - `get_tile(z, x, y, style)`: Retrieves tile from disk cache or fetches from Carto CDN and saves to disk.
  - `cache_bounding_box(bbox, min_zoom, max_zoom)`: Bulk pre-caches geographic areas for offline field demonstrations.

### D. Interactive Map Tile Proxy ([`IntersectionCategorizer/src/app.py`](file:///C:/Code/Capstone/IntersectionCategorizer/src/app.py))
- **Default Layer**: The Leaflet basemap is configured to use the local tile proxy layer by default:
  ```javascript
  const localCache = L.tileLayer('/api/tiles/voyager/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© CARTO, © OpenStreetMap contributors (Local Cache)'
  });
  localCache.addTo(map);
  ```
- **Tile Proxy Endpoint**: `/api/tiles/{style}/{z}/{x}/{y}.png` checks disk cache first, downloads missing tiles using `CARTO_API_KEY`, stores them locally, and returns the binary image stream.

---

## 4. Cache Management & CLI Commands

### Pre-Caching Basemap Tiles for Offline Demonstrations
In `IntersectionCategorizer`:
```bash
# Pre-cache zoom levels 13 and 14 for the entire City of Bend
python main.py --cache-tiles --cache-zooms 13 14
```

### Forcing a Refresh
To bypass the cache on any client, specify `use_cache=False` or `force_refresh=True`:
```python
# Nominatim fresh fetch:
client.geocode("SW Century Dr & SW Simpson Ave", force_refresh=True)

# Carto tile cache fresh fetch:
tile_cache.get_tile(z=14, x=2670, y=5953, force_refresh=True)
```
