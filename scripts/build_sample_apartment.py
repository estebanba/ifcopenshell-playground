"""Build an IFC4 interior model of the Sample apartment from its CADCraft drawing.

    python3 scripts/cadcraft_read.py drawings/sample_apartment.entities.json   # read the live drawing
    uv run python scripts/build_sample_apartment.py                               # writes models/sample_apartment.ifc
    uv run python scripts/build_sample_apartment.py --live                        # both steps in one

Input is the JSON written by scripts/cadcraft_read.py (every model-space entity, with its handle
and geometry). The drawing is in millimetres, the model in metres, and the drawing's coordinates
are kept, so x/y in the model equal the drawing's x/y divided by 1000.

How the plan is read:
- Wall linework is layer 0, plus short (jamb-length) pieces on any layer. Furniture and door
  leaves drawn on layer 0 are listed in NOT_WALL so they don't split rooms.
- Door gaps are closed between their two jambs: pairs of parallel jamb pieces 0.6-1.7 m
  apart with nothing between them. The wall linework is then polygonized into faces.
- Faces are classified by "thickness", 2 * area / perimeter. Thin faces under 0.5 m2 are
  openings: a door if a swing arc is hinged on it or it came from a jamb pair, otherwise a
  window. One exception: a thin face whose two ends both touch other openings is a pier
  (wall). Other thin faces are walls, and thick faces are rooms.
- Rooms are named from TEXT inside them when the drawing has some. Otherwise ROOM_SEEDS
  gives a name per room, and the rest become "Room n".
- Furniture comes from FURNITURE, keyed by entity handle. Closed outlines on layer Proy that
  aren't listed become "Unclassified item" boxes, so new items still show up.

Heights are not in a plan. They are the assumptions below.

GlobalIds are derived from the drawing's entity handles (or, for walls and openings, their
position). Rebuilding after a drawing edit keeps each unchanged element's GlobalId.
"""

import argparse
import json
import math
import subprocess
import sys
import uuid
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
import ifcopenshell.guid
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "drawings" / "sample_apartment.entities.json"
OUT = ROOT / "models" / "sample_apartment.ifc"

# ---------------------------------------------------------------- assumed heights (m), not in the plan
CEIL = 2.70          # clear ceiling height
DOOR_H = 2.10        # door head
WIN_SILL = 0.90
WIN_HEAD = 2.30      # also the head of the French door to the terrace
FINISH_T = 0.02      # floor and ceiling finish thickness (drawn below the floor / above the ceiling)

# ---------------------------------------------------------------- reading the plan (drawing units: mm)
JAMB = (200, 460)        # length of a jamb piece = wall thickness
OPENING_W = (600, 1700)  # clear width of a door or window
DOOR_R = (500, 1000)     # radius of a door swing arc
THIN = 450               # 2A/P below this: wall or opening, above: room
OPENING_MAX_AREA = 0.5e6

# Furniture, fixtures and door leaves drawn on layer 0. They are not walls.
NOT_WALL = {"55C", "56B", "56D", "5D7", "5D8", "565", "5B1", "5BA", "5E3", "5F4"}

# Room names: the drawing has no text yet, so a point inside each room (drawing mm) names it.
ROOM_SEEDS = {
    "Living / dining": (-1500, 16000),
    "Bedroom 1": (-5000, 16000),
    "Main bedroom": (-3000, 9500),
    "Walk-in closet": (-7400, 10500),
    "Bedroom 2": (-2500, 6800),
    "Bathroom": (-2500, 4500),
    "Kitchen": (-2700, 1800),
    "Corridor": (0, 6000),
    "Terrace": (-3000, 22000),
}
EXTERNAL_ROOMS = {"Terrace"}

