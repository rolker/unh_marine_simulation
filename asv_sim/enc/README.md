# ENC cells for the charted-object collision (issue #113)

NOAA Electronic Navigational Charts, S-57, the two harbour-scale (usage band 5,
1:12000) cells that cover the Ocean Discovery Day demo area (Portsmouth Harbor,
lat 43.0537 to 43.0937, lon -70.7405 to -70.6695, the demo truth grid):

| Cell | Edition | Update | Issued | Covers |
|------|---------|--------|--------|--------|
| `US5PSMCC.000` | 4 | 0 | 2025-02-18 | lon -70.800 to -70.725, lat 43.05 to 43.125 |
| `US5PSMCD.000` + `US5PSMCD.001` | 5 | 1 | 2026-02-12 | lon -70.725 to -70.650, lat 43.05 to 43.125 |

Source: NOAA Office of Coast Survey, https://charts.noaa.gov/ENCs/ENCs.shtml
(copied from an ENC_ROOT downloaded in July 2026). The NOAA user agreement
(`NOAA_USERAGREEMENT.TXT`) permits redistribution without restriction. These
copies are a simulation fixture, not updated and not for navigation.

`asv_sim` reads them with GDAL's OGR S-57 driver (`asv_sim/charts.py`) when
`collision.enc_dir` points at this directory; the demo launch does. Point it at
another cell file or a directory of cells (flat, or one directory per cell as in
an ENC_ROOT) for another area; a directory holding cells more than half a degree
apart is refused. Cells of different scales that overlap would both be read:
give it the cells you want and no others.
