# FZK-Haus: editing an IFC in Bonsai over MCP

Status: **done** (2026-11-09). The first Blender MCP + IFC test passed, followed by a larger geometry edit: a barrel roof, with the roof structure and walls adapted to it. Everything was done **interactively** through `execute_blender_code`. No script reproduces it (see [Open items](#open-items)).

- Input: `models/AC20-FZK-Haus.ifc` (KIT FZK-Haus, IFC4, ArchiCAD export).
- Output: `models/blender_edit.ifc`.
- Check: `notebooks/03-blender-edit-check.ipynb`.

## 1. First test: read, compare, edit, verify

1. **Load:** Bonsai opened FZK-Haus with `bpy.ops.bim.load_project(..., should_start_fresh_session=True)` in about 0.6 s: IFC4, 13 walls.
2. **Compare:** I read every wall's psets and quantity sets in Blender, using Bonsai's IfcOpenShell 0.9.1a, and compared them with `data/walls_structured.csv` from the venv's 0.9.0. All 13 GlobalIds and all **1,326 values match**, with the same columns on both sides. (`ArchiCADProperties.Geschützt` is a boolean in IFC and the text `"False"` in the CSV. Compare those as strings.)
3. **Edit:** I set `Pset_WallCommon.ThermalTransmittance` on `Wand-Ext-ERDG-1` from 0.4 to 0.28 with `ifcopenshell.api.run("pset.edit_pset", ...)`, then saved with `bpy.ops.bim.save_project(filepath=..., should_save_as=True)`.
4. **Verify:** `03-blender-edit-check.ipynb` opens both files with the venv's ifcopenshell and asserts that this is the only change to any wall property.

## 2. Barrel roof

The gable roof was two slabs (Dach-1 and Dach-2), each a flat extrusion 0.2 m thick, sloped at 30°. They became **one** curved slab:

- **Dach-1 keeps its GlobalId, psets, material and style.** Its body is now an `IfcExtrudedAreaSolid` with an `IfcArbitraryClosedProfileDef` over an `IfcIndexedPolyCurve` with true arc segments, extruded 13 m along x.
- **Arc geometry:** it runs through the old eaves (z 2.91 m) and the old ridge height (z 6.32 m). The rise is 3.21 m, the inner radius Rᵢ = 6.317 m (centre at y = 5, z = −0.197), and the slab is 0.2 m thick radially.
- **Dach-2 is removed** with `root.remove_product`, so GlobalId `2IxUUNUVPB6Ob$eicCfP2N` no longer exists.
- The bounding-box representation was updated.

## 3. Roof structure and walls adapted to the arc

In the original model everything sat tight against the roof underside. The adaptation keeps that logic and keeps every GlobalId:

| Element | Change |
| --- | --- |
| 42 rafters (`Sparren-*`, `IfcMember`) | ArchiCAD B-reps replaced by curved half-arches, 80 × 160 mm, eave to crown. They are embedded in the slab, from Rᵢ to Rᵢ + 0.16, at the same 21 x positions |
| Ridge beam `First` | Moved up 3 cm to the new crown (top z 6.12 m) |
| Eave purlins `Pfette-1-1`, `Pfette-2-1` | Moved up about 0.6 m and tilted ±49°, so their top faces follow the arc (top about z 3.95 m). Only the placement changed; the geometry is the original |
| Eave walls `Wand-Ext-OG-2/4` | The old half-space cut became an intersection with a cylinder of radius Rᵢ − 0.16 (`IfcBooleanResult` INTERSECTION, representation type `CSG`). They now rise to the purlins |
| Gable walls `Wand-Ext-OG-1/3` | Intersected with a cylinder of radius Rᵢ, so they close up to the curved underside (top z 6.12 m) |
| Space `7 Galerie` | Rebuilt as the volume under the arc (an extruded profile with an arc) |
| Bounding boxes | Recalculated for all 50 changed elements |

Fit check, triangulated with the venv's ifcopenshell and measured as the radius from the arc axis:
- slab 6.317–6.517 m;
- rafters 6.317–6.477 m;
- ridge beam and purlins 6.157–6.317 m;
- eave walls up to 6.157 m;
- gable walls and the Galerie up to 6.317 m.

So everything is tight against the arc. The only overlap is the purlin top edges, which reach 0.2 mm into the slab, where a flat face meets a curve.

## Checks (2026-11-25)

- `ifcopenshell.validate` on `blender_edit.ifc` reports 5 schema errors. The **original `AC20-FZK-Haus.ifc` has the same 5**: `VIRTUAL` `IfcRelSpaceBoundary` entries on level 2a without a `RelatedBuildingElement`, from the ArchiCAD export. The edits added none.
- `03-blender-edit-check.ipynb` runs with 0 errors.

## Lessons (Bonsai 0.9.1a, over MCP)

- `ifcopenshell.util.placement.get_local_placement` doesn't exist in Bonsai's build. Use `get_placement`.
- `IfcStore.get_entity` doesn't exist either. Use `bonsai.tool.Ifc.get_entity(obj)`.
- Editing the IFC directly with the API, then `f.write(path)` and reloading with `load_project`, is the robust way to refresh the viewport after large geometry changes.
- Code run through MCP uses **Bonsai's** IfcOpenShell (0.9.1a), not the venv's (0.9.0). Cross-check results in the venv.

## Known limits

- **Stale quantities:** BaseQuantities and ArchiCADQuantities still describe the old geometry. Dach-1 still says `GrossArea` 82.56 m², which is the old half roof. The 4 upper walls and the Galerie (`GrossVolume` 428.64 m³) are out of date too.
- **Stale space boundaries:** the `IfcRelSpaceBoundary` connection geometry still traces the old gable outline.
- **Purlins through the gable walls:** the purlins still pass through the gable walls. The original model was built the same way.
- **Naming:** the single roof slab is still called "Dach-1".
- **Notebook scope:** `03-blender-edit-check.ipynb` checks wall properties only. It doesn't check the roof geometry.

## Open items

1. **Script the edits.** `blender_edit.ifc` can't be regenerated: the steps were run interactively, and the backup taken before the structure step was in a temporary session folder that no longer exists. A script that goes from `AC20-FZK-Haus.ifc` to `blender_edit.ifc` would make it reproducible and reviewable.
2. **Quantities.** Recalculate the BaseQuantities from the new geometry (`ifc5d` / Bonsai's quantity take-off). Remove the ArchiCAD-specific quantities or mark them as stale.
3. **Space boundaries.** Regenerate them for the upper floor, or remove them.
4. **Roof check in the notebook.** Extend `03-blender-edit-check.ipynb` to assert the roof changes: one roof slab with an arc profile, rafter radii and wall tops.