# handle -> (IFC class, predefined type, name, z0, z1). Names with "?" are guesses from shape and size.
FURNITURE = {
    # bedroom 1
    "5F7": ("IfcFurniture", "BED", "L-shaped bed/bench? (part 1)", 0.0, 0.45),
    "5F9": ("IfcFurniture", "BED", "L-shaped bed/bench? (part 2)", 0.0, 0.45),
    "603": ("IfcFurniture", "DESK", "Desk? 1200x600", 0.0, 0.75),
    "601": ("IfcFurniture", "USERDEFINED", "Radiator? 800x150", 0.15, 0.75),
    "5FE": ("IfcFurniture", "SHELF", "Shelf? 1220x300", 0.0, 1.80),
    "5FB": ("IfcFurniture", "USERDEFINED", "Chest of drawers? 1000x520", 0.0, 0.90),
    # living / dining
    "6A7": ("IfcFurniture", "SOFA", "L-sofa (long part)", 0.0, 0.80),
    "6A9": ("IfcFurniture", "SOFA", "L-sofa (return)", 0.0, 0.80),
    "6BE": ("IfcCovering", "FLOORING", "Round rug", 0.0, 0.01),
    "6BD": ("IfcFurniture", "TABLE", "Dining table 1400x800", 0.0, 0.75),
    "6C2": ("IfcFurniture", "CHAIR", "Dining chair", 0.0, 0.45),
    "6C3": ("IfcFurniture", "CHAIR", "Dining chair", 0.0, 0.45),
    "6C5": ("IfcFurniture", "CHAIR", "Dining chair", 0.0, 0.45),
    "6C6": ("IfcFurniture", "CHAIR", "Dining chair", 0.0, 0.45),
    # main bedroom
    "6CB": ("IfcFurniture", "BED", "Bed with side tables? 2700x2000", 0.0, 0.50),
    "6C9": ("IfcFurniture", "USERDEFINED", "Wardrobe 3800x600", 0.0, 2.40),
    "6E7": ("IfcFurniture", "USERDEFINED", "Bench or dresser? 1600x700", 0.0, 0.75),
    "6E9": ("IfcFurniture", "DESK", "Desk? 1600x700", 0.0, 0.75),
    "6CD": ("IfcFurniture", "USERDEFINED", "Rounded unit? 1600x400", 0.0, 0.90),
    # bedroom 2
    "5E1": ("IfcFurniture", "BED", "Double bed 1600x2000", 0.0, 0.50),
    "670": ("IfcFurniture", "USERDEFINED", "Wardrobe 1400x700", 0.0, 2.10),
    "6E3": ("IfcFurniture", "USERDEFINED", "Side table?", 0.0, 0.50),
    # bathroom (open outlines, closed against the walls)
    "55C": ("IfcSanitaryTerminal", "BATH", "Bath 1700x700", 0.0, 0.55),
    "56B": ("IfcSanitaryTerminal", "WASHHANDBASIN", "Vanity with basin 850x500", 0.0, 0.85),
    "565": ("IfcSanitaryTerminal", "TOILETPAN", "WC", 0.0, 0.40),
    # kitchen
    "56D": ("IfcFurniture", "USERDEFINED", "Kitchen counter", 0.0, 0.90),
    "732": ("IfcFurniture", "TABLE", "Round table Ø1200", 0.0, 0.75),
    "78B": ("IfcFurniture", "CHAIR", "Chair", 0.0, 0.45),   # block of 4 chairs, see chairs_78B()
}
IGNORE = {"5E8", "56E"}   # bedroom-2 duvet line; a box outside the flat (doormat?)


def chairs_78B(table_c):
    """The chairs block (*U…) nests 4 chairs whose geometry MCP doesn't return. Read once from a
    DXF copy: 430 mm chairs, rotated 45°, at (±530, ±530) mm from the round table's centre."""
    out = []
    for sx, sy in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
        c = (table_c[0] + sx * 530, table_c[1] + sy * 530)
        sq = [(c[0] + 304 * math.cos(math.radians(a)), c[1] + 304 * math.sin(math.radians(a)))
              for a in (0, 90, 180, 270)]
        out.append(Polygon(sq))
    return out


# ---------------------------------------------------------------- drawing geometry
def P(p):
    return (round(p["x"], 1), round(p["y"], 1))


