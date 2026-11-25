"""Build an approximate IFC4 model of Casa ATO (IR arquitectura, San Isidro, 2016-2020).

There are no drawings. The model is reconstructed from the project text and photographs
(portfolio: estebanbasili.com/work/ir-arquitectura/casa-ato; ArchDaily 1018863;
photos by Fernando Schapochnik). All dimensions below are ESTIMATES scaled from people
and known elements in the photos (roughly +/-15 %). Change them here and re-run.

    uv run python scripts/build_casa_ato.py            # writes models/casa-ato.ifc

Coordinates: x runs along the street (box width), y runs front -> back (front facade at
y = 0 faces the street and the pool, which lie at negative y), z is up. Metres.

Reading of the building (from the text and photos):
- Three board-formed concrete walls (M1-M3), perpendicular to the street, stand in a middle
  band. Between M1 and M2 is the sanitary core; between M2 and M3 is the circulation void,
  open to the sky and holding open steel stairs.
- The walls carry the concrete roof slab. On the roof, three upstand ("inverted") beams run
  over the walls and cantilever front and back as corbels.
- The steel upper floor of the front and back zones hangs from those corbels by steel
  hangers in the facade planes. The ground level stays open and semi-covered.
- Front facade: glazing set back behind white planters and exterior blinds.
- Back facade: dark panels with deep punched windows.
- One side facade has vertical slats.
- The roof is a landscaped garden with parapets around the void and a tube railing whose
  ends curve down.
"""

from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.api as api
import ifcopenshell.api.aggregate  # noqa: F401  (submodules must be imported explicitly)
import ifcopenshell.api.context  # noqa: F401
import ifcopenshell.api.feature  # noqa: F401
import ifcopenshell.api.geometry  # noqa: F401
import ifcopenshell.api.material  # noqa: F401
import ifcopenshell.api.project  # noqa: F401
import ifcopenshell.api.pset  # noqa: F401
import ifcopenshell.api.root  # noqa: F401
import ifcopenshell.api.spatial  # noqa: F401
import ifcopenshell.api.style  # noqa: F401
import ifcopenshell.api.unit  # noqa: F401

OUT = Path(__file__).resolve().parent.parent / "models" / "casa-ato.ifc"

# ---------------------------------------------------------------- estimated dimensions
W = 11.0            # box width along the street (4 bays)
BAY = W / 4         # structural bay; walls M1-M3 and hangers on the 3 inner grid lines
D = 12.0            # box depth, front -> back
ZONE = 4.0          # depth of the hung front / back zones; middle band = D - 2*ZONE
WALL_T = 0.25       # concrete wall thickness
FFL_UP = 3.2        # upper floor finished level (box underside ~2.8, matched to photo 0009)
DECK_T = 0.12       # steel deck + finish
BEAM_H = 0.30       # IPE300 edge / cross beams
CEIL = 6.0          # underside of the concrete roof slab (2.8 m rooms)
ROOF_T = 0.20       # concrete roof slab
GARDEN_T = 0.40     # green roof substrate
RAIL_H = 1.10      # railing height above the garden
GLASS_SET = 0.50    # front glazing setback behind planters / blinds
SKIN_T = 0.15       # lightweight back / side walls
BLIND_DROP = 1.35   # how far the front blinds are lowered (as in most photos)

BOTTOM = FFL_UP - DECK_T - BEAM_H        # underside of the hung box (2.78)
ROOF_TOP = CEIL + ROOF_T                 # 6.2
GARDEN_TOP = ROOF_TOP + GARDEN_T         # 6.6
FASCIA_TOP = ROOF_TOP + 0.5              # top of the steel roof edge
PARAPET_TOP = GARDEN_TOP + 0.8           # concrete parapets around the void
VOID_BEAM = (CEIL - 0.4, GARDEN_TOP + 0.4)   # deep concrete beams closing the void ends at roof level
XM = [BAY, 2 * BAY, 3 * BAY]             # wall / hanger grid lines
VOID_X = (XM[1] + WALL_T / 2, XM[2] - WALL_T / 2)   # clear width of the void
BAND_Y = (ZONE, D - ZONE)                           # middle band

f = api.project.create_file(version="IFC4")


