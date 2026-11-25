# CADCraft → Blender interior workflow

Status: **first model built** (2026-11-10). `scripts/cadcraft_read.py` reads the live drawing and `scripts/build_sample_apartment.py` turns it into `models/sample_apartment.ifc`, which loads in Bonsai. The sample doesn't follow the conventions below yet, so the build script has small per-handle tables (`NOT_WALL`, `FURNITURE`, `ROOM_SEEDS`). Agreed conventions would replace them.

```bash
uv run python scripts/build_sample_apartment.py --live    # read CADCraft, write models/sample_apartment.ifc
```

How the plan is read: the wall linework is polygonized after closing each door gap between its two jambs. Faces are then sorted by thickness (2·area/perimeter): rooms, walls and openings. A swing arc hinged on an opening, whose radius matches the opening width, makes it a door; the other openings are windows. Details are in the script's docstring.

## Goal

The drawings are for interior design (interiorismo), not architecture. Plans are drawn in CADCraft, which offers AutoCAD-level 2D drafting that Blender and Bonsai don't have. Claude reads the drawing live over MCP and builds or updates a 3D model in Blender/Bonsai. When the drawing changes, Claude updates the model to match.

- **Clear interior dimensions are what matter.** Walls are not designed here. The sample drawing has its walls drawn, so the model uses them as drawn, and the room faces come out exact. A drawing with only room outlines would get thin wall shells built outward from each outline, which isn't implemented yet.
- **No save on every change.** Claude reads the open drawing through the app's control port. Saving is only for keeping versions.

## Why CADCraft

| | CADCraft | ClassCAD (classcad.ai) |
| --- | --- | --- |
| Kind | 2D drafting app (AutoCAD-style) | Headless 3D parametric engine for mechanical parts |
| License | MIT OR Apache-2.0, no account | Proprietary engine, needs a classcad.ch account |
| Formats | DXF, DWG, SVG, PNG, PDF | OFB, STL (free tier), STEP and GLB (paid) |
| MCP | Yes, bridges to the running app | Yes, local WASM engine |
| IFC / BIM | No | No |

Neither one does IFC. CADCraft fits better because the input is 2D plans. It's also local-only and has no account, which matches the project's privacy rules.

## Architecture

```
CADCraft app (--control 7979)
   │  JSON-lines control channel, loopback + session token
   ▼
cadcraft-cli mcp --connect 127.0.0.1:7979 --lazy     ← `cadcraft` in .mcp.json
   │  MCP (stdio)
   ▼
Claude Code ──── reads entities, areas, texts, renders
   │  MCP (stdio)
   ▼
mcp-for-blender ──▶ Blender + Bonsai (localhost:9876)  ← `blender` in .mcp.json
```

### An update round

1. The user edits the drawing in CADCraft, then tells Claude ("updated the kitchen"), ideally with the changed items selected.
2. Claude reads the drawing again: `query_entities`, with `selected: true` to read just the selection.
3. Claude compares it with the last read, using entity handles as IDs, and changes only the affected objects in Blender.
4. Claude checks the Blender result with `look`, next to a `render` of the plan.

The MCP server has **no change events**. Claude only re-reads when the user says something changed.

### CADCraft MCP tools used

| Tool | Use |
| --- | --- |
| `inspect_drawing` | Layers, blocks, counts, extents, selection |
| `query_entities {type?, layer?, selected?, window?}` | Entities with handles and geometry (default limit 500) |
| `execute` → `shapes` | Area, perimeter and centroid of closed outlines (room areas) |
| `execute` → `loops` | Closed loops from loose line/arc chains |
| `find_text` | Room names, block attributes, notes such as `h=2400` |
| `render` / `screenshot` | PNG of the drawing or window, for visual checks |

## Drawing conventions (proposal, not agreed yet)

| Layer / block | Draw | Becomes in Blender / Bonsai |
| --- | --- | --- |
| `ROOM` | One closed polyline per room, at the **clear interior** size | `IfcSpace` with floor and ceiling. Optional wall shells built outward |
| `ROOM` text | One room name inside each outline | Space name |
| `FURN` blocks (`SOFA_2200`, `BED_1600`, …) | Furniture as named blocks | `IfcFurniture`, placed and rotated as in the plan |
| `JOIN` blocks | Built-in joinery and kitchen runs | Casework |
| `DOOR`, `WIND` | Opening blocks or marks on an outline edge | Openings in that face |
| Text `h=…` | Height exceptions | Ceiling and joinery heights. Otherwise a project default from a config file |
| Everything else | Dimensions, hatches, notes | Ignored. Dimension text is only checked against the geometry |