def bulge_pts(a, b, bulge, n=8):
    """Points along a polyline arc segment from a to b (bulge = tan(angle/4)), excluding a."""
    if abs(bulge) < 1e-9:
        return [b]
    ang = 4 * math.atan(bulge)
    chord = math.dist(a, b)
    r = chord / (2 * math.sin(ang / 2))
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    d = r * math.cos(ang / 2)
    ux, uy = (b[0] - a[0]) / chord, (b[1] - a[1]) / chord
    cx, cy = mx - uy * d, my + ux * d
    a0 = math.atan2(a[1] - cy, a[0] - cx)
    return [(cx + abs(r) * math.cos(a0 + ang * i / n), cy + abs(r) * math.sin(a0 + ang * i / n))
            for i in range(1, n + 1)]


def vertices(g):
    vs = g["vertices"]
    pts = [P(vs[0]["p"])]
    pairs = list(zip(vs, vs[1:] + ([vs[0]] if g["closed"] else [])))
    for v, w in pairs:
        pts += bulge_pts(P(v["p"]), P(w["p"]), v["bulge"])
    return pts


def outline(e):
    """A closed shapely polygon for an entity, if it has one."""
    g = e["geometry"]
    if g["type"] == "lwPolyline":
        pts = vertices(g)
        return Polygon(pts).buffer(0) if len(pts) >= 3 else None
    if g["type"] == "circle":
        return Point(P(g["center"])).buffer(g["radius"], 32)
    if g["type"] == "arc":   # a rug or a fixture drawn as an arc: use the full circle
        return Point(P(g["center"])).buffer(g["radius"], 32)
    return None


def read_plan(entities):
    E = {e["handle"]: e for e in entities}
    segs = []
    for h, e in E.items():
        g = e["geometry"]
        if h in NOT_WALL or h in IGNORE or h in FURNITURE:
            continue
        if g["type"] == "line" and e["layer"] == "0":
            segs.append([P(g["a"]), P(g["b"])])
        elif g["type"] == "lwPolyline" and not g["closed"]:
            pts = vertices(g)
            if e["layer"] == "0" or (len(pts) == 2 and math.dist(*pts) <= JAMB[1]):
                segs.append(pts)
    net = unary_union([LineString(s) for s in segs])

    # close door gaps between jamb pairs
    pieces = [(a, b) for s in segs for a, b in zip(s, s[1:])]
    jambs = [(a, b) for a, b in pieces
             if JAMB[0] <= math.dist(a, b) <= JAMB[1] and (abs(a[0] - b[0]) < 1 or abs(a[1] - b[1]) < 1)]
    added, gap_boxes = [], []
    for i, (p1, q1) in enumerate(jambs):
        for p2, q2 in jambs[i + 1:]:
            for p2, q2 in [(p2, q2), (q2, p2)]:
                v1 = (q1[0] - p1[0], q1[1] - p1[1])
                v2 = (q2[0] - p2[0], q2[1] - p2[1])
                off = (p2[0] - p1[0], p2[1] - p1[1])
                L = math.hypot(*off)
                if math.dist(v1, v2) > 2 or not OPENING_W[0] <= L <= OPENING_W[1]:
                    continue
                if abs(off[0] * v1[0] + off[1] * v1[1]) > 2:
                    continue
                if any(LineString([(p1[0] + off[0] * t, p1[1] + off[1] * t),
                                   (q1[0] + off[0] * t, q1[1] + off[1] * t)]).intersects(net) for t in (0.3, 0.5, 0.7)):
                    continue
                added += [[p1, p2], [q1, q2]]
                gap_boxes.append(Polygon([p1, q1, q2, p2]))
    faces = list(polygonize(unary_union([LineString(s) for s in segs + added])))

    arcs = [e for e in E.values() if e["geometry"]["type"] == "arc"
            and DOOR_R[0] <= e["geometry"]["radius"] <= DOOR_R[1] and e["handle"] not in FURNITURE]

    def thick(f):
        return 2 * f.area / f.length

    rooms = [f for f in faces if thick(f) >= THIN]
    thin = [f for f in faces if thick(f) < THIN]
    cand = [f for f in thin if f.area < OPENING_MAX_AREA]
    walls = [f for f in thin if f.area >= OPENING_MAX_AREA]
    openings = []
    for f in cand:
        hinges = [a for a in arcs if f.exterior.distance(Point(P(a["geometry"]["center"]))) < 5]
        x0, y0, x1, y1 = f.bounds
        width = max(x1 - x0, y1 - y0)
        if abs(width - sum(a["geometry"]["radius"] for a in hinges)) > 60:
            hinges = []      # a hinge on the edge of a neighbouring pier: the leaves don't span this face
        from_gap = any(f.symmetric_difference(b).area < 1e3 for b in gap_boxes)
        if hinges or from_gap:
            openings.append(("door", f, hinges))
            continue
        touching = [o for o in cand if o is not f and f.intersection(o).length > 100]
        if len(touching) >= 2:
            walls.append(f)          # a pier between two openings
        else:
            openings.append(("window", f, []))
    return E, rooms, walls, openings


