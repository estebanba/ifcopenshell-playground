# Casa ATO: IFC model from photos, with a schematic MEP

Status: **architecture and MEP built** (2026-11-09/10). `scripts/build_casa_ato.py` writes `models/casa-ato.ifc` (IFC4, metres). It calls `scripts/casa_ato_mep.py` for the MEP. The architecture is reconstructed from photos and the dimensions are estimates. The MEP is a design proposal: none of it is visible in the sources.

```bash
uv run python scripts/build_casa_ato.py      # writes models/casa-ato.ifc and prints a count of MEP elements
```

## Sources

Casa ATO, IR arquitectura, San Isidro (Buenos Aires), 2016–2020. There were no drawings. The model is built from:

- the project text and 22 photos on [estebanbasili.com/work/ir-arquitectura/casa-ato](https://www.estebanbasili.com/work/ir-arquitectura/casa-ato). The page is a single-page app: the text is in the JS bundle, and the photo list comes from `https://locus-api.estebanbasili.com/api/cloudinary/images/portfolio/work/casa-ato`;
- 49 more photos in the [ArchDaily publication 1018863](https://www.archdaily.com/1018863/ato-house-ir-arquitectura). It has photos only, no plans or sections.

Photos by Fernando Schapochnik. The photos are **not** stored in the repo. The copies used during modelling were in a temporary session folder.

## Reading of the building

From the project text and the photos together:

- **Concrete walls:** three board-formed walls (M1–M3) stand in a middle band, perpendicular to the street. Between M1 and M2 is the **sanitary core**. Between M2 and M3 is the **circulation void**, open to the sky, with open steel stairs from the ground floor to the roof.
- **Roof:** the walls carry a concrete roof slab. Three upstand ("inverted") beams run over the walls and cantilever front and back as corbels.
- **Upper floor:** a steel floor, hung from those corbels by steel hangers in the front and back facades. The front and back zones span the full width. Below them the ground floor is open and semi-covered.
- **Front facade** (street and pool side): glazing set back behind white planters, with exterior motorised blinds.
- **Back facade:** dark panels with deep, projecting window reveals.
- **One side facade:** vertical slats.
- **Roof garden:** planted, with concrete parapets around the void and a tube railing whose ends curve down.

Coordinates in the model: x runs along the street, y runs from the front facade (y = 0) to the back, and z is up. The street and pool are at negative y.

## Estimated dimensions

These are scaled from people in the photos and from known elements (roughly ±15 %). They are named constants at the top of `build_casa_ato.py`. All heights derive from `FFL_UP`, `CEIL` and the roof build-up, so changing one level keeps the rest consistent.

| Constant | Value | Meaning |
| --- | --- | --- |
| `W`, `BAY` | 11.0 m, 2.75 m | Box width, 4 equal bays; walls and hangers on the 3 inner grid lines |
| `D`, `ZONE` | 12.0 m, 4.0 m | Box depth; the hung front and back zones are 4 m deep each, and the middle band is 4 m |
| `FFL_UP` | 3.2 m | Upper finished floor. The box underside is at about 2.78 m, matched to photo 0009 |
| `CEIL` | 6.0 m | Underside of the roof slab (2.8 m rooms) |
| `ROOF_T`, `GARDEN_T` | 0.20 m, 0.40 m | Roof slab, green roof substrate. The garden top is at 6.6 m |
| `WALL_T`, `SKIN_T` | 0.25 m, 0.15 m | Concrete walls, lightweight back and side walls |
| `GLASS_SET` | 0.50 m | Front glazing setback behind the planters and blinds |
| Lot, pool | ~13 m wide; pool 3.5 × 10.4 m in the front garden | The text gives the 1 m side setbacks |

Matching check: with cameras placed where photos 0009 (front garden), 0040 (back corner) and 0006 (aerial) were taken, the model reads like the photos. The box's height-to-width ratio is 0.37 in the model and 0.38 in photo 0009.

## The model: architecture

Three storeys: Ground floor (0.0), Upper floor (3.2), Roof garden (6.2).

| Part | IFC |
| --- | --- |
| Concrete walls M1–M3, void parapets | `IfcWall` (SOLIDWALL, PARAPET) |
| Roof slab with the void opening | `IfcSlab` ROOF, profile with a hole |
| Upstand beams and corbels, void edge beams | `IfcBeam` (concrete) |
| Hangers | `IfcMember` USERDEFINED "Hanger" |
| Steel floor | `IfcBeam` IPE300 edges and cross beams, IPE200 joists, `IfcSlab` deck and landing |
| Front glazing, glass at the void ends | `IfcCurtainWall` aggregating `IfcPlate` panels and `IfcMember` mullions |
| Back and side facades | `IfcWall` with `IfcOpeningElement` + `IfcWindow`. The back windows have projecting reveals |
| Blinds, side slats | `IfcShadingDevice` (JALOUSIE, USERDEFINED) |
| Planters | `IfcBuildingElementProxy` "Planter" |
| Green roof | `IfcCovering` ROOFING |
| Railing | `IfcRailing`, swept-disk tubes with arc ends |
| Stairs in the void | `IfcStair`: treads and two flat stringers per flight |
| Site | Lawn (`IfcGeographicElement`), paving and pool deck (`IfcSlab`), water (`IfcBuildingElementProxy` "Swimming pool"; IFC4 has no pool class) |
| Spaces | 9 `IfcSpace`: core, terraces, void (EXTERNAL), living and kitchen, bedrooms, bathrooms, side zone, corridor |

The project pset `CasaATO_Provenance` records the sources, the photographer, the method, the accuracy, the key assumptions, and that the MEP is a proposal.

## The model: MEP (schematic design proposal)

The text names these systems: a groundwater (geothermal) heat pump, photovoltaics, robotic blinds, home automation, lighting, security and irrigation. The rest is designed to fit the plan:

- **Plant room and risers:** the plant room is in the ground-floor sanitary core, and every riser runs in one shaft in the core's back-left corner.
- **Upper floor:** water and heating are PEX in the floor build-up.
- **Drainage:** one soil stack, vented through the roof garden.
- **Ventilation:** natural cross-ventilation, as the text describes. There is no MVHR, only bathroom and kitchen extracts.

| System (`IfcDistributionSystem`) | Main parts |
| --- | --- |
| Geothermal groundwater (open loop) | Production well at the front, reinjection well at the back (30 m casings), submersible pump, plate heat exchanger |
| Heat pump source loop | Heat exchanger ↔ 8 kW water-to-water heat pump |
| Radiant floor heating / cooling | 200 l buffer tank, circulator, riser, 8-loop manifold with thermal actuators, PEX loops in the front, back and corridor zones |
| Domestic cold / hot water | Street meter, stopcock, 250 l cylinder heated by the heat pump, cold and hot manifolds, a PEX home run to each of the 7 fixtures (2 bathrooms, kitchen) |
| Sanitary drainage and vent | Fixture branches → multi-inlet stack fitting → stack → inspection chamber → sewer; vent cowl on the roof; plant room floor trap |
| Rainwater harvesting | 2 roof garden drains with downpipes on the back facade, a void floor gully, and a 4.5 m³ underground cistern |
| Irrigation | Pump in the cistern → riser → roof solenoid valves → roof drip ring; branch to the planter drip lines |
| Pool filtration | Skimmer → pump → sand filter (in the plant room) → return inlet |
| Bathroom and kitchen extract | Ceiling grilles → riser → roof fan; kitchen hood → its own duct and roof cowl |
| Power distribution | Meter pillar, ducts, main board, cable tray riser, upper consumer unit, 8 floor outlets |
| Lighting | 22 point lights on circuits: soffit, ceilings and pool |
| Photovoltaic generation | 18 × 400 Wp modules over the back roof, 2 strings, combiner box, 7 kW inverter → main board |
| Home automation (KNX) | Controller, blind motors, room sensors, weather station, cistern level and soil moisture sensors, bus trunk cable |
| Security and fire detection | 3 cameras, smoke detectors, router/NVR |

How it's modelled:

- **Rigid networks** (drainage, groundwater, primary heating, ducts, trays, pool, water main) are `IfcPipeSegment` / `IfcDuctSegment` / `IfcCableCarrierSegment` per straight leg, joined by BEND fittings. Tees and manifolds are JUNCTION fittings.
- **Flexible runs** (PEX loops and home runs, drip lines, cables, conduits) are each one continuous segment along a polyline. This matches how they're installed, with no fittings.
- **Ports.** Every segment, fitting and device has `IfcDistributionPort`s, connected upstream → downstream with `IfcRelConnectsPorts` (`connect_port(direction="SOURCE")`). Each element is assigned to its system or systems.

## Checks (2026-11-10)

- `ifcopenshell.validate`: 0 issues.
- All 527 elements with geometry triangulate in the venv's ifcopenshell (95 architecture, 432 MEP).
- Every piped system forms **one connected network** through its ports. Extract has 2 by design: the bathrooms and the kitchen.
- Power distribution (6 networks), home automation (4) and security (0) are partly logical. Their devices belong to the system without modelled cables between them.
- There are 20 unconnected ports, all of them intentional ends: street main, sewer, reinjection depth, drip line ends, the tray top, the last light or outlet on each circuit, and the PV string starts.

## Viewing in Bonsai

```python
bpy.ops.bim.load_project(filepath=".../models/casa-ato.ifc", should_start_fresh_session=True)
```

To inspect the MEP, run `scripts/blender_arch_transparency.py` in Blender (Text Editor → Run Script, or over MCP):

- **What it does:** sets every non-MEP object to 12 % opacity and hides spaces, openings and shading devices.
- **Viewport only:** the IFC is untouched. Re-run it after every load.
- **To restore:** set `ALPHA = 1.0` and run it again. Glass and water keep their own transparency.

Bonsai notes:
- Swept-disk pipes, cables and the railing load as **CURVE** objects, not meshes.
- In solid shading, dark materials look light grey under studio lighting. Use material preview to judge colours.

## Known limits

- **Estimates, not survey:** every dimension is estimated. Interior partitions beyond the core, doors, furniture and kitchen joinery are not modelled.
- **Unverified layout details:** which side has the slats is a reading of one photo (0065). The stairs are simplified.
- **Clashes accepted at this level of detail:** slabs pass over the walls, beams pass through wall ends, and the railing crosses the upstand beams. The MEP has no penetrations or sleeves through walls and slabs, and no clash detection has been run.
- **Drains are drawn level,** not sloped.
- **Not modelled:** sizing calculations (pipe and duct sizes are nominal), switches, earthing and lightning protection. The heat pump, pumps, fans and blind motors have no modelled cables; they belong to their systems logically.

## Open items

1. **Real dimensions.** The most useful inputs are the overall width and depth, the floor-to-floor heights and the wall spacing. Any drawings would help too. A rebuild with them takes minutes.
2. **The real MEP.** The MEP is a proposal. Replace it with the installed systems, equipment sizes and routes if they're known.
3. **Stable GlobalIds.** They are random on every build, so anything added in Bonsai is lost on a rebuild. Derive them from stable keys with UUID5, as `build_sample_apartment.py` does.
4. **Quantities.** No element or space has `Qto_*` sets yet.
5. **Penetrations and clashes.** Add openings or sleeves where the MEP crosses walls and slabs, then run a clash check.
6. **Drain falls.** Slope the gravity drains if the model is to be used beyond visualisation.