Rules:
- **Draw to scale.** Claude measures the geometry and never reads dimension text as input.
- **Keep furniture data outside the model.** Data added in Bonsai, such as products and finishes, goes in a side file keyed by entity handle. That way, rebuilding the geometry doesn't lose it.

## The model: `models/sample_apartment.ifc`

Built by `scripts/build_sample_apartment.py` from the JSON that `scripts/cadcraft_read.py` writes. IFC4, metres, one storey ("Apartment"). x and y equal the drawing's coordinates divided by 1000, so any point in the model can be traced back to the drawing.

| Drawing | IFC |
| --- | --- |
| Room faces (thick faces of the wall linework) | `IfcSpace` from floor to ceiling, with `Qto_SpaceBaseQuantities` (net floor area, perimeter, height). The terrace is `EXTERNAL` |
| Each room | `IfcCovering` FLOORING (20 mm below 0: wood, tiles in the kitchen and bathroom, paving on the terrace) and CEILING (20 mm above the ceiling, none on the terrace) |
| Thin wall faces | `IfcWall`, full height |
| Opening faces | Their own `IfcWall` piece, with an `IfcOpeningElement` cutting from sill to head, filled by an `IfcDoor` or `IfcWindow` |
| Door swing arcs | Door leaves, closed, 40 mm, flush with the face where the hinge is. Two arcs make a double door |
| Opening with no arc, from a jamb pair | Entrance door, leaf in the middle of the wall |
| Furniture outlines (`FURNITURE` table) | `IfcFurniture`, or `IfcSanitaryTerminal` for the bath, WC and basin, extruded to an assumed height. The rug is an `IfcCovering` |
| Closed `Proy` outlines that aren't in the table | Red "Unclassified item" boxes 0.40 m high, so new items show up |

Assumed heights, set as constants at the top of the script: ceiling 2.70 m, door head 2.10 m, window sill 0.90 m, window head 2.30 m (also the head of the double door to the terrace).

The project pset `SampleApartment_Provenance` records the source drawing, the method and the assumed heights.

**Stable IDs.** GlobalIds are UUID5 hashes of keys: the entity handle for furniture, the room name for spaces, floors and ceilings, and the position rounded to 10–100 mm for walls and openings. Rebuilding after an edit keeps the IDs of everything that didn't change. A wall or opening that moves gets a new ID.

**Checks (2026-11-10).** Validation finds 0 issues and all 106 elements triangulate. The counts are 9 spaces, 21 walls (7 plus 14 opening pieces), 9 doors, 5 windows, 18 coverings plus the rug, 27 furniture items and 3 sanitary terminals. The top view in Bonsai matches the CADCraft plan.

**Known limits.**
- Walls show seams where each opening's wall piece meets the main wall.
- Door leaves are drawn closed. `OperationType` is generic (`SINGLE_SWING_LEFT`, or `DOUBLE_DOOR_SINGLE_SWING`) and doesn't follow the real hand of each door.
- The chairs block `78B` nests four chairs that MCP doesn't return. The script rebuilds them around table `732`, using offsets read once from a DXF copy.
- The kitchen counter `56D` is a single line. The script offsets it 600 mm into the room.

### Loading it in Bonsai

Through `execute_blender_code`:

```python
bpy.ops.bim.load_project(filepath=".../models/sample_apartment.ifc", should_start_fresh_session=True)
# then hide IfcSpace/*, IfcCovering/Ceiling* and IfcOpeningElement/* to see inside
```

A fresh session replaces the open project. Before loading, check `IfcStore.history` for unsaved IFC edits; the `.blend` only holds viewport state. The MCP server keeps running after the reload.

## Open items