# ---------------------------------------------------------------- IFC helpers
f = None
body = None
storey = None
MATS = {}
NS = uuid.UUID("5b0b6c2e-8f1e-4c55-9a43-6f0e6d1c2a10")


def gid(key):
    return ifcopenshell.guid.compress(uuid.uuid5(NS, key).hex)


def m(p):
    return (p[0] / 1000.0, p[1] / 1000.0)


def P3(x, y, z):
    return f.createIfcCartesianPoint((float(x), float(y), float(z)))


def Dir(*v):
    return f.createIfcDirection(tuple(float(a) for a in v))


def polyline(pts):
    pts = [m(p) for p in pts]
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    pts = pts + [pts[0]]
    return f.createIfcPolyline([f.createIfcCartesianPoint((float(a), float(b))) for a, b in pts])


def extrude(poly, z0, z1):
    poly = poly.simplify(0.5)
    outer = list(poly.exterior.coords)
    holes = [list(r.coords) for r in poly.interiors]
    prof = (f.createIfcArbitraryProfileDefWithVoids("AREA", None, polyline(outer), [polyline(h) for h in holes])
            if holes else f.createIfcArbitraryClosedProfileDef("AREA", None, polyline(outer)))
    pos = f.createIfcAxis2Placement3D(P3(0, 0, z0), None, None)
    return f.createIfcExtrudedAreaSolid(prof, pos, Dir(0, 0, 1), float(z1 - z0))


def make(ifc_class, name, key, polys, z0, z1, mat, predefined=None, object_type=None):
    el = api.root.create_entity(f, ifc_class=ifc_class, name=name, predefined_type=predefined)
    el.GlobalId = gid(key)
    if object_type:
        el.ObjectType = object_type
    if ifc_class == "IfcSpace":
        api.aggregate.assign_object(f, products=[el], relating_object=storey)
    elif ifc_class != "IfcOpeningElement":
        api.spatial.assign_container(f, products=[el], relating_structure=storey)
    api.geometry.edit_object_placement(f, product=el, matrix=np.eye(4))
    items = [extrude(p, z0, z1) for p in polys]
    rep = f.createIfcShapeRepresentation(body, "Body", "SweptSolid", items)
    api.geometry.assign_representation(f, product=el, representation=rep)
    api.style.assign_representation_styles(f, shape_representation=rep, styles=[MATS[mat][1]])
    if ifc_class not in ("IfcOpeningElement", "IfcSpace"):
        api.material.assign_material(f, products=[el], type="IfcMaterial", material=MATS[mat][0])
    return el