# ---------------------------------------------------------------- geometry helpers
def P3(x, y, z):
    return f.createIfcCartesianPoint((float(x), float(y), float(z)))


def Dir(*v):
    return f.createIfcDirection(tuple(float(a) for a in v))


def polyline(pts):
    pts = list(pts) + [pts[0]]
    return f.createIfcPolyline([f.createIfcCartesianPoint((float(a), float(b))) for a, b in pts])


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def profile(outer, holes=()):
    if holes:
        return f.createIfcArbitraryProfileDefWithVoids("AREA", None, polyline(outer), [polyline(h) for h in holes])
    return f.createIfcArbitraryClosedProfileDef("AREA", None, polyline(outer))


def extrude_z(outer, z0, z1, holes=()):
    pos = f.createIfcAxis2Placement3D(P3(0, 0, z0), None, None)
    return f.createIfcExtrudedAreaSolid(profile(outer, holes), pos, Dir(0, 0, 1), float(z1 - z0))


def box(x0, y0, z0, x1, y1, z1):
    return extrude_z(rect(x0, y0, x1, y1), z0, z1)


def extrude_x(pts_yz, x0, x1):
    """Extrude a profile drawn in the (y, z) plane along +x."""
    pos = f.createIfcAxis2Placement3D(P3(x0, 0, 0), Dir(1, 0, 0), Dir(0, 1, 0))
    return f.createIfcExtrudedAreaSolid(profile(pts_yz), pos, Dir(0, 0, 1), float(x1 - x0))


def ipe(h, b, tw, tf, name):
    return f.createIfcIShapeProfileDef("AREA", name, None, b, h, tw, tf, 0.012)


IPE300 = ipe(0.30, 0.15, 0.0071, 0.0107, "IPE300")
IPE200 = ipe(0.20, 0.10, 0.0056, 0.0085, "IPE200")


def beam_along(prof, start, axis, length):
    """I-section with its centroid line starting at `start`, running along `axis` (x or y)."""
    ref = (0, 1, 0) if axis == "x" else (1, 0, 0)
    a = (1, 0, 0) if axis == "x" else (0, 1, 0)
    pos = f.createIfcAxis2Placement3D(P3(*start), Dir(*a), Dir(*ref))
    return f.createIfcExtrudedAreaSolid(prof, pos, Dir(0, 0, 1), float(length))


def tube(points, radius, arcs=()):
    """Swept-disk tube along a 3D polyline; `arcs` = list of (i, j, k) 1-based arc index triples."""
    pl = f.createIfcCartesianPointList3D([[float(c) for c in p] for p in points])
    segs, i, n = [], 1, len(points)
    arc_starts = {a[0]: a for a in arcs}
    run = [1]
    while i < n:
        if i in arc_starts:
            if len(run) > 1:
                segs.append(f.createIfcLineIndex(run))
            a = arc_starts[i]
            segs.append(f.createIfcArcIndex(a))
            i = a[2]
            run = [i]
        else:
            i += 1
            run.append(i)
    if len(run) > 1:
        segs.append(f.createIfcLineIndex(run))
    curve = f.createIfcIndexedPolyCurve(pl, segs, False)
    return f.createIfcSweptDiskSolid(curve, float(radius), None, None, None)


# ---------------------------------------------------------------- project structure
project = api.root.create_entity(f, ifc_class="IfcProject", name="Casa ATO")
project.Description = "Approximate model reconstructed from photographs; dimensions estimated."
api.unit.assign_unit(f, length={"is_metric": True, "raw": "METERS"},
                     area={"is_metric": True, "raw": "SQUARE_METERS"},
                     volume={"is_metric": True, "raw": "CUBIC_METERS"})
model = api.context.add_context(f, context_type="Model")
body = api.context.add_context(f, context_type="Model", context_identifier="Body",
                               target_view="MODEL_VIEW", parent=model)

site = api.root.create_entity(f, ifc_class="IfcSite", name="Lot - San Isidro, Buenos Aires")
building = api.root.create_entity(f, ifc_class="IfcBuilding", name="Casa ATO")
api.aggregate.assign_object(f, products=[site], relating_object=project)
api.aggregate.assign_object(f, products=[building], relating_object=site)
for el in (site, building):
    api.geometry.edit_object_placement(f, product=el, matrix=np.eye(4))
