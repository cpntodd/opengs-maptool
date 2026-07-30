<img width="350" height="350" alt="ogs-mt-logo" src="https://github.com/user-attachments/assets/d03854c8-c2e1-468f-9f8a-269f498d169c" />

# Open Grand Strategy - Map Tool

[![Debian](https://img.shields.io/badge/Debian-13%20(trixie)-A81D33?style=flat-square&logo=debian)](https://www.debian.org/)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-GPL--3.0--or--later-blue?style=flat-square)](LICENSE)
[![Discord](https://img.shields.io/badge/Discord-OpenGS-5865F2?style=flat-square&logo=discord)](https://discord.gg/6pRc9f6g6S)

The OpenGS Map Tool is a specialized utility for creating map data used in grand strategy games.
Province and territory maps form the backbone of these games, defining the geographical regions that players interact with.

---

## Features

- **Map Import** -- load real-world administrative boundaries from GeoJSON or MapInfo TAB files, auto-generate land/sea raster images from Natural Earth coastline data
- Generate and Export province maps and province data
- Generate and Export territory maps, territory data, and territory history
- Density image support for controlling province/territory distribution
- Lake support -- lakes are automatically detected and become individual provinces
- Exclude ocean from density influence per generation step
- Jagged borders -- optional natural-looking borders for land and ocean regions
- Terrain system -- import a terrain image to assign terrain types to provinces

## Showcase

Output territory Map:
![example](/example_output/territores.png)
Output Province Map:
![example2](/example_output/provinces.png)

---

## How to Install

### Debian 13 (trixie) / Linux

```bash
# System dependencies
sudo apt install python3-pyqt6 python3-numpy python3-pillow python3-scipy python3-tk python3-venv gdal-bin

# Clone and setup
git clone https://github.com/cpntodd/opengs-maptool.git
cd opengs-maptool
python3 -m venv --system-site-packages .venv
.venv/bin/pip install tkinterdnd2 cartopy

# Run
.venv/bin/python3 main.py
```

### Windows

1. Go to the "Releases" section on GitHub
2. Download and unpack `ogs_maptool.zip`
3. Run the executable

### Manual (pip)

```bash
git clone https://github.com/cpntodd/opengs-maptool.git
cd opengs-maptool
pip install -r requirements.txt
pip install cartopy
python main.py
```

---

## How to Use

### Map Import Tab (NEW)

The Map Import tab lets you import real-world GIS boundary data and generate matching land/sea images.

**Workflow:**
1. Click **Load Boundaries...** and select one or more `.tab` or `.geojson` files (multi-select with Ctrl+click)
2. Boundaries are auto-converted (TAB -> GeoJSON via GDAL) and auto-rasterized
3. Click **Generate Land Image** to create a coastline-based land/sea raster from Natural Earth data
4. Click **Send to Boundary Tab** to push the rasterized boundary to the pipeline
5. Use **Add Boundaries...** to append additional files to the current set

**Options:**
- **Width / Line** -- control output resolution and boundary line thickness
- **Clip to Land** (on by default) -- clips boundary polygons to the coastline so they don't extend into the ocean
- **Rasterize** -- re-render after changing settings

**Supported formats:** GeoJSON (`.geojson`, `.json`), MapInfo TAB (`.tab`)

**Auto-export:** Rendered boundary and land images are automatically saved to the `renders/` folder with the detected region name (e.g., `renders/Australia_boundary.png`).

### Land Image
The Land Image tab takes an image that specifies the ocean and lake areas of the map.
- **Ocean** must be RGB color (5, 20, 18)
- **Lakes** must be RGB color (0, 255, 0)
- Everything else is considered land

See examples in the folder `example_input`.

### Boundary Image
The Boundary Image tab defines the bounds that the provinces and territories need to adhere to.
Typical use would be borders for countries, states or other administrative units.
The boundary borders must be pure black, RGB (0, 0, 0), everything else will be ignored.

### Density Image
The Density Image tab allows you to import a density image that controls how provinces and territories are distributed.
Darker areas attract more seeds, resulting in smaller and denser regions. A normalize preset and an equator distribution preset are available.

The "Exclude Ocean" checkboxes on this tab let you ignore the density image for ocean regions during territory and/or province generation.

### Terrain Image
The Terrain Image tab allows you to import a terrain image that assigns terrain types to provinces after generation.
Each pixel color maps to a specific terrain type. The terrain is sampled at each province's center point and constrained by province type (land provinces only receive land terrains, ocean provinces only receive naval terrains, etc.).

**Land terrains** and their RGB colors:
| Terrain  | RGB |
|----------|-----|
| forest   | (89, 199, 85) |
| hills    | (248, 255, 153) |
| mountain | (157, 192, 208) |
| plains   | (255, 129, 66) |
| urban    | (120, 120, 120) |
| jungle   | (127, 191, 0) |
| marsh    | (76, 96, 35) |
| desert   | (255, 127, 0) |

**Naval terrains:**
| Terrain     | RGB |
|-------------|-----|
| deep_ocean  | (2, 38, 150) |
| shallow_sea | (56, 118, 217) |
| fjords      | (75, 162, 198) |

**Lake terrain:**
| Terrain | RGB |
|---------|-----|
| lakes   | (58, 91, 255) |

If no terrain image is provided, defaults are used: plains for land, deep_ocean for ocean, and lakes for lake provinces.

### Territory Image
The Territory Image tab generates the territory map, based on the Land and Boundary inputs.
NB! You don't need both inputs, but you need at least one.
Ex. A map without any ocean does not need to have input in the Land tab, but then there must be input in the Boundary tab, and vice versa.
Both input images must have the same dimensions/size for a good result.

Use the sliders to adjust the number of territories on land and ocean.
The density strength slider controls how strongly the density image influences seed placement.

Check "Jagged Land Borders" or "Jagged Ocean Borders" to produce natural-looking, irregular borders instead of straight Voronoi edges.

Territory map and the file containing territory information (id, rgb, type, coordinates) can be exported after generation.

### Province Image
The Province Image tab generates the province map, based on the generated territories.
NB! You need to generate territories before you can generate provinces.

Use the sliders to adjust the number of provinces on land and ocean.
Lakes are automatically detected and each connected lake region becomes its own province, assigned to the overlapping territory.

Check "Jagged Land Borders" or "Jagged Ocean Borders" to produce natural-looking, irregular borders instead of straight Voronoi edges.

Province map and the file containing province information (id, rgb, type, coordinates, terrain) can be exported after generation. The terrain field is included when a terrain image has been imported.
Territory history files (defining the belonging provinces per territory) can be exported after generation.

---

## Using Real-World Boundaries

The Map Import tab supports importing administrative boundary data from sources like [data.gov.au](https://data.gov.au). Australian Local Government Area (LGA) boundaries are available as free downloads:

- [WA Local Government Areas](https://data.gov.au/data/dataset/wa-local-government-areas-geoscape-administrative-boundaries)
- [National Geoscape Administrative Boundaries](https://data.gov.au/data/dataset/geoscape-administrative-boundaries)

Download the TAB or SHP format files, then load them in the Map Import tab. The tool will:
1. Convert to GeoJSON
2. Compute the geographic bounding box
3. Rasterize boundaries at your chosen resolution
4. Generate a matching land/sea image from Natural Earth coastline data
5. Auto-save everything to the `renders/` folder

---

## Contributions

Contributions can come in many forms and all are appreciated:
- Feedback
- Code improvements
- Added functionality

## Discord

Follow and/or support the project on [OpenGS Discord Server](https://discord.gg/6pRc9f6g6S)

## Delivered and maintained by

(c) 2026 [cpntodd](https://github.com/cpntodd) -- Licensed under GPL-3.0-or-later

<img width="350" height="350" alt="gsi-logo" src="https://github.com/user-attachments/assets/e7210566-7997-4d82-845e-48f249d439a0" />