def build(entities, title):
    global f, body, storey
    E, rooms, walls, openings = read_plan(entities)

    f = api.project.create_file(version="IFC4")
    project = api.root.create_entity(f, ifc_class="IfcProject", name="Sample apartment")
    project.GlobalId = gid("project")
    project.Description = f"Interior model generated from the CADCraft drawing {title} by scripts/build_sample_apartment.py"
    api.unit.assign_unit(f, length={"is_metric": True, "raw": "METERS"},
                         area={"is_metric": True, "raw": "SQUARE_METERS"},
                         volume={"is_metric": True, "raw": "CUBIC_METERS"})
    model = api.context.add_context(f, context_type="Model")
    body = api.context.add_context(f, context_type="Model", context_identifier="Body",
                                   target_view="MODEL_VIEW", parent=model)
    site = api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    building = api.root.create_entity(f, ifc_class="IfcBuilding", name="Sample apartment")
    storey = api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Apartment")
    for el, key in [(site, "site"), (building, "building"), (storey, "storey")]:
        el.GlobalId = gid(key)
    storey.Elevation = 0.0
    api.aggregate.assign_object(f, products=[site], relating_object=project)
    api.aggregate.assign_object(f, products=[building], relating_object=site)
    api.aggregate.assign_object(f, products=[storey], relating_object=building)
    for el in (site, building, storey):
        api.geometry.edit_object_placement(f, product=el, matrix=np.eye(4))

    for key, name, cat, rgb, tr in [
        ("wall", "Plastered wall", "plaster", (0.93, 0.92, 0.89), 0.0),
        ("floor", "Wood floor", "wood", (0.72, 0.58, 0.42), 0.0),
        ("tiles", "Floor tiles", "ceramic", (0.80, 0.80, 0.78), 0.0),
        ("deck", "Terrace paving", "concrete", (0.62, 0.62, 0.60), 0.0),
        ("ceiling", "Ceiling, painted", "plaster", (0.97, 0.97, 0.96), 0.0),
        ("wood", "Wood, light", "wood", (0.82, 0.70, 0.52), 0.0),
        ("fabric", "Upholstery", "textile", (0.45, 0.50, 0.55), 0.0),
        ("rug", "Rug", "textile", (0.70, 0.62, 0.55), 0.0),
        ("white", "White lacquer", "", (0.96, 0.96, 0.95), 0.0),
        ("ceramic", "Sanitary ceramic", "ceramic", (0.98, 0.98, 0.98), 0.0),
        ("door", "Door leaf, painted", "wood", (0.90, 0.89, 0.86), 0.0),
        ("glass", "Glass", "glass", (0.55, 0.66, 0.72), 0.65),
        ("space", "Space", "", (0.85, 0.75, 0.40), 0.85),
        ("unknown", "Unclassified", "", (0.95, 0.30, 0.30), 0.0),
    ]:
        mat = api.material.add_material(f, name=name, category=cat or None)
        st = api.style.add_style(f, name=name)
        api.style.add_surface_style(f, style=st, ifc_class="IfcSurfaceStyleShading", attributes={
            "SurfaceColour": {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]},
            "Transparency": tr})
        MATS[key] = (mat, st)

    # ---- rooms
    texts = [(e, P(e["geometry"].get("insert") or e["geometry"].get("p") or {"x": 0, "y": 0}))
             for e in E.values() if e["type"] in ("Text", "MText") and e["geometry"].get("text")]
    report = []
    unnamed = 0
    for poly in sorted(rooms, key=lambda r: -r.area):
        name = next((e["geometry"]["text"] for e, p in texts if poly.contains(Point(p))), None)
        name = name or next((n for n, s in ROOM_SEEDS.items() if poly.contains(Point(s))), None)
        if not name:
            unnamed += 1
            name = f"Room {unnamed}"
        ext = name in EXTERNAL_ROOMS
        rp = poly.representative_point()
        top = 0.0 if ext else CEIL
        sp = make("IfcSpace", name, f"space:{name}", [poly], 0.0, CEIL, "space",
                  predefined="EXTERNAL" if ext else "INTERNAL")
        sp.LongName = name
        q = api.pset.add_qto(f, product=sp, name="Qto_SpaceBaseQuantities")
        api.pset.edit_qto(f, qto=q, properties={"NetFloorArea": round(poly.area / 1e6, 3),
                                                "NetPerimeter": round(poly.length / 1000, 3),
                                                "Height": 0.0 if ext else CEIL})
        floor_mat = "deck" if ext else ("tiles" if name in ("Bathroom", "Kitchen") else "floor")
        make("IfcCovering", f"Floor - {name}", f"floor:{name}", [poly], -FINISH_T, 0.0, floor_mat,
             predefined="FLOORING")
        if not ext:
            make("IfcCovering", f"Ceiling - {name}", f"ceiling:{name}", [poly], CEIL, CEIL + FINISH_T,
                 "ceiling", predefined="CEILING")
        report.append((name, poly.area / 1e6, poly.bounds, (rp.x, rp.y), top))

    # ---- walls (wall faces plus the openings they host)
    for poly in walls:
        c = poly.representative_point()
        make("IfcWall", "Wall", f"wall:{round(c.x, -2)}:{round(c.y, -2)}", [poly], 0.0, CEIL, "wall",
             predefined="SOLIDWALL")
    for kind, poly, hinges in openings:
        x0, y0, x1, y1 = poly.bounds
        along_x = (x1 - x0) > (y1 - y0)
        width = (x1 - x0) if along_x else (y1 - y0)
        c = poly.centroid
        key = f"{kind}:{round(c.x, -1)}:{round(c.y, -1)}"
        head = DOOR_H if kind == "door" and len(hinges) < 2 else WIN_HEAD
        sill = 0.0 if kind == "door" else WIN_SILL
        # the opening's own wall piece: what remains of it after the cut is the sill and lintel
        piece = make("IfcWall", "Wall", f"wallpiece:{key}", [poly], 0.0, CEIL, "wall", predefined="SOLIDWALL")
        cut = poly.buffer(20, join_style=2)
        op = make("IfcOpeningElement", f"{kind.title()} opening", f"opening:{key}", [cut], sill, head, "glass",
                  predefined="OPENING")
        api.feature.add_feature(f, feature=op, element=piece)
        if kind == "door":
            leaves = []
            if hinges:
                for a in hinges:
                    g = a["geometry"]
                    cx, cy = P(g["center"])
                    r = g["radius"]
                    # closed leaf: from the hinge towards the opening's middle, flush with the hinge's wall face
                    if along_x:
                        s = 1 if c.x > cx else -1
                        t = 40 if abs(cy - y0) < abs(cy - y1) else -40
                        leaves.append(Polygon([(cx, cy), (cx + s * r, cy), (cx + s * r, cy + t), (cx, cy + t)]))
                    else:
                        s = 1 if c.y > cy else -1
                        t = 40 if abs(cx - x0) < abs(cx - x1) else -40
                        leaves.append(Polygon([(cx, cy), (cx, cy + s * r), (cx + t, cy + s * r), (cx + t, cy)]))
            else:
                mid = (y0 + y1) / 2 if along_x else (x0 + x1) / 2
                leaves.append(Polygon([(x0, mid - 20), (x1, mid - 20), (x1, mid + 20), (x0, mid + 20)]) if along_x
                              else Polygon([(mid - 20, y0), (mid + 20, y0), (mid + 20, y1), (mid - 20, y1)]))
            fill = make("IfcDoor", "Door" if hinges else "Entrance door", f"door-el:{key}",
                        [l.buffer(0) for l in leaves], 0.0, head, "door",
                        predefined="DOOR")
            fill.OverallWidth, fill.OverallHeight = width / 1000, head
            fill.OperationType = "DOUBLE_DOOR_SINGLE_SWING" if len(hinges) == 2 else "SINGLE_SWING_LEFT"
        else:
            mid = (y0 + y1) / 2 if along_x else (x0 + x1) / 2
            pane = (Polygon([(x0, mid - 15), (x1, mid - 15), (x1, mid + 15), (x0, mid + 15)]) if along_x
                    else Polygon([(mid - 15, y0), (mid + 15, y0), (mid + 15, y1), (mid - 15, y1)]))
            fill = make("IfcWindow", "Window", f"window-el:{key}", [pane], sill, head, "glass", predefined="WINDOW")
            fill.OverallWidth, fill.OverallHeight = width / 1000, head - sill
        api.feature.add_filling(f, opening=op, element=fill)

    # ---- furniture
    counts = {}
    unclassified = []
    rooms_union = unary_union(rooms)
    for h, e in E.items():
        spec = FURNITURE.get(h)
        if spec is None:
            if e["layer"] == "Proy" and e["geometry"]["type"] == "lwPolyline" and e["geometry"]["closed"]:
                spec = ("IfcFurniture", "USERDEFINED", f"Unclassified item {h}", 0.0, 0.40)
                unclassified.append(h)
            else:
                continue
        cls, pre, name, z0, z1 = spec
        if h == "78B":
            table = E.get("732")
            if not table:
                continue
            polys = chairs_78B(P(table["geometry"]["center"]))
            for i, poly in enumerate(polys):
                make(cls, f"{name} {i + 1}", f"furn:{h}:{i}", [poly], z0, z1, "wood", predefined=pre)
            counts[cls] = counts.get(cls, 0) + len(polys)
            continue
        poly = outline(e)
        if poly is None and e["geometry"]["type"] == "lwPolyline":     # open outline closed by the wall
            pts = vertices(e["geometry"])
            if len(pts) >= 3:
                poly = Polygon(pts).buffer(0)
            elif h == "56D":   # counter front edge: a 600 mm deep counter on the side that lies in a room
                line = LineString(pts)
                sides = [line.buffer(s * 600, single_sided=True, cap_style=2) for s in (1, -1)]
                poly = max(sides, key=lambda p: p.intersection(rooms_union).area)
        if h == "565":                                                   # WC: arc plus its two side lines
            g = e["geometry"]
            cx, cy = P(g["center"])
            poly = unary_union([Point(cx, cy).buffer(g["radius"], 24),
                                Polygon([(cx - 250, cy - 257), (cx + 250, cy - 257), (cx + 250, cy), (cx - 250, cy)])])
            poly = poly.intersection(Polygon([(cx - 300, cy - 257), (cx + 300, cy - 257),
                                              (cx + 300, cy + 300), (cx - 300, cy + 300)]))
        if poly is None or poly.is_empty:
            print(f"  skipped {h} ({name}): no outline")
            continue
        if h == "6BE":                                                   # rug: keep the visible part
            mat = "rug"
        elif cls == "IfcSanitaryTerminal":
            mat = "ceramic"
        elif pre in ("SOFA", "BED"):
            mat = "fabric"
        elif pre == "USERDEFINED" and name.startswith("Unclassified"):
            mat = "unknown"
        elif "Wardrobe" in name or "counter" in name:
            mat = "white"
        else:
            mat = "wood"
        make(cls, name, f"furn:{h}", [poly], z0, z1, mat, predefined=pre,
             object_type=name if pre == "USERDEFINED" else None)
        counts[cls] = counts.get(cls, 0) + 1

    pset = api.pset.add_pset(f, product=project, name="SampleApartment_Provenance")
    api.pset.edit_pset(f, pset=pset, properties={
        "SourceDrawing": title,
        "Method": "Plan read from CADCraft over MCP (scripts/cadcraft_read.py); walls, rooms and openings derived "
                  "by polygonizing the wall linework; furniture classified by entity handle.",
        "AssumedHeights": f"ceiling {CEIL} m, door head {DOOR_H} m, window sill {WIN_SILL} m, window head {WIN_HEAD} m",
    })
    return report, len(walls), openings, counts, unclassified


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=str(SRC), help="entities JSON from cadcraft_read.py")
    ap.add_argument("--live", action="store_true", help="read the running CADCraft first")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    if a.live:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "cadcraft_read.py"), a.src], check=True)
    data = json.loads(Path(a.src).read_text())
    report, n_walls, openings, counts, unclassified = build(data["entities"], data["drawing"].get("title", "?"))
    Path(a.out).parent.mkdir(exist_ok=True)
    f.write(a.out)

    print(f"wrote {a.out}")
    for name, area, b, _, _ in report:
        print(f"  {name:18s} {area:6.2f} m2   {(b[2] - b[0]):5.0f} x {(b[3] - b[1]):5.0f} mm (bounding box)")
    doors = sum(1 for k, *_ in openings if k == "door")
    print(f"  walls {n_walls}, doors {doors}, windows {len(openings) - doors}, "
          + ", ".join(f"{k.removeprefix('Ifc')} {v}" for k, v in sorted(counts.items())))
    if unclassified:
        print(f"  unclassified Proy outlines (add them to FURNITURE): {', '.join(unclassified)}")


if __name__ == "__main__":
    main()