1. **Edit-and-rebuild round trip.** Change the drawing, run `build_sample_apartment.py --live`, reload, and check that only the changed elements have new GlobalIds. This is the main promise of the workflow, and it's still untested.
2. **Heights.** Confirm the real ceiling, door and window heights. They are now assumptions.
3. **Drawing conventions.** Agree on the `ROOM` / `FURN` / `DOOR` layers, named blocks and room-name text (see above). They would replace `NOT_WALL`, `FURNITURE` and `ROOM_SEEDS`, so new drawings need no per-handle tables.
4. **Furniture guesses.** Confirm the items marked "?": the L-shape in bedroom 1, the 150×800 item ("radiator?"), the 700×1600 and 1600×700 units in the main bedroom, and the 2700×2000 "bed with side tables".
5. **Room-outline-only drawings.** Build thin wall shells outward from closed `ROOM` outlines, for drawings without walls.
6. **The CADCraft questions below:** handles, dimensions and the updater.

## Open questions

- **Handle stability, partly answered.** Handles survived deleting entities and saving to DWG: all 114 remaining entities kept their handles. Still to test: moving or stretching an entity, undo, and reopening the file. Anonymous block names (`*U…`) are renumbered on save, so they can't be used as IDs.
- **Dimensions over MCP.** The docs don't say how dimension entities come back from `query_entities`.
- **Updater.** The app updates itself (0.18.0 → 0.19.0 on first launch, recorded in `~/Library/Application Support/CADCraft/self-update.txt`). It's not known whether this can be turned off, or what else goes out over the network.
- ~~**Live bridge.**~~ Works (2026-11-10): `inspect_drawing`, `query_entities` and `screenshot` reached the running app. `inspect_drawing` with entities included is too large for a whole plan, so use `query_entities` with filters.

## Sample: `drawings/sample_apartment.dwg`

Read on 2026-11-10 with `cadcraft-cli info` and a DXF copy parsed with ezdxf. Nothing was skipped on read.

- **File:** DXF version AC1032 (2018), units mm (`$INSUNITS = 4`). At first it had 124 entities: 118 in model space (the plan) and 6 in the paper-space layouts. The total was 100 polylines, 11 arcs, 5 lines, 1 circle and 1 block reference.
- **Layers:** `0` (walls plus some furniture), `Proy` (HIDDEN linetype: furniture and door swings) and `Defpoints`.
- **Blocks:** only the AutoCAD defaults `_ArchTick` and `_DetailCallout`, plus one anonymous block `*U5`, which is probably the chairs around the round table.
- **Missing:** no text, no dimension entities, no closed room outlines. Walls are double lines with gaps at the doors, mostly 350 mm thick.
- **Stray items:** at first there were loose furniture pieces outside the plan (x ≈ 6.9–10.1 m) and a 1400×800 rectangle on the terrace. The user deleted all four (handles `6AA`, `6AB`, `6B9`, `617`) on 2026-11-10. Model space now has 114 entities.

Rooms as read from the coordinates. The names are guesses from the furniture:

| Room | Clear size (mm) | Area | Contents |
| --- | --- | --- | --- |
| Living/dining (top right) | 3700 × 5600 | ~20.7 m² | L-sofa, round rug, table 1400×800 with 4 chairs, French door to the terrace |
| Bedroom (top left) | 3000 × 5600 | ~16.8 m² | Two single beds in an L, desk, dresser, shelf |
| Main bedroom (centre) | ~5260 × ~4650 | ~24 m² | Bed 2700×2000, 3.8 m wardrobe, desk, bench |
| Walk-in closet | 1200 × 4980 | ~6.0 m² | Off the main bedroom |
| Bedroom 2 | 3200 × 2700 | ~8.6 m² | Double bed 1600×2000, wardrobe 700×1400 |
| Bathroom | 3200 × 1450 | ~4.6 m² | Bath 1700×700, WC, basin |
| Kitchen/diner (bottom) | ~3450 × 2800 | ~9.4 m² | 600 mm counter, round table Ø1200 with 4 chairs |
| Corridor (east) | 1200–1450 wide, ~12.6 m long | | 800 mm doors, entrance at the bottom |
| Terrace/garden (top) | 7750 × 6000 | ~46.5 m² | |

The sizes marked `~` come from rooms with jogs or chamfers. They will be exact once each room has a closed `ROOM` outline.

### What the sample needs before automation

1. A closed `ROOM` polyline and a name text for each room. These could be generated from the wall lines into a **copy** of the file, for review.
2. Furniture moved to its own layer (`FURN`) and door swings to `DOOR`, separate from the walls.
3. Furniture as named blocks, or at least labelled, so a bed can be told apart from a wardrobe.