storeys = {}
for key, name, elev in [("GF", "Ground floor", 0.0), ("UF", "Upper floor", FFL_UP), ("RF", "Roof garden", ROOF_TOP)]:
    s = api.root.create_entity(f, ifc_class="IfcBuildingStorey", name=name)
    s.Elevation = elev
    api.aggregate.assign_object(f, products=[s], relating_object=building)
    m = np.eye(4); m[2, 3] = elev
    api.geometry.edit_object_placement(f, product=s, matrix=m)
    storeys[key] = s

# ---------------------------------------------------------------- materials and styles
MATS = {}
for key, name, cat, rgb, tr in [
    ("concrete", "Board-formed concrete", "concrete", (0.70, 0.69, 0.66), 0.0),
    ("steel", "Steel, dark painted", "steel", (0.11, 0.11, 0.12), 0.0),
    ("panel", "Dark facade panel", "aluminium", (0.17, 0.17, 0.18), 0.0),
    ("glass", "Glass", "glass", (0.55, 0.66, 0.72), 0.65),
    ("planter", "Planter, white", "concrete", (0.92, 0.92, 0.90), 0.0),
    ("blind", "Exterior blind slats", "aluminium", (0.13, 0.13, 0.14), 0.0),
    ("partition", "Plasterboard partition", "gypsum", (0.93, 0.93, 0.91), 0.0),
    ("garden", "Green roof substrate and planting", "earth", (0.30, 0.45, 0.20), 0.0),
    ("paving", "Concrete paving", "concrete", (0.80, 0.79, 0.76), 0.0),
    ("lawn", "Lawn", "earth", (0.33, 0.52, 0.24), 0.0),
    ("water", "Pool water", "water", (0.35, 0.68, 0.68), 0.35),
    ("space", "Space", "", (0.85, 0.75, 0.40), 0.85),
]:
    mat = api.material.add_material(f, name=name, category=cat or None)
    st = api.style.add_style(f, name=name)
    api.style.add_surface_style(f, style=st, ifc_class="IfcSurfaceStyleShading", attributes={
        "SurfaceColour": {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]},
        "Transparency": tr})
    MATS[key] = (mat, st)


def make(ifc_class, name, items, mat, container=None, predefined=None, object_type=None,
         rtype="SweptSolid", part_of=None, space_of=None):
    el = api.root.create_entity(f, ifc_class=ifc_class, name=name, predefined_type=predefined)
    if object_type:
        el.ObjectType = object_type
    if part_of is not None:
        api.aggregate.assign_object(f, products=[el], relating_object=part_of)
    elif space_of is not None:
        api.aggregate.assign_object(f, products=[el], relating_object=space_of)
    elif container is not None:
        api.spatial.assign_container(f, products=[el], relating_structure=storeys[container])
    api.geometry.edit_object_placement(f, product=el, matrix=np.eye(4))
    if items:
        rep = f.createIfcShapeRepresentation(body, "Body", rtype, items)
        api.geometry.assign_representation(f, product=el, representation=rep)
        api.style.assign_representation_styles(f, shape_representation=rep, styles=[MATS[mat][1]])
    if mat != "space" and ifc_class not in ("IfcOpeningElement",):
        api.material.assign_material(f, products=[el], type="IfcMaterial", material=MATS[mat][0])
    return el


def window_in(wall, name, container, opening_items, frame_items, glass_items, width, height):
    op = make("IfcOpeningElement", f"{name} opening", opening_items, "glass", predefined="OPENING")
    api.feature.add_feature(f, feature=op, element=wall)
    win = api.root.create_entity(f, ifc_class="IfcWindow", name=name, predefined_type="WINDOW")
    api.spatial.assign_container(f, products=[win], relating_structure=storeys[container])
    api.geometry.edit_object_placement(f, product=win, matrix=np.eye(4))
    win.OverallWidth, win.OverallHeight = float(width), float(height)
    rep = f.createIfcShapeRepresentation(body, "Body", "SweptSolid", frame_items + glass_items)
    api.geometry.assign_representation(f, product=win, representation=rep)
    for it in frame_items:
        f.createIfcStyledItem(it, [MATS["steel"][1]], None)
    for it in glass_items:
        f.createIfcStyledItem(it, [MATS["glass"][1]], None)
    api.material.assign_material(f, products=[win], type="IfcMaterial", material=MATS["glass"][0])
    api.feature.add_filling(f, opening=op, element=win)
    return win


