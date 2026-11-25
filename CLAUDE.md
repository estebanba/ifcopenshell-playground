# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A playground for IFC (Industry Foundation Classes / BIM) work in Python. It has three parts:

1. **Python and notebooks:** IfcOpenShell, ifccsv and pandas, run in the uv venv.
2. **Blender MCP:** controlling Blender 5.2 and the Bonsai BIM add-on from Claude through [mcp-for-blender](https://github.com/ahujasid/mcp-for-blender).
3. **CADCraft → Blender interior workflow (current focus):** the user draws 2D plans in CADCraft. Claude reads them live over CADCraft's MCP, generates an IFC and loads it in Bonsai. See `docs/cadcraft-interior-workflow.md`.

## Environment (last verified 2026-11-09)

| Component | Version | Notes |
| --- | --- | --- |
| Python | 3.12.11 | `.python-version`, managed by uv 0.13.7 |
| ifcopenshell / ifccsv | 0.9.0.post1 / 0.9.0 | in the project venv |
| pandas / numpy / shapely | 3.1.1 / 2.5.4 / 2.2.0 | pandas 3 upgrade checked; the notebook exports did not change |
| Blender | 5.2.3 LTS | `/Applications/Blender.app` |
| Bonsai | 0.9.1-alpha261108 | Blender extension; bundles **its own** IfcOpenShell (0.9.1a261108), separate from the venv |
| mcp-for-blender | server 2.2.7 (pinned), add-on 1.8 | MCP protocol 15 |
| CADCraft | 0.19.0 (app + `cadcraft-cli`) | 2D DXF/DWG drafting. App in `/Applications`; CLI in `~/.local/opt/cadcraft-cli-0.19.0`, symlinked from `~/.local/bin` |

## Common Commands

```bash
uv sync                                             # install (dev group: ipykernel, nbclient, nbformat, nbstripout)
uv run python main.py                               # placeholder entry point
uv run python scripts/check_notebooks.py notebooks/*.ipynb   # run all notebooks in memory, report errors
python3 scripts/mcp_call.py '[["get_scene_info", {}]]'       # call Blender MCP tools directly (see below)
uv lock --upgrade && uv sync                        # upgrade deps; then re-run check_notebooks
open -a CADCraft --args --control 7979              # start CADCraft so the `cadcraft` MCP bridge can connect
cadcraft-cli info drawings/<file>.dwg               # drawing summary as JSON (headless)
cadcraft-cli convert drawings/<file>.dwg out.png    # render; also svg/pdf/dxf/dwg
```

## Project Structure

- `notebooks/`: experiments. They open models with relative paths (`../models/...`), so run them with cwd set to `notebooks/`.
  - `01-hello-world`: basic queries. Writes `empty_model.ifc`, `model_with_wall.ifc` and `new.ifc` into `models/`.
  - `02-code-examples`: iterates over every entity. **Don't keep its outputs**: they made the file 13.8 MB.
  - `XX-ifc-pandas`, `XX-ifccsv`, `XX-ifccsv-structured`: drafts (the `XX` prefix). They write `data/ifccsv_example.csv` and `data/walls_structured.{csv,xlsx}`.
- `models/`: IFC files, **git-ignored**. The main sample is `AC20-FZK-Haus.ifc` (KIT FZK-Haus, IFC4).
- `drawings/`: DXF/DWG drawings, **git-ignored** like `models/`. The first sample is `sample_apartment.dwg`, an apartment plan in mm.
- `docs/cadcraft-interior-workflow.md`: the CADCraft → Blender interior workflow. It covers the design, the proposed layer and block conventions, and an analysis of the sample drawing.
- `docs/fzk-haus-bonsai-edits.md`: the FZK-Haus edits in Bonsai over MCP (the first test, then the barrel roof and structure), with the Bonsai API lessons.
- `docs/casa-ato-model.md`: Casa ATO from photos, plus its schematic MEP. It covers sources, estimates, the IFC mapping, MEP systems, checks and how to view it.
- `data/`: CSV/XLSX exports produced by the notebooks.
- `scripts/check_notebooks.py`: runs notebooks headlessly. It doesn't modify the notebooks, but they may rewrite `data/` and `models/`.
- `scripts/mcp_call.py`: a stdio client for the Blender MCP server, for smoke tests when the `blender` MCP tools aren't loaded.
- `scripts/build_casa_ato.py`: generates `models/casa-ato.ifc` (IFC4) with the venv's ifcopenshell. Its estimated dimensions are named constants at the top; all heights derive from `FFL_UP`, `CEIL` and the roof build-up.
- `scripts/casa_ato_mep.py`: the schematic MEP, called by the build script. Rigid networks use segments, bends and junctions; flexible PEX loops, drip lines and cables are each one continuous segment. Every element has connected ports and belongs to a system.
- `scripts/cadcraft_read.py`: reads every model-space entity of the drawing open in CADCraft over the MCP bridge, or a file with `--file`, and writes JSON (for example `drawings/sample_apartment.entities.json`). Uses the system `python3`; no venv needed.
- `scripts/build_sample_apartment.py`: builds `models/sample_apartment.ifc` from that JSON (`--live` reads the app first). It polygonizes the wall linework into walls, rooms and openings. Door gaps are closed between jamb pairs. Furniture is classified by handle in `FURNITURE`, and rooms are named by `ROOM_SEEDS` until the drawing has text. Heights are assumed constants (`CEIL` 2.70). GlobalIds come from handles and positions, so a rebuild keeps them.
- `scripts/blender_arch_transparency.py`: run in Blender to make the non-MEP objects see-through (viewport only). Run `apply(1.0)` to restore.
- `.mcp.json`: the project-scoped MCP server config: `blender` and `cadcraft`.

## Conventions

- **Notebook outputs are stripped on commit.** `.gitattributes` applies the `nbstripout` filter, and the filter is registered in `.git/config`. A new clone needs `uv run nbstripout --install --attributes .gitattributes` once.
- **Don't commit IFC models.** Add new models under `models/` and document where they came from in the README.
- Check dependency upgrades with `scripts/check_notebooks.py`. Also diff the `data/` exports, which are deterministic.
- **Docs:** one doc per workflow in `docs/`. Each has Status, the model or design, Checks (with a date), Known limits and **Open items**. When the work changes, update that doc, the README's "Status and open points", and the status below. Write down what is estimated or proposed, not only what was built.
- **Generate models with scripts.** Interactive MCP edits can't be reproduced (`blender_edit.ifc` is the cautionary case). Validate every generated model with `ifcopenshell.validate`, and triangulate it in the venv.

## Blender MCP setup

- **Server:** `.mcp.json` runs `uvx mcp-for-blender==2.2.7` with these environment variables:
  - `DISABLE_TELEMETRY=true`: without it the server sends anonymous usage data to Supabase, even though add-on consent is off. Its events can include prompt text.
  - `BLENDERMCP_NO_UPDATE_CHECK=1`
  - `BLENDER_HOST=localhost`, `BLENDER_PORT=9876`
- **Add-on:** `~/Library/Application Support/Blender/5.2/scripts/addons/blender_mcp.py`. In Blender it's listed as "Interface: MCP for Blender". Start it from the 3D view sidebar (N), MCP tab, **Start MCP Server**.
- **Tools:** `get_addon_status`, `get_scene_info`, `execute_blender_code`, `look`, `search_assets`, `import_asset`, `generate_3d`, `disable_telemetry`, `record_trajectory_feedback`.

### User decisions: keep these
- **Telemetry stays off** on both layers: the server environment variable and the add-on's "Allow Telemetry" preference (`telemetry_consent=False`).
- **Localhost only.** Bind Address stays `localhost`, and "Allow Remote Connections" stays off. The socket has no authentication and runs any Python sent to it.
- **External integrations stay off:** Poly Haven, Sketchfab, Poly Pizza, Hyper3D, Hunyuan3D, Tripo and Meshy. Don't call `generate_3d`, `search_assets` or `import_asset` without asking.
- **Keep the version pinned.** Upgrade deliberately: read the new version's `telemetry.py` and its add-on defaults, then update `.mcp.json`, the add-on (`uvx mcp-for-blender==X install-addon --addons-dir "<5.2 addons dir>"`) and this file.

### Gotchas
- The default `install-addon` picks the **old 4.3** addons folder. Always pass `--addons-dir` for 5.2.
- "Add-on not loaded: No module named 'blender_mcp'" means Blender was already running when the addons folder was created. Restart Blender.
- If the `blender` MCP tools are missing in a session, check that Blender is running and the server is started, then that `.mcp.json` was approved. `scripts/mcp_call.py` checks the connection outside Claude Code's MCP integration.
- Code run with `execute_blender_code` uses **Bonsai's** IfcOpenShell (0.9.1a), not the venv's (0.9.0).

## CADCraft MCP setup (2026-11-10)

- **Goal:** interior design. Draw plans in CADCraft; Claude reads them live over MCP and builds the model in Blender/Bonsai.
- **Server:** `.mcp.json` entry `cadcraft` runs `cadcraft-cli mcp --connect 127.0.0.1:7979 --lazy`, a bridge to the running app.
- **Start the app with the control port:** `open -a CADCraft --args --control 7979`. A normal launch has no control port, and the bridge then fails on its first call. The port binds to loopback only and needs a per-session token, which the bridge reads by itself from `~/.cache/cadcraft-control-7979.token`.
- **Headless:** `cadcraft-cli mcp` (no `--connect`) has the same read tools on a file. `cadcraft-cli info|convert` works for one-off reads and renders.
- **Read tools:** `query_entities` (handles and geometry), `inspect_drawing`, `find_text`, `execute` → `shapes` (area, perimeter) or `loops`, `render` (PNG). There are no change events, so re-query after the user says they edited.
- **`inspect_drawing` output is too large** for a whole plan (about 107k characters for 114 entities). Call it with `entities: false`, and use `query_entities` filtered by layer, window or selection.
- **`entityCount` includes paper space.** In the sample it is 120, while `query_entities` counts the 114 in model space.
- **The CADCraft window must stay open.** `screenshot` saves the PNG to a temp folder under `/var/folders/...`.
- **Install check:** the CLI zip's SHA256 matched `SHA256SUMS.txt`. The CLI is signed and notarised by the same Developer ID (team `DJ6XS33FX8`) as the app. The gpg signature wasn't checked because gpg isn't installed.
- **Open question:** the app updates itself (`~/Library/Application Support/CADCraft/self-update.txt`). It's not known yet whether that can be turned off, or what else the app sends over the network.
- **Sample drawing:** `drawings/sample_apartment.dwg` (mm). Layer `0` holds walls and some furniture; `Proy` holds furniture and door swings. It has no text, no dimensions and no closed room outlines. See the workflow doc.
- **Reading DXF in Python:** ezdxf is *not* in the project venv. For one-off reads, use `uv run --no-project --with ezdxf python -I script.py file.dxf` on a DXF copy made with `cadcraft-cli convert`.

## Status and next steps

- Done (2026-11-08/09):
  - repo cleanup and `.gitignore`;
  - dependency upgrade, with the notebooks verified;
  - notebook outputs stripped;
  - Blender and Bonsai updated;
  - Blender MCP installed and checked end to end.
- **Repository:** **public** on GitHub, `estebanba/ifcopenshell-playground` (2026-11-25). Keep private details out of tracked files: the apartment sample is called "sample apartment" on purpose, and its local files are reached through git-ignored symlinks. Commits carry **no** Claude co-author or attribution lines; that's turned off in the user settings (`attribution` in `~/.claude/settings.json`). `models/` and `drawings/` are git-ignored and exist only locally.
- FZK-Haus in Bonsai over MCP (2026-11-09), **done**. Details are in [docs/fzk-haus-bonsai-edits.md](docs/fzk-haus-bonsai-edits.md).
  - The first test passed: all 1,326 wall values match the CSV, one thermal value was edited, and notebook 03 verifies it.
  - Then the gable roof became a barrel arc, with its rafters, purlins, walls and Galerie adapted.
  - `blender_edit.ifc` has the 5 schema errors already in the original export, and no new ones.
  - Open: the edits aren't scripted (the file can't be regenerated), the quantities and space boundaries are stale, and the notebook doesn't check the roof.
