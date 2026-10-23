# GTFS feeds

Public static schedules, trimmed to the box lat 33.975–34.090, lon −118.485 to −118.360 (Westwood / UCLA / Sawtelle / Palms / Culver City / Mar Vista). Raw downloads go in `raw/` (gitignored). Trimmed feeds (about 15 MB) are committed.

| Key | Agency | Feed URL | Downloaded | Service dates | Trimmed |
|---|---|---|---|---|---|
| `ccb` | Culver CityBus | https://web.culvercity.org/gtfs/gtfsexport.zip (linked from [culvercity.gov GIS data](https://www.culvercity.gov/City-Hall/City-Departments/IT/Download-GIS-Data)) | 2026-10-22 | 2026-07-13 – 2026-12-13 | 382 stops, 11 routes, 4,184 trips |
| `metro_bus` | LA Metro bus | https://gitlab.com/LACMTA/gtfs_bus/-/raw/master/gtfs_bus.zip | 2026-10-22 | 2026-06-07 – 2026-12-12 | 665 stops, 20 routes, 7,807 trips |
| `metro_rail` | LA Metro rail | https://gitlab.com/LACMTA/gtfs_rail/-/raw/master/gtfs_rail.zip | 2026-10-22 | 2026-10-22 – 2026-11-05 | 10 stops, 2 routes (D, E), 2,125 trips |
| `bbb` | Big Blue Bus | https://gtfs.bigbluebus.com/current.zip | 2026-10-22 | 2026-08-09 – 2026-12-12 | 634 stops, 16 routes, 3,152 trips |

The Metro rail feed covers only two weeks at a time. Re-download it before graded runs after Nov 5. The other feeds expire in mid-December.

Line names: Big Blue Bus `BB<n>`, Culver CityBus `CC<n>` (Rapid 6 is `CC6R`), Metro bus `M<n>`, Metro rail by line name (`E Line`).

## Refresh

```bash
curl -L -o data/gtfs/raw/metro_rail.zip https://gitlab.com/LACMTA/gtfs_rail/-/raw/master/gtfs_rail.zip
python -m bus_agent.gtfs trim
python -m pytest
```