# ---------------------------------------------------------------- site
POOL = (5.9, -12.0, 9.4, -1.6)
POOL_DECK = rect(5.5, -12.4, 9.8, -1.0)
make("IfcGeographicElement", "Garden lawn",
     [extrude_z(rect(-1.0, -16.0, W + 1.0, D + 8.0), -0.30, -0.04, holes=[POOL_DECK])], "lawn",
     container="GF", predefined="TERRAIN")
make("IfcSlab", "Ground paving (covered areas)", [box(-0.5, -1.0, -0.15, W + 0.5, D + 2.5, 0.0)], "paving",
     container="GF", predefined="FLOOR")
make("IfcSlab", "Pool deck", [extrude_z(POOL_DECK, -0.15, 0.0, holes=[rect(*POOL)])], "paving",
     container="GF", predefined="FLOOR")
make("IfcBuildingElementProxy", "Swimming pool (water)", [box(POOL[0], POOL[1], -1.3, POOL[2], POOL[3], -0.10)],
     "water", container="GF", object_type="Swimming pool")

# ---------------------------------------------------------------- concrete structure
for i, x in enumerate(XM, 1):
    make("IfcWall", f"Concrete wall M{i}", [box(x - WALL_T / 2, BAND_Y[0], 0.0, x + WALL_T / 2, BAND_Y[1], CEIL)],
         "concrete", container="GF", predefined="SOLIDWALL")
void_hole = rect(VOID_X[0], BAND_Y[0], VOID_X[1], BAND_Y[1])
make("IfcSlab", "Concrete roof slab", [extrude_z(rect(0, 0, W, D), CEIL, ROOF_TOP, holes=[void_hole])],
     "concrete", container="RF", predefined="ROOF")
for i, x in enumerate(XM, 1):   # upstand beams + front/back corbels, hidden in the garden build-up
    spans = [(0.0, D)] if i == 1 else [(0.0, BAND_Y[0]), (BAND_Y[1], D)]
    make("IfcBeam", f"Inverted beam V{i} with corbels",
         [box(x - WALL_T / 2, y0, ROOF_TOP, x + WALL_T / 2, y1, FASCIA_TOP) for y0, y1 in spans],
         "concrete", container="RF", predefined="BEAM")
for i, x in enumerate(XM[1:], 2):   # walls M2 / M3 continue above the roof as void parapets
    make("IfcWall", f"Void parapet on M{i}", [box(x - WALL_T / 2, BAND_Y[0] - 0.15, ROOF_TOP, x + WALL_T / 2,
                                                  BAND_Y[1] + 0.15, PARAPET_TOP)],
         "concrete", container="RF", predefined="PARAPET")
for name, y0, y1 in [("front", BAND_Y[0] - 0.15, BAND_Y[0]), ("back", BAND_Y[1], BAND_Y[1] + 0.15)]:
    make("IfcBeam", f"Void edge beam ({name})", [box(XM[1] - WALL_T / 2, y0, VOID_BEAM[0], XM[2] + WALL_T / 2, y1, VOID_BEAM[1])],
         "concrete", container="RF", predefined="BEAM")

# ---------------------------------------------------------------- hung steel upper floor
for i, x in enumerate(XM, 1):
    for side, y0, y1 in [("front", -0.08, -0.02), ("back", D + 0.02, D + 0.08)]:
        make("IfcMember", f"Hanger H{i} {side}", [box(x - 0.04, y0, BOTTOM, x + 0.04, y1, FASCIA_TOP)],
             "steel", container="UF", predefined="USERDEFINED", object_type="Hanger")
zc = BOTTOM + BEAM_H / 2
edge = [beam_along(IPE300, (0, 0.075, zc), "x", W), beam_along(IPE300, (0, D - 0.075, zc), "x", W),
        beam_along(IPE300, (0.075, 0.15, zc), "y", D - 0.3), beam_along(IPE300, (W - 0.075, 0.15, zc), "y", D - 0.3)]