- Casa ATO (2026-11-09/10), **built**. Details are in [docs/casa-ato-model.md](docs/casa-ato-model.md).
  - It's rebuilt from photos, plus a schematic MEP: 15 systems, 432 MEP elements, all connected through ports.
  - Validation finds 0 issues and all 527 elements triangulate.
  - Open: the dimensions are estimates and the MEP is a proposal. GlobalIds are random on each build, so switch to UUID5. There are no quantities, penetrations or clash check, and the drains aren't sloped.
  - Gotchas:
    - Bonsai loads swept-disk pipes as CURVE objects.
    - A serpentine needs an even number of passes, or its return lane overlaps the last pass and the loop fails to triangulate.
- CADCraft set up (2026-11-10):
  - The app and CLI are installed at 0.19.0, and the `cadcraft` MCP server is in `.mcp.json`.
  - A headless MCP smoke test passed: `open`, then `query_entities` returned handles and geometry.
  - The sample drawing was read and analysed.
  - **Live bridge works** (later on 2026-11-10): `inspect_drawing`, `query_entities` and `screenshot` reached the running app.
  - **Handles survive edit and save.** The user deleted 4 entities (`617`, `6AA`, `6AB`, `6B9`) and saved; the other 114 kept their handles. Anonymous block names do **not** survive a save (`*U5` became `*U3`), so never use them as IDs.
  - **First apartment model** (2026-11-10): `build_sample_apartment.py` produces 9 spaces, 7 walls plus 14 opening wall pieces, 9 doors, 5 windows, floors and ceilings, and 30 furniture and sanitary items. Validation finds 0 issues, all 106 elements triangulate, and it loads in Bonsai. The top view matches the CADCraft plan.
    - Plan-reading gotchas: a hinge arc can sit on a neighbouring pier's edge, so a face is only a door if its width equals the sum of its leaf radii. The chairs block (`78B`) nests 4 chairs that MCP doesn't return, so they are rebuilt around table `732`. The counter `56D` is a single line, so it is offset 600 mm into the kitchen.
  - Next:
    - test that handles also survive moving or stretching an entity, and undo;
    - edit-and-rebuild round trip: change the drawing, rebuild with `--live`, reload in Bonsai, and check the GlobalIds;
    - agree on the layer and block conventions, which would replace `NOT_WALL`, `FURNITURE` and `ROOM_SEEDS`;
    - confirm the real ceiling, door and window heights.
- Later:
  - rename the `XX-*` notebooks into the numbered sequence;
  - replace the placeholder `main.py`, or move reusable helpers into a module.