make("IfcBeam", "Perimeter edge beams IPE300", edge, "steel", container="UF", predefined="BEAM")
make("IfcBeam", "Cross beams at wall ends IPE300",
     [beam_along(IPE300, (0.15, y, zc), "x", W - 0.3) for y in BAND_Y], "steel", container="UF", predefined="BEAM")
zc2 = FFL_UP - DECK_T - 0.10
sec = []
for k in range(1, 8):
    x = k * BAY / 2
    sec += [beam_along(IPE200, (x, 0.15, zc2), "y", BAND_Y[0] - 0.15),
            beam_along(IPE200, (x, BAND_Y[1], zc2), "y", D - 0.15 - BAND_Y[1])]
make("IfcBeam", "Secondary floor beams IPE200", sec, "steel", container="UF", predefined="JOIST")
make("IfcSlab", "Upper floor steel deck", [extrude_z(rect(0, 0, W, D), FFL_UP - DECK_T, FFL_UP, holes=[void_hole])],
     "steel", container="UF", predefined="FLOOR")
make("IfcSlab", "Void landing", [box(VOID_X[0], BAND_Y[0], FFL_UP - 0.10, VOID_X[1], BAND_Y[0] + 1.0, FFL_UP)],
     "steel", container="UF", predefined="LANDING")
fascia = []
for z0, z1 in [(BOTTOM, FFL_UP), (CEIL, FASCIA_TOP)]:
    fascia += [box(-0.02, -0.02, z0, W + 0.02, 0, z1), box(-0.02, D, z0, W + 0.02, D + 0.02, z1),
               box(-0.02, 0, z0, 0, D, z1), box(W, 0, z0, W + 0.02, D, z1)]
make("IfcPlate", "Steel edge fascias", fascia, "steel", container="UF", predefined="SHEET")

# ---------------------------------------------------------------- envelope
cw = api.root.create_entity(f, ifc_class="IfcCurtainWall", name="Front glazing")
api.spatial.assign_container(f, products=[cw], relating_structure=storeys["UF"])
api.geometry.edit_object_placement(f, product=cw, matrix=np.eye(4))
x0, x1, n = SKIN_T, W - SKIN_T, 8
xs = np.linspace(x0, x1, n + 1)
for i in range(n):
    make("IfcPlate", f"Front glass {i + 1}", [box(xs[i] + 0.03, GLASS_SET, FFL_UP, xs[i + 1] - 0.03, GLASS_SET + 0.02, CEIL)],
         "glass", predefined="CURTAIN_PANEL", part_of=cw)
for i, x in enumerate(xs):
    make("IfcMember", f"Front mullion {i + 1}", [box(x - 0.03, GLASS_SET - 0.04, FFL_UP, x + 0.03, GLASS_SET + 0.08, CEIL)],
         "steel", predefined="MULLION", part_of=cw)

for name, y in [("Void glazing (front room)", BAND_Y[0] - 0.02), ("Void glazing (back room)", BAND_Y[1])]:
    g = api.root.create_entity(f, ifc_class="IfcCurtainWall", name=name)
    api.spatial.assign_container(f, products=[g], relating_structure=storeys["UF"])
    api.geometry.edit_object_placement(f, product=g, matrix=np.eye(4))
    xm = (VOID_X[0] + VOID_X[1]) / 2
    for i, (a, b) in enumerate([(VOID_X[0], xm), (xm, VOID_X[1])]):
        make("IfcPlate", f"{name} pane {i + 1}", [box(a + 0.03, y, FFL_UP, b - 0.03, y + 0.02, VOID_BEAM[0])],
             "glass", predefined="CURTAIN_PANEL", part_of=g)
    make("IfcMember", f"{name} frame", [box(VOID_X[0], y - 0.03, FFL_UP, VOID_X[0] + 0.05, y + 0.05, VOID_BEAM[0]),
                                        box(xm - 0.025, y - 0.03, FFL_UP, xm + 0.025, y + 0.05, VOID_BEAM[0]),
                                        box(VOID_X[1] - 0.05, y - 0.03, FFL_UP, VOID_X[1], y + 0.05, VOID_BEAM[0])],
         "steel", predefined="MULLION", part_of=g)

back = make("IfcWall", "Back facade (dark panels)", [box(SKIN_T, D - SKIN_T, FFL_UP, W - SKIN_T, D, CEIL)],
            "panel", container="UF", predefined="STANDARD")
for k in range(4):
    cx = (k + 0.5) * BAY
    wx0, wx1, wz0, wz1 = cx - 0.65, cx + 0.65, FFL_UP + 0.4, FFL_UP + 2.6
    t, proj = 0.05, 0.35
    frame = [box(wx0, D - SKIN_T, wz0, wx0 + t, D, wz1), box(wx1 - t, D - SKIN_T, wz0, wx1, D, wz1),
             box(wx0, D - SKIN_T, wz0, wx1, D, wz0 + t), box(wx0, D - SKIN_T, wz1 - t, wx1, D, wz1),
             # deep projecting reveal (the dark "boxes" around the back windows)
             box(wx0 - 0.03, D, wz0 - 0.03, wx0, D + proj, wz1 + 0.03), box(wx1, D, wz0 - 0.03, wx1 + 0.03, D + proj, wz1 + 0.03),
             box(wx0 - 0.03, D, wz0 - 0.03, wx1 + 0.03, D + proj, wz0), box(wx0 - 0.03, D, wz1, wx1 + 0.03, D + proj, wz1 + 0.03)]
    glass = [box(wx0 + t, D - 0.08, wz0 + t, wx1 - t, D - 0.06, wz1 - t)]
    window_in(back, f"Back window {k + 1}", "UF", [box(wx0, D - SKIN_T - 0.05, wz0, wx1, D + 0.05, wz1)],
              frame, glass, wx1 - wx0, wz1 - wz0)

for side, xa, xb in [("left", 0.0, SKIN_T), ("right", W - SKIN_T, W)]:
    wall = make("IfcWall", f"Side facade {side} (dark panels)", [box(xa, GLASS_SET, FFL_UP, xb, D - SKIN_T, CEIL)],
                "panel", container="UF", predefined="STANDARD")
    y0, y1, z0, z1 = BAND_Y[0] + 0.3, BAND_Y[1] - 0.3, FFL_UP + 0.3, CEIL - 0.3
    t = 0.05
    frame = [box(xa, y0, z0, xb, y0 + t, z1), box(xa, y1 - t, z0, xb, y1, z1),
             box(xa, y0, z0, xb, y1, z0 + t), box(xa, y0, z1 - t, xb, y1, z1)]
    glass = [box((xa + xb) / 2 - 0.01, y0 + t, z0 + t, (xa + xb) / 2 + 0.01, y1 - t, z1 - t)]
    window_in(wall, f"Side window {side} (corridor)", "UF", [box(xa - 0.05, y0, z0, xb + 0.05, y1, z1)],
              frame, glass, y1 - y0, z1 - z0)

# core: dark enclosure at ground level, partitions upstairs
cx0, cx1 = XM[0] + WALL_T / 2, XM[1] - WALL_T / 2
for y in BAND_Y:
    make("IfcWall", f"Core enclosure GF y={y:g}", [box(cx0, y - 0.05, 0.0, cx1, y + 0.05, BOTTOM)],
         "panel", container="GF", predefined="STANDARD")
    make("IfcWall", f"Core partition UF y={y:g}", [box(cx0, y - 0.05, FFL_UP, cx1, y + 0.05, CEIL)],
         "partition", container="UF", predefined="PARTITIONING")

# front planters and blinds
planters = []
for k in range(4):
    a, b, m = k * BAY + 0.06, (k + 1) * BAY - 0.06, (k + 0.5) * BAY
    for p0, p1 in [(a, m - 0.03), (m + 0.03, b)]:
        planters.append(make("IfcBuildingElementProxy", f"Planter {len(planters) + 1}",
                             [box(p0, 0.10, FFL_UP, p1, GLASS_SET - 0.05, FFL_UP + 0.45)], "planter",
                             container="UF", object_type="Planter"))
for k in range(4):
    a, b = k * BAY + 0.05, (k + 1) * BAY - 0.05
    slats = [box(a, 0.02, z, b, 0.08, z + 0.006) for z in np.arange(CEIL - BLIND_DROP, CEIL, 0.07)]
    slats.append(box(a, 0.0, CEIL, b, 0.10, CEIL + 0.12))   # head box
    make("IfcShadingDevice", f"Front exterior blind {k + 1}", slats, "blind", container="UF", predefined="JALOUSIE")
fins = [box(-0.13, y, BOTTOM, -0.05, y + 0.03, FASCIA_TOP) for y in np.arange(0.10, D - 0.10, 0.15)]
make("IfcShadingDevice", "Side vertical slats (left)", fins, "steel", container="UF", predefined="USERDEFINED")

# ---------------------------------------------------------------- roof garden and railing
garden_hole = rect(XM[1] - WALL_T / 2, BAND_Y[0] - 0.15, XM[2] + WALL_T / 2, BAND_Y[1] + 0.15)
make("IfcCovering", "Green roof", [extrude_z(rect(0.02, 0.02, W - 0.02, D - 0.02), ROOF_TOP, GARDEN_TOP, holes=[garden_hole])],
     "garden", container="RF", predefined="ROOFING")
top, base, ins, r = GARDEN_TOP + RAIL_H, GARDEN_TOP, 0.25, 0.45
xr = W - 1.2
c45 = r * (1 - np.cos(np.pi / 4))
rail_pts = [(xr + r, ins, base), (xr + r, ins, top - r), (xr + r - c45, ins, top - c45), (xr, ins, top),
            (ins, ins, top), (ins, D - ins, top), (xr, D - ins, top),
            (xr + r - c45, D - ins, top - c45), (xr + r, D - ins, top - r), (xr + r, D - ins, base)]
rail = [tube(rail_pts, 0.021, arcs=[(2, 3, 4), (7, 8, 9)])]
posts = [(x, ins) for x in (ins, BAY, 2 * BAY, 3 * BAY)] + [(ins, y) for y in (3.0, 6.0, 9.0)] + \
        [(x, D - ins) for x in (BAY, 2 * BAY, 3 * BAY)]
rail += [tube([(x, y, base), (x, y, top)], 0.012) for x, y in posts]
make("IfcRailing", "Roof railing", rail, "steel", container="RF", predefined="GUARDRAIL", rtype="AdvancedSweptSolid")

# ---------------------------------------------------------------- stairs in the void
def stair(name, x0, x1, y_start, y_end, z_start, z_end, n_risers, container):
    """Open steel stair: n_risers - 1 treads plus two flat stringers, rising from y_start to y_end."""
    rise = (z_end - z_start) / n_risers
    sgn = 1 if y_end > y_start else -1
    going = abs(y_end - y_start) / (n_risers - 1)
    items = []
    for i in range(1, n_risers):
        z = z_start + i * rise
        ya, yb = y_start + sgn * (i - 1) * going, y_start + sgn * i * going
        items.append(box(x0, min(ya, yb) - 0.02, z - 0.03, x1, max(ya, yb) + 0.02, z))
    s = rise / going
    L = abs(y_end - y_start)
    # stringer outline in (y, z): a 0.25 m deep band along the nosing line z = z_start + d*s

    def yz(d, z):
        return (y_start + sgn * d, z)
    outline = [yz(-0.05 / s, z_start), yz(L, z_start + L * s + 0.05),
               yz(L, z_start + L * s - 0.20), yz(0.20 / s, z_start)]
    for xa in (x0, x1 - 0.012):
        items.append(extrude_x(outline, xa, xa + 0.012))
    el = make("IfcStair", name, items, "steel", container=container, predefined="STRAIGHT_RUN_STAIR")
    el.Description = f"{n_risers} risers x {rise:.3f} m, going {going:.3f} m"
    return el


stair("Stair ground -> upper floor", VOID_X[0] + 0.08, VOID_X[0] + 0.98, BAND_Y[1] + 1.0, BAND_Y[0] + 1.0,
      0.0, FFL_UP, 17, "GF")
stair("Stair upper floor -> roof", VOID_X[1] - 0.98, VOID_X[1] - 0.08, BAND_Y[0] + 1.0, BAND_Y[1] + 0.15,
      FFL_UP, VOID_BEAM[1], 22, "UF")

# ---------------------------------------------------------------- spaces
def space(name, long_name, key, x0, y0, x1, y1, z0, z1, external=False):
    s = make("IfcSpace", name, [box(x0, y0, z0, x1, y1, z1)], "space", space_of=storeys[key],
             predefined="EXTERNAL" if external else "INTERNAL")
    s.LongName = long_name
    return s


space("GF-1", "Sanitary core (ground)", "GF", cx0, BAND_Y[0] + 0.05, cx1, BAND_Y[1] - 0.05, 0.0, BOTTOM)
space("GF-2", "Covered terrace (front)", "GF", 0, 0, W, BAND_Y[0], 0.0, BOTTOM, external=True)
space("GF-3", "Covered terrace (back)", "GF", 0, BAND_Y[1], W, D, 0.0, BOTTOM, external=True)
space("GF-4", "Circulation void", "GF", VOID_X[0], BAND_Y[0], VOID_X[1], BAND_Y[1], 0.0, ROOF_TOP, external=True)
space("UF-1", "Living / kitchen (front zone)", "UF", SKIN_T, GLASS_SET + 0.02, W - SKIN_T, BAND_Y[0] - 0.02, FFL_UP, CEIL)
space("UF-2", "Bedrooms (back zone)", "UF", SKIN_T, BAND_Y[1] + 0.02, W - SKIN_T, D - SKIN_T, FFL_UP, CEIL)
space("UF-3", "Sanitary core (bathrooms)", "UF", cx0, BAND_Y[0] + 0.05, cx1, BAND_Y[1] - 0.05, FFL_UP, CEIL)
space("UF-4", "Side zone (left)", "UF", SKIN_T, BAND_Y[0], XM[0] - WALL_T / 2, BAND_Y[1], FFL_UP, CEIL)
space("UF-5", "Corridor (right)", "UF", XM[2] + WALL_T / 2, BAND_Y[0], W - SKIN_T, BAND_Y[1], FFL_UP, CEIL)

# ---------------------------------------------------------------- MEP (schematic design proposal)
from casa_ato_mep import add_mep  # noqa: E402  (scripts/ is on sys.path when run as a script)

mep_counts = add_mep(f, body, storeys, dict(
    W=W, D=D, BAY=BAY, FFL_UP=FFL_UP, CEIL=CEIL, ROOF_TOP=ROOF_TOP, GARDEN_TOP=GARDEN_TOP, BOTTOM=BOTTOM))

# ---------------------------------------------------------------- provenance
pset = api.pset.add_pset(f, product=project, name="CasaATO_Provenance")
api.pset.edit_pset(f, pset=pset, properties={
    "Architects": "IR arquitectura",
    "Location": "San Isidro, Buenos Aires, Argentina (facing the Bajo de San Isidro ecological reserve)",
    "Period": "2016-2020",
    "Sources": "estebanbasili.com/work/ir-arquitectura/casa-ato (text + 22 photos); archdaily.com/1018863 (49 photos)",
    "Photographer": "Fernando Schapochnik",
    "Method": "Reconstructed from photographs; no drawings available. Generated by scripts/build_casa_ato.py",
    "DimensionalAccuracy": "Estimated, roughly +/-15 percent",
    "KeyAssumptions": f"Box {W} x {D} m in 4 bays of {BAY:.2f} m; front/back hung zones {ZONE} m deep; "
                      f"upper FFL {FFL_UP} m; roof slab top {ROOF_TOP} m; interior layout beyond the core is not modelled.",
    "MEP": "Schematic design proposal (scripts/casa_ato_mep.py), not as-built: systems named in the project text "
           "(groundwater heat pump, PV, blinds, automation, irrigation) plus water, drainage, extract and electrical "
           "routed to fit the reconstructed plan. Gravity drains drawn level.",
})

OUT.parent.mkdir(exist_ok=True)
f.write(str(OUT))
print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB), {len(list(f.by_type('IfcProduct')))} products")
print("MEP:", ", ".join(f"{k.removeprefix('Ifc')} {v}" for k, v in sorted(mep_counts.items())))
