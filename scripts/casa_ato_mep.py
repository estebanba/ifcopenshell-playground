"""Schematic MEP for the Casa ATO model (called from build_casa_ato.py).

This is a DESIGN PROPOSAL, not an as-built record. No MEP is visible in the photos. The
project text names these systems: a groundwater (geothermal) heat pump, photovoltaics,
robotic blinds, home automation, lighting, security and irrigation. Everything else is
designed to fit the reconstructed plan.

Strategy:
- Plant room: the ground-floor sanitary core.
- Service shaft: one shaft in the core's back-left corner carries every riser.
- Upper floor: water and heating run as PEX home runs and loops in the floor build-up.
- Drainage: a single soil stack down the shaft, vented through the roof garden.
- Ventilation: natural cross-ventilation, as the text describes, so there is no MVHR.
  Only bathroom and kitchen extracts.
- Simplifications: gravity drains are drawn level, not sloped; switches and control wiring
  are not routed; the devices are grouped logically into their systems.

Modelling:
- Rigid networks (drainage, groundwater, primary heating, ducts, trays, pool, mains) are
  IfcPipe/Duct/CableCarrier segments joined by bends, tees and multi-inlet junctions.
- Flexible runs (PEX loops and home runs, drip lines, cables) are each one continuous
  segment.
- Every segment, fitting and device carries IfcDistributionPorts, connected with
  IfcRelConnectsPorts in the flow direction, and is assigned to an IfcDistributionSystem.
"""

import math
from types import SimpleNamespace

import numpy as np
import ifcopenshell
import ifcopenshell.api as api
import ifcopenshell.api.geometry  # noqa: F401
import ifcopenshell.api.material  # noqa: F401
import ifcopenshell.api.root  # noqa: F401
import ifcopenshell.api.spatial  # noqa: F401
import ifcopenshell.api.style  # noqa: F401
import ifcopenshell.api.system  # noqa: F401

# system key -> (Name, PredefinedType, ObjectType for USERDEFINED, colour, port SystemType)
SYSTEMS = {
    "GW":   ("Geothermal groundwater (open loop)", "USERDEFINED", "Groundwater source", (0.10, 0.55, 0.45)),
    "SRC":  ("Heat pump source loop", "CONDENSERWATER", None, (0.20, 0.70, 0.55)),
    "HTG":  ("Radiant floor heating / cooling", "HEATING", None, (0.95, 0.45, 0.10)),
    "DCW":  ("Domestic cold water", "DOMESTICCOLDWATER", None, (0.10, 0.35, 0.95)),
    "DHW":  ("Domestic hot water", "DOMESTICHOTWATER", None, (0.90, 0.10, 0.10)),
    "SAN":  ("Sanitary drainage and vent", "DRAINAGE", None, (0.45, 0.28, 0.12)),
    "RW":   ("Rainwater harvesting", "RAINWATER", None, (0.10, 0.75, 0.90)),
    "IRR":  ("Irrigation (from rainwater cistern)", "WATERSUPPLY", None, (0.45, 0.80, 0.10)),
    "POOL": ("Pool filtration", "USERDEFINED", "Pool filtration", (0.30, 0.50, 0.85)),
    "EXH":  ("Bathroom and kitchen extract", "EXHAUST", None, (0.75, 0.75, 0.10)),
    "ELEC": ("Power distribution", "ELECTRICAL", None, (0.95, 0.70, 0.00)),
    "LTG":  ("Lighting", "LIGHTING", None, (1.00, 0.90, 0.40)),
    "PV":   ("Photovoltaic generation", "POWERGENERATION", None, (0.85, 0.35, 0.65)),
    "CTRL": ("Home automation (KNX)", "CONTROL", None, (0.55, 0.25, 0.85)),
    "SEC":  ("Security and fire detection", "SECURITY", None, (0.90, 0.25, 0.55)),
}

KINDS = {  # kind -> (segment class, segment type, fitting class, port type, rigid?)
    "pipe":    ("IfcPipeSegment", "RIGIDSEGMENT", "IfcPipeFitting", "PIPE", True),
    "pex":     ("IfcPipeSegment", "FLEXIBLESEGMENT", None, "PIPE", False),
    "duct":    ("IfcDuctSegment", "RIGIDSEGMENT", "IfcDuctFitting", "DUCT", True),
    "tray":    ("IfcCableCarrierSegment", "CABLETRAYSEGMENT", "IfcCableCarrierFitting", "CABLECARRIER", True),
    "conduit": ("IfcCableCarrierSegment", "CONDUITSEGMENT", None, "CABLECARRIER", False),
    "cable":   ("IfcCableSegment", "CABLESEGMENT", None, "CABLE", False),
}


class MEP:
    def __init__(self, f, body, storeys, d):
        self.f, self.body, self.storeys = f, body, storeys
        self.d = SimpleNamespace(**d) if isinstance(d, dict) else d
        self.styles, self.systems, self.count = {}, {}, {}
        for key, (name, ptype, otype, rgb) in SYSTEMS.items():
            s = api.system.add_system(f, ifc_class="IfcDistributionSystem")
            s.Name, s.PredefinedType = name, ptype
            if otype:
                s.ObjectType = otype
            self.systems[key] = s
            self.styles[key] = self._style(f"MEP {name}", rgb)
        self.styles["equip"] = self._style("MEP equipment", (0.78, 0.80, 0.82))
        self.styles["fixture"] = self._style("Sanitary ware", (0.96, 0.96, 0.96))
        self.styles["pv"] = self._style("PV module", (0.08, 0.10, 0.22))
        self.styles["light"] = self._style("Luminaire", (1.0, 0.97, 0.80))
        self.styles["device"] = self._style("Device", (0.20, 0.20, 0.22))

    # ------------------------------------------------------------ low level
    def _style(self, name, rgb, tr=0.0):
        st = api.style.add_style(self.f, name=name)
        api.style.add_surface_style(self.f, style=st, ifc_class="IfcSurfaceStyleShading", attributes={
            "SurfaceColour": {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]}, "Transparency": tr})
        return st

    def P(self, p):
        return self.f.createIfcCartesianPoint(tuple(float(c) for c in p))

    def D(self, v):
        return self.f.createIfcDirection(tuple(float(c) for c in v))

    def storey(self, z):
        d = self.d
        if z < d.FFL_UP - 0.45:
            return self.storeys["GF"]
        if z < d.ROOF_TOP:
            return self.storeys["UF"]
        return self.storeys["RF"]

    def element(self, cls, name, items, style, z, systems=(), predefined=None, object_type=None, rtype="SweptSolid"):
        f = self.f
        el = api.root.create_entity(f, ifc_class=cls, name=name, predefined_type=predefined)
        if object_type:
            el.ObjectType = object_type
        api.spatial.assign_container(f, products=[el], relating_structure=self.storey(z))
        api.geometry.edit_object_placement(f, product=el, matrix=np.eye(4))
        rep = f.createIfcShapeRepresentation(self.body, "Body", rtype, items)
        api.geometry.assign_representation(f, product=el, representation=rep)
        api.style.assign_representation_styles(f, shape_representation=rep, styles=[style])
        for s in systems:
            api.system.assign_system(f, products=[el], system=self.systems[s])
        self.count[cls] = self.count.get(cls, 0) + 1
        return el

    def port(self, el, pt, flow, ptype, sys_key):
        p = api.system.add_port(self.f, element=el)
        m = np.eye(4); m[:3, 3] = pt
        api.geometry.edit_object_placement(self.f, product=p, matrix=m)
        p.FlowDirection, p.PredefinedType = flow, ptype
        p.SystemType = SYSTEMS[sys_key][1]
        p.Name = f"{el.Name} / {flow.lower()}"
        return p

    def connect(self, up, down):
        if up is not None and down is not None:
            api.system.connect_port(self.f, port1=up, port2=down, direction="SOURCE")

    # ------------------------------------------------------------ geometry items
    def tube(self, pts, r):
        line = self.f.createIfcPolyline([self.P(p) for p in pts])
        return self.f.createIfcSweptDiskSolid(line, float(r), None, None, None)

    def rect_run(self, a, b, w, h):
        a, b = np.array(a, float), np.array(b, float)
        v = b - a; L = float(np.linalg.norm(v)); ax = v / L
        ref = (1, 0, 0) if abs(ax[2]) > 0.9 else ((0, 1, 0) if abs(ax[0]) > 0.9 else (1, 0, 0))
        prof = self.f.createIfcRectangleProfileDef("AREA", None, None, float(w), float(h))
        pos = self.f.createIfcAxis2Placement3D(self.P(a), self.D(ax), self.D(ref))
        return self.f.createIfcExtrudedAreaSolid(prof, pos, self.D((0, 0, 1)), L)

    def box(self, x0, y0, z0, x1, y1, z1):
        f = self.f
        prof = f.createIfcRectangleProfileDef("AREA", None, f.createIfcAxis2Placement2D(
            f.createIfcCartesianPoint(((x0 + x1) / 2, (y0 + y1) / 2)), None), float(x1 - x0), float(y1 - y0))
        pos = f.createIfcAxis2Placement3D(self.P((0, 0, z0)), None, None)
        return f.createIfcExtrudedAreaSolid(prof, pos, self.D((0, 0, 1)), float(z1 - z0))

    def cyl(self, cx, cy, r, z0, z1):
        f = self.f
        prof = f.createIfcCircleProfileDef("AREA", None, f.createIfcAxis2Placement2D(
            f.createIfcCartesianPoint((float(cx), float(cy))), None), float(r))
        pos = f.createIfcAxis2Placement3D(self.P((0, 0, z0)), None, None)
        return f.createIfcExtrudedAreaSolid(prof, pos, self.D((0, 0, 1)), float(z1 - z0))

    def sphere(self, pt, r):
        return self.f.createIfcSphere(self.f.createIfcAxis2Placement3D(self.P(pt), None, None), float(r))

    # ------------------------------------------------------------ networks
    def run(self, sys_key, name, pts, size, kind="pipe", start=None, end=None):
        """Route a run through `pts`. `size` = diameter, or (w, h) for trays.
        `start` = upstream SOURCE port to connect to; `end` = downstream SINK port.
        Returns (first SINK port, last SOURCE port)."""
        seg_cls, seg_type, fit_cls, ptype, rigid = KINDS[kind]
        style = self.styles[sys_key]
        raw = [tuple(float(c) for c in p) for p in pts]
        pts = [p for i, p in enumerate(raw) if i == 0 or np.linalg.norm(np.subtract(p, raw[i - 1])) > 1e-6]
        if not rigid:
            items = [self.tube(pts, size / 2)]
            el = self.element(seg_cls, name, items, style, min(p[2] for p in pts), [sys_key], seg_type,
                              rtype="AdvancedSweptSolid")
            a = self.port(el, pts[0], "SINK", ptype, sys_key)
            b = self.port(el, pts[-1], "SOURCE", ptype, sys_key)
            self.connect(start, a); self.connect(b, end)
            return a, b
        first = prev = None
        for i in range(len(pts) - 1):
            p0, p1 = pts[i], pts[i + 1]
            if kind == "tray":
                item, rtype = self.rect_run(p0, p1, *size), "SweptSolid"
            else:
                item, rtype = self.tube([p0, p1], size / 2), "AdvancedSweptSolid"
            seg = self.element(seg_cls, f"{name} #{i + 1}", [item], style, min(p0[2], p1[2]), [sys_key], seg_type,
                               rtype=rtype)
            a = self.port(seg, p0, "SINK", ptype, sys_key)
            b = self.port(seg, p1, "SOURCE", ptype, sys_key)
            if prev is not None:
                fr = (size / 2 * 1.35) if kind != "tray" else max(size) * 0.6
                fit_item = self.sphere(p0, fr) if kind != "tray" else self.box(
                    p0[0] - fr / 2, p0[1] - fr / 2, p0[2] - size[1] / 2, p0[0] + fr / 2, p0[1] + fr / 2, p0[2] + size[1] / 2)
                fit = self.element(fit_cls, f"{name} bend {i}", [fit_item], style, p0[2], [sys_key], "BEND",
                                   rtype="CSG" if kind != "tray" else "SweptSolid")
                fi = self.port(fit, p0, "SINK", ptype, sys_key)
                fo = self.port(fit, p0, "SOURCE", ptype, sys_key)
                self.connect(prev, fi); self.connect(fo, a)
            else:
                first = a
            prev = b
        self.connect(start, first); self.connect(prev, end)
        return first, prev

    def junction(self, sys_key, name, pt, n_in, n_out, size, kind="pipe", object_type=None):
        """Tee / multi-inlet junction at `pt`. Returns (list of SINK ports, list of SOURCE ports)."""
        seg_cls, seg_type, fit_cls, ptype, rigid = KINDS[kind]
        cls, pdef = (fit_cls, "JUNCTION") if fit_cls else ("IfcJunctionBox", "POWER")
        el = self.element(cls, name, [self.sphere(pt, size / 2 * 1.7)], self.styles[sys_key], pt[2], [sys_key],
                          pdef, object_type=object_type, rtype="CSG")
        ins = [self.port(el, pt, "SINK", ptype, sys_key) for _ in range(n_in)]
        outs = [self.port(el, pt, "SOURCE", ptype, sys_key) for _ in range(n_out)]
        return ins, outs

    def device(self, cls, name, items, ports=(), systems=(), predefined=None, object_type=None, style="equip",
               rtype="SweptSolid", z=None):
        """Equipment / terminal. ports = [(key, pt, flow, ptype, sys_key)] -> returns (el, {key: port})."""
        zz = z if z is not None else (ports[0][1][2] if ports else 0.0)
        el = self.element(cls, name, items, self.styles[style], zz, systems, predefined, object_type, rtype)
        return el, {k: self.port(el, pt, flow, pt_type, sk) for k, pt, flow, pt_type, sk in ports}


def serpentine(x_start, x_end, y_near, y_far, spacing, z):
    """Radiant loop body: passes along x (alternating direction) from the near to the far edge,
    then a return lane just outside x_start back to the near edge. Starts at (x_start, y_near)."""
    n = max(3, int(abs(y_far - y_near) / spacing))
    if n % 2 == 0:      # even number of passes, so the loop ends back on the x_start side
        n += 1
    ys = np.linspace(y_near, y_far, n + 1)
    pts = []
    for k, y in enumerate(ys):
        a, b = (x_start, x_end) if k % 2 == 0 else (x_end, x_start)
        pts += [(a, y, z), (b, y, z)]
    lane = x_start + 0.12 * np.sign(x_start - x_end)
    pts += [(lane, pts[-1][1], z), (lane, y_near, z)]
    return pts


def add_mep(f, body, storeys, d):
    m = MEP(f, body, storeys, d)
    E = SimpleNamespace(**d) if isinstance(d, dict) else d
    FL = E.FFL_UP          # upper finished floor
    BUZ = FL - 0.30        # services zone under the upper core floor (above the plant room)
    SCR = FL - 0.06        # PEX in the floor build-up
    CL = E.CEIL            # underside of roof slab
    GT = E.GARDEN_TOP

    # ================================================================ plant room equipment
    # heat exchanger (groundwater side isolated from the heat pump by a plate HX)
    hx, HX = m.device("IfcHeatExchanger", "Groundwater plate heat exchanger", [m.box(3.85, 4.2, 0.3, 4.15, 4.5, 0.9)],
                      [("gw_in", (3.85, 4.28, 0.40), "SINK", "PIPE", "GW"), ("gw_out", (3.85, 4.42, 0.80), "SOURCE", "PIPE", "GW"),
                       ("src_out", (4.15, 4.28, 0.80), "SOURCE", "PIPE", "SRC"), ("src_in", (4.15, 4.42, 0.40), "SINK", "PIPE", "SRC")],
                      systems=["GW", "SRC"], predefined="PLATE")
    hp, HP = m.device("IfcUnitaryEquipment", "Water-to-water heat pump 8 kW", [m.box(4.45, 4.15, 0.05, 5.30, 4.85, 1.15)],
                      [("src_in", (4.45, 4.28, 0.80), "SINK", "PIPE", "SRC"), ("src_out", (4.45, 4.42, 0.40), "SOURCE", "PIPE", "SRC"),
                       ("flow", (4.70, 4.50, 1.15), "SOURCE", "PIPE", "HTG"), ("ret", (5.00, 4.50, 1.15), "SINK", "PIPE", "HTG"),
                       ("dhw_flow", (4.65, 4.85, 0.90), "SOURCE", "PIPE", "DHW"), ("dhw_ret", (5.10, 4.85, 0.90), "SINK", "PIPE", "DHW")],
                      systems=["SRC", "HTG", "DHW", "ELEC", "CTRL"], predefined="USERDEFINED",
                      object_type="Groundwater-source heat pump (heating, cooling, DHW)")
    buf, BUF = m.device("IfcTank", "Buffer tank 200 l", [m.cyl(4.95, 5.5, 0.30, 0.05, 1.55)],
                        [("hp_in", (4.80, 5.40, 1.55), "SINK", "PIPE", "HTG"), ("hp_out", (5.10, 5.40, 1.55), "SOURCE", "PIPE", "HTG"),
                         ("sys_out", (4.80, 5.60, 1.55), "SOURCE", "PIPE", "HTG"), ("sys_in", (5.10, 5.60, 1.55), "SINK", "PIPE", "HTG")],
                        systems=["HTG"], predefined="STORAGE")
    dhw, DHWT = m.device("IfcTank", "DHW cylinder 250 l (heat pump coil)", [m.cyl(4.95, 6.35, 0.30, 0.05, 1.85)],
                         [("coil_in", (4.85, 6.25, 1.85), "SINK", "PIPE", "DHW"), ("coil_out", (5.05, 6.25, 1.85), "SOURCE", "PIPE", "DHW"),
                          ("hot", (4.95, 6.50, 1.85), "SOURCE", "PIPE", "DHW"), ("cold", (4.65, 6.35, 0.25), "SINK", "PIPE", "DCW")],
                         systems=["DHW", "DCW"], predefined="STORAGE")
    pump_h, PH = m.device("IfcPump", "Heating circulator", [m.cyl(4.80, 5.60, 0.07, 1.80, 2.05)],
                          [("in", (4.80, 5.60, 1.80), "SINK", "PIPE", "HTG"), ("out", (4.80, 5.60, 2.05), "SOURCE", "PIPE", "HTG")],
                          systems=["HTG", "CTRL"], predefined="CIRCULATOR")
    mdb, MDB = m.device("IfcElectricDistributionBoard", "Main distribution board", [m.box(2.88, 4.30, 1.00, 3.05, 5.10, 1.90)],
                        [("in", (2.975, 4.70, 1.00), "SINK", "CABLECARRIER", "ELEC"), ("tray", (2.975, 4.70, 1.90), "SOURCE", "CABLECARRIER", "ELEC")],
                        systems=["ELEC", "LTG", "PV"], predefined="DISTRIBUTIONBOARD", style="device")
    inv, INV = m.device("IfcTransformer", "PV inverter 7 kW", [m.box(2.88, 5.30, 1.20, 3.05, 5.80, 1.80)],
                        [("dc", (2.975, 5.55, 1.80), "SINK", "CABLE", "PV"), ("ac", (2.975, 5.30, 1.50), "SOURCE", "CABLE", "PV")],
                        systems=["PV", "ELEC"], predefined="INVERTER", style="device")
    ctrl, _ = m.device("IfcController", "Home automation controller (KNX / IP)", [m.box(2.88, 6.00, 1.30, 2.98, 6.40, 1.70)],
                       systems=["CTRL", "SEC"], predefined="PROGRAMMABLE", style="device", z=1.3)
    m.device("IfcCommunicationsAppliance", "Network router / NVR", [m.box(2.88, 6.50, 1.30, 2.98, 6.80, 1.55)],
             systems=["SEC", "CTRL"], predefined="ROUTER", style="device", z=1.3)
    ppool, PP = m.device("IfcPump", "Pool filtration pump", [m.box(4.00, 7.25, 0.05, 4.35, 7.60, 0.35)],
                         [("in", (4.35, 7.42, 0.20), "SINK", "PIPE", "POOL"), ("out", (4.175, 7.42, 0.35), "SOURCE", "PIPE", "POOL")],
                         systems=["POOL", "ELEC"], predefined="ENDSUCTION")
    pfil, PF = m.device("IfcFilter", "Pool sand filter", [m.cyl(4.95, 7.40, 0.25, 0.05, 1.00)],
                        [("in", (4.70, 7.42, 0.60), "SINK", "PIPE", "POOL"), ("out", (4.95, 7.40, 1.00), "SOURCE", "PIPE", "POOL")],
                        systems=["POOL"], predefined="WATERFILTER")

    # ================================================================ geothermal open loop
    for name, (wx, wy), depth in [("Production well P1", (1.5, -8.0), -30.0), ("Reinjection well R1", (9.5, 18.0), -30.0)]:
        m.device("IfcDistributionChamberElement", f"{name} wellhead chamber", [m.box(wx - 0.4, wy - 0.4, -0.9, wx + 0.4, wy + 0.4, 0.0)],
                 systems=["GW"], predefined="VALVECHAMBER", z=-0.9)
        m.element("IfcPipeSegment", f"{name} casing DN150", [m.tube([(wx, wy, -0.9), (wx, wy, depth)], 0.08)],
                  m.styles["equip"], -0.9, ["GW"], "RIGIDSEGMENT", rtype="AdvancedSweptSolid")
    wp, WP = m.device("IfcPump", "Submersible well pump", [m.cyl(1.5, -8.0, 0.05, -16.0, -15.0)],
                      [("out", (1.5, -8.0, -15.0), "SOURCE", "PIPE", "GW")], systems=["GW", "ELEC", "CTRL"],
                      predefined="SUBMERSIBLEPUMP", z=-15)
    m.run("GW", "Groundwater supply", [(1.5, -8.0, -15.0), (1.5, -8.0, -0.6), (1.5, 4.28, -0.6), (3.6, 4.28, -0.6),
                                        (3.6, 4.28, 0.4), (3.85, 4.28, 0.4)], 0.05, start=WP["out"], end=HX["gw_in"])
    m.run("GW", "Groundwater reinjection", [(3.85, 4.42, 0.8), (3.5, 4.42, 0.8), (3.5, 4.42, -0.7), (3.5, 18.0, -0.7),
                                             (9.5, 18.0, -0.7), (9.5, 18.0, -20.0)], 0.05, start=HX["gw_out"])
    m.run("SRC", "Source loop to heat pump", [(4.15, 4.28, 0.8), (4.45, 4.28, 0.8)], 0.04, start=HX["src_out"], end=HP["src_in"])
    m.run("SRC", "Source loop return", [(4.45, 4.42, 0.4), (4.15, 4.42, 0.4)], 0.04, start=HP["src_out"], end=HX["src_in"])

    # ================================================================ heating / cooling primary + radiant floor
    m.run("HTG", "HP to buffer", [(4.7, 4.5, 1.15), (4.7, 4.5, 1.75), (4.7, 5.4, 1.75), (4.8, 5.4, 1.75), (4.8, 5.4, 1.55)],
          0.035, start=HP["flow"], end=BUF["hp_in"])
    m.run("HTG", "Buffer to HP", [(5.1, 5.4, 1.55), (5.1, 5.4, 1.85), (5.1, 4.5, 1.85), (5.0, 4.5, 1.85), (5.0, 4.5, 1.15)],
          0.035, start=BUF["hp_out"], end=HP["ret"])
    m.run("HTG", "Buffer to circulator", [(4.8, 5.6, 1.55), (4.8, 5.6, 1.8)], 0.035, start=BUF["sys_out"], end=PH["in"])
    # radiant manifold in the upper shaft
    MX0, MY = 3.00, 7.45
    mani, MAN = m.device("IfcPipeFitting", "Radiant floor manifold (8 loops)",
                         [m.box(2.95, 7.45, 3.40, 3.62, 7.60, 3.48), m.box(2.95, 7.45, 3.77, 3.62, 7.60, 3.85)],
                         [("in", (3.45, 7.53, 3.40), "SINK", "PIPE", "HTG"), ("out", (3.55, 7.53, 3.40), "SOURCE", "PIPE", "HTG")],
                         systems=["HTG"], predefined="JUNCTION", object_type="Manifold", z=3.4)
    m.run("HTG", "Flow riser to manifold", [(4.8, 5.6, 2.05), (4.8, 5.6, 2.25), (3.45, 5.6, 2.25), (3.45, 7.8, 2.25),
                                             (3.45, 7.8, 3.30), (3.45, 7.53, 3.30), (3.45, 7.53, 3.40)], 0.035,
          start=PH["out"], end=MAN["in"])
    m.run("HTG", "Return riser from manifold", [(3.55, 7.53, 3.40), (3.55, 7.53, 3.30), (3.55, 7.8, 3.30), (3.55, 7.8, 2.40),
                                                 (3.55, 5.75, 2.40), (5.1, 5.75, 2.40), (5.1, 5.6, 2.40), (5.1, 5.6, 1.55)], 0.035,
          start=MAN["out"], end=BUF["sys_in"])
    loops = [  # name, x_start (feed side), x_end, y_near, y_far, feeder lane y (flow; return lane +/- 0.05)
        ("Front zone L1", 2.55, 0.45, 3.55, 0.80, 3.85),
        ("Front zone L2", 5.30, 2.90, 3.55, 0.80, 3.85),
        ("Front zone L3", 8.10, 5.70, 3.55, 0.80, 3.85),
        ("Front zone L4", 10.55, 8.50, 3.55, 0.80, 3.85),
        ("Back zone L5", 3.70, 0.45, 8.45, 11.55, 8.20),
        ("Back zone L6", 7.20, 4.00, 8.45, 11.55, 8.20),
        ("Back zone L7", 10.55, 7.50, 8.45, 11.55, 8.20),
        ("Corridor L8", 10.55, 8.70, 7.65, 4.35, 8.20),
    ]
    for i, (name, xs_, xe_, yn, yf, fy) in enumerate(loops):
        xf, xr = MX0 + 0.075 * i, MX0 + 0.075 * i + 0.035
        z = SCR - 0.004 * i
        fyr = fy + 0.05 if fy > 6 else fy - 0.05   # return lane runs beside the flow lane...
        zr = z - 0.025                              # ...and 25 mm lower, so the loop never crosses itself
        body_pts = serpentine(xs_, xe_, yn, yf, 0.30, z)
        lane_x = body_pts[-1][0]
        pts = ([(xf, MY, 3.77), (xf, MY, z), (xf, fy, z), (xs_, fy, z)] + body_pts +
               [(lane_x, yn, zr), (lane_x, fyr, zr), (xr, fyr, zr), (xr, MY, zr), (xr, MY, 3.48)])
        ps, pe = m.run("HTG", f"Radiant loop {name}", pts, 0.017, kind="pex")
        mani_out = m.port(mani, (xf, MY, 3.77), "SOURCE", "PIPE", "HTG")
        mani_in = m.port(mani, (xr, MY, 3.48), "SINK", "PIPE", "HTG")
        m.connect(mani_out, ps); m.connect(pe, mani_in)
        m.device("IfcActuator", f"Loop actuator {name}", [m.cyl(xr, MY - 0.03, 0.015, 3.48, 3.56)],
                 systems=["CTRL", "HTG"], predefined="THERMOSTATICACTUATOR", style="device", z=3.48)

    # ================================================================ sanitary fixtures (upper core + kitchen)
    fixtures = [  # name, class/type, geometry boxes, cold pt, hot pt, drain pt, drain dia
        ("WC bathroom A", "TOILETPAN", [(4.87, 4.10, FL, 5.23, 4.65, FL + 0.40), (4.85, 4.06, FL + 0.40, 5.25, 4.25, FL + 0.80)],
         (5.05, 4.10, FL + 0.60), None, (5.05, 4.25, FL), 0.11),
        ("Basin bathroom A", "WASHHANDBASIN", [(3.85, 4.06, FL + 0.70, 4.35, 4.50, FL + 0.85)],
         (4.05, 4.08, FL + 0.55), (4.15, 4.08, FL + 0.55), (4.10, 4.20, FL), 0.04),
        ("Shower bathroom A", "SHOWER", [(2.95, 4.80, FL, 3.75, 5.60, FL + 0.05)],
         (3.00, 5.15, FL + 1.10), (3.00, 5.25, FL + 1.10), (3.35, 5.20, FL), 0.05),
        ("WC bathroom B", "TOILETPAN", [(4.87, 7.05, FL, 5.23, 7.60, FL + 0.40), (4.85, 7.41, FL + 0.40, 5.25, 7.60, FL + 0.80)],
         (5.05, 7.60, FL + 0.60), None, (5.05, 7.40, FL), 0.11),
        ("Basin bathroom B", "WASHHANDBASIN", [(3.95, 6.85, FL + 0.70, 4.45, 7.28, FL + 0.85)],
         (4.15, 7.26, FL + 0.55), (4.25, 7.26, FL + 0.55), (4.20, 7.10, FL), 0.04),
        ("Shower bathroom B", "SHOWER", [(2.95, 6.20, FL, 3.75, 7.00, FL + 0.05)],
         (3.00, 6.55, FL + 1.10), (3.00, 6.65, FL + 1.10), (3.35, 6.60, FL), 0.05),
        ("Kitchen sink", "SINK", [(0.30, 3.35, FL + 0.85, 2.50, 3.95, FL + 0.90), (1.15, 3.45, FL + 0.70, 1.65, 3.85, FL + 0.85)],
         (1.35, 3.93, FL + 0.55), (1.45, 3.93, FL + 0.55), (1.40, 3.65, FL), 0.05),
    ]
    FX = []
    for name, ptype, boxes, cw, hw, dr, dd in fixtures:
        ports = [("cw", cw, "SINK", "PIPE", "DCW"), ("dr", dr, "SOURCE", "PIPE", "SAN")]
        sys_ = ["DCW", "SAN"]
        if hw:
            ports.append(("hw", hw, "SINK", "PIPE", "DHW")); sys_.append("DHW")
        el, pp = m.device("IfcSanitaryTerminal", name, [m.box(*b) for b in boxes], ports, sys_, ptype,
                          style="fixture", z=FL)
        FX.append((name, cw, hw, dr, dd, pp))

    # ---------------------------------------------------------------- domestic cold water
    met, MET = m.device("IfcFlowMeter", "Water meter (street connection)", [m.box(2.10, -15.90, -0.60, 2.70, -15.30, 0.00)],
                        [("in", (2.40, -15.90, -0.40), "SINK", "PIPE", "DCW"), ("out", (2.40, -15.30, -0.40), "SOURCE", "PIPE", "DCW")],
                        systems=["DCW"], predefined="WATERMETER")
    m.run("DCW", "Street main connection", [(2.40, -16.5, -0.80), (2.40, -16.5, -0.40), (2.40, -15.90, -0.40)], 0.032,
          end=MET["in"])
    val, VAL = m.device("IfcValve", "Main stopcock + filter", [m.box(3.18, 4.53, 0.30, 3.32, 4.67, 0.45)],
                        [("in", (3.25, 4.60, 0.30), "SINK", "PIPE", "DCW"), ("out", (3.25, 4.60, 0.45), "SOURCE", "PIPE", "DCW")],
                        systems=["DCW"], predefined="STOPCOCK")
    m.run("DCW", "Service pipe to plant room", [(2.40, -15.30, -0.40), (2.40, 4.60, -0.40), (3.25, 4.60, -0.40), (3.25, 4.60, 0.30)],
          0.032, start=MET["out"], end=VAL["in"])
    (t1_in,), (t1_a, t1_b) = m.junction("DCW", "Cold water tee T1", (3.25, 6.35, 0.25), 1, 2, 0.032)
    m.run("DCW", "Cold main", [(3.25, 4.60, 0.45), (3.25, 4.60, 0.25), (3.25, 6.35, 0.25)], 0.032, start=VAL["out"], end=t1_in)
    m.run("DCW", "Cold feed to DHW cylinder", [(3.25, 6.35, 0.25), (4.65, 6.35, 0.25)], 0.025, start=t1_a, end=DHWT["cold"])
    cman, CMAN = m.device("IfcPipeFitting", "Cold water manifold (PEX home runs)", [m.box(2.92, 7.33, 4.15, 3.00, 7.90, 4.25)],
                          [("in", (2.96, 7.80, 4.15), "SINK", "PIPE", "DCW")], systems=["DCW"], predefined="JUNCTION",
                          object_type="Manifold", z=4.15)
    m.run("DCW", "Cold riser", [(3.25, 6.35, 0.25), (3.25, 7.80, 0.25), (3.25, 7.80, 4.05), (2.96, 7.80, 4.05), (2.96, 7.80, 4.15)],
          0.028, start=t1_b, end=CMAN["in"])
    # ---------------------------------------------------------------- domestic hot water
    m.run("DHW", "HP to DHW coil", [(4.65, 4.85, 0.9), (4.65, 4.85, 2.0), (4.85, 4.85, 2.0), (4.85, 6.25, 2.0), (4.85, 6.25, 1.85)],
          0.028, start=HP["dhw_flow"], end=DHWT["coil_in"])
    m.run("DHW", "DHW coil return", [(5.05, 6.25, 1.85), (5.05, 6.25, 2.1), (5.10, 6.25, 2.1), (5.10, 4.85, 2.1), (5.10, 4.85, 0.9)],
          0.028, start=DHWT["coil_out"], end=HP["dhw_ret"])
    hman, HMAN = m.device("IfcPipeFitting", "Hot water manifold (PEX home runs)", [m.box(2.92, 7.33, 4.45, 3.00, 7.90, 4.55)],
                          [("in", (2.96, 7.80, 4.45), "SINK", "PIPE", "DHW")], systems=["DHW"], predefined="JUNCTION",
                          object_type="Manifold", z=4.45)
    m.run("DHW", "Hot riser", [(4.95, 6.50, 1.85), (4.95, 6.50, 2.55), (3.35, 6.50, 2.55), (3.35, 7.80, 2.55), (3.35, 7.80, 4.35),
                               (2.96, 7.80, 4.35), (2.96, 7.80, 4.45)], 0.028, start=DHWT["hot"], end=HMAN["in"])
    # home runs: manifold -> down the shaft -> floor build-up -> fixture
    for k, (name, cw, hw, dr, dd, pp) in enumerate(FX):
        for sys_key, man, mz, tgt, off in [("DCW", cman, 4.20, cw, 0.0), ("DHW", hman, 4.50, hw, 0.012)]:
            if tgt is None:
                continue
            y0 = 7.36 + 0.075 * k
            z = SCR - 0.02 - 0.008 * k - off
            pts = [(3.00, y0, mz), (3.08 + off, y0, mz), (3.08 + off, y0, z)]
            if tgt[1] < 4.05:  # kitchen: leave the core along y = 4.25, cross under M1
                pts += [(3.08 + off, 4.25 + off, z), (tgt[0], 4.25 + off, z)]
            else:
                pts += [(3.08 + off, tgt[1], z)]
            pts += [(tgt[0], tgt[1], z), tgt]
            op = m.port(man, (3.00, y0, mz), "SOURCE", "PIPE", sys_key)
            m.run(sys_key, f"{SYSTEMS[sys_key][0]} home run to {name}", pts, 0.016, kind="pex", start=op,
                  end=pp["cw" if sys_key == "DCW" else "hw"])

    # ---------------------------------------------------------------- soil stack, branches, sewer
    SX, SY = 3.05, 7.75
    br_ins, (st_down, st_up) = m.junction("SAN", "Stack branch junction (multi-inlet)", (SX, SY, BUZ), len(FX), 2, 0.11,
                                          object_type="Multi-inlet stack fitting")
    for (name, cw, hw, dr, dd, pp), port_in in zip(FX, br_ins):
        pts = [dr, (dr[0], dr[1], BUZ)]
        if dr[1] < 4.05:
            pts += [(dr[0], 4.30, BUZ), (SX, 4.30, BUZ)]
        else:
            pts += [(SX, dr[1], BUZ)] if abs(dr[0] - SX) > 1e-6 else []
        pts += [(SX, SY, BUZ)] if pts[-1][:2] != (SX, SY) else []
        m.run("SAN", f"Waste branch {name}", pts, max(dd, 0.05), start=pp["dr"], end=port_in)
    vent_cap, VC = m.device("IfcPipeFitting", "Stack vent cowl", [m.cyl(SX, SY, 0.08, GT + 0.55, GT + 0.75)],
                            [("in", (SX, SY, GT + 0.55), "SINK", "PIPE", "SAN")], systems=["SAN"], predefined="EXIT", z=GT)
    m.run("SAN", "Stack vent through roof", [(SX, SY, BUZ), (SX, SY, GT + 0.55)], 0.11, start=st_up, end=VC["in"])
    ftrap, FT = m.device("IfcWasteTerminal", "Plant room floor trap", [m.box(4.0, 6.85, -0.05, 4.2, 7.05, 0.0)],
                         [("out", (4.10, 6.95, -0.05), "SOURCE", "PIPE", "SAN")], systems=["SAN"], predefined="FLOORTRAP", z=0)
    (td_a, td_b), (td_out,) = m.junction("SAN", "Underground drain tee", (SX, 6.95, -0.70), 2, 1, 0.11)
    m.run("SAN", "Soil stack", [(SX, SY, BUZ), (SX, SY, -0.70), (SX, 6.95, -0.70)], 0.11, start=st_down, end=td_a)
    m.run("SAN", "Floor trap branch", [(4.10, 6.95, -0.05), (4.10, 6.95, -0.70), (SX, 6.95, -0.70)], 0.05,
          start=FT["out"], end=td_b)
    ic, IC = m.device("IfcDistributionChamberElement", "Inspection chamber at boundary", [m.box(2.75, -15.50, -1.10, 3.35, -14.90, 0.0)],
                      [("in", (SX, -14.90, -0.95), "SINK", "PIPE", "SAN"), ("out", (SX, -15.50, -1.0), "SOURCE", "PIPE", "SAN")],
                      systems=["SAN"], predefined="INSPECTIONCHAMBER", z=-1.1)
    m.run("SAN", "Building drain to boundary", [(SX, 6.95, -0.70), (SX, -14.90, -0.95)], 0.11, start=td_out, end=IC["in"])
    m.run("SAN", "Connection to public sewer", [(SX, -15.50, -1.0), (SX, -16.5, -1.05)], 0.11, start=IC["out"])

    # ================================================================ rainwater harvesting + irrigation
    cis, CIS = m.device("IfcTank", "Rainwater cistern 4.5 m3 (underground)", [m.box(4.5, 14.5, -2.0, 6.5, 16.0, -0.4)],
                        [("in_l", (4.7, 15.25, -0.4), "SINK", "PIPE", "RW"), ("in_r", (6.3, 15.25, -0.4), "SINK", "PIPE", "RW"),
                         ("in_v", (5.5, 14.8, -0.4), "SINK", "PIPE", "RW"),
                         ("draw", (5.0, 15.6, -1.9), "SOURCE", "PIPE", "IRR")], systems=["RW", "IRR"], predefined="STORAGE", z=-2)
    for side, x, inp in [("left", 0.5, CIS["in_l"]), ("right", 10.5, CIS["in_r"])]:
        rd, RD = m.device("IfcWasteTerminal", f"Roof garden drain ({side})", [m.cyl(x, 11.5, 0.12, E.ROOF_TOP, GT + 0.02)],
                          [("out", (x, 11.5, E.ROOF_TOP + 0.05), "SOURCE", "PIPE", "RW")], systems=["RW"], predefined="ROOFDRAIN",
                          z=E.ROOF_TOP)
        xc = 4.7 if side == "left" else 6.3
        m.run("RW", f"Downpipe {side}", [(x, 11.5, E.ROOF_TOP + 0.05), (x, 12.12, E.ROOF_TOP + 0.05), (x, 12.12, -0.6),
                                         (x, 15.25, -0.6), (xc, 15.25, -0.6), (xc, 15.25, -0.4)], 0.09, start=RD["out"], end=inp)
    vg, VG = m.device("IfcWasteTerminal", "Void floor gully", [m.box(6.8, 5.9, -0.05, 7.0, 6.1, 0.0)],
                      [("out", (6.9, 6.0, -0.05), "SOURCE", "PIPE", "RW")], systems=["RW"], predefined="GULLYTRAP", z=0)
    m.run("RW", "Void gully drain", [(6.9, 6.0, -0.05), (6.9, 6.0, -0.5), (6.9, 14.0, -0.5), (5.5, 14.0, -0.5), (5.5, 14.8, -0.5),
                                     (5.5, 14.8, -0.4)], 0.075, start=VG["out"], end=CIS["in_v"])
    ip, IP = m.device("IfcPump", "Irrigation pump (in cistern)", [m.cyl(5.0, 15.6, 0.07, -1.9, -1.5)],
                      [("in", (5.0, 15.6, -1.9), "SINK", "PIPE", "IRR"), ("out", (5.0, 15.6, -1.5), "SOURCE", "PIPE", "IRR")],
                      systems=["IRR", "ELEC", "CTRL"], predefined="SUBMERSIBLEPUMP", z=-1.9)
    m.connect(CIS["draw"], IP["in"])
    (it_in,), (it_up, it_pl) = m.junction("IRR", "Irrigation tee (planters)", (3.2, 7.5, FL - 0.15), 1, 2, 0.032)
    m.run("IRR", "Irrigation main + riser", [(5.0, 15.6, -1.5), (5.0, 15.6, -0.45), (3.2, 15.6, -0.45), (3.2, 7.5, -0.45),
                                             (3.2, 7.5, FL - 0.15)], 0.032, start=IP["out"], end=it_in)
    vb, VB = m.device("IfcValve", "Irrigation solenoid valves (roof)", [m.box(3.05, 7.35, GT, 3.35, 7.65, GT + 0.25)],
                      [("in", (3.2, 7.5, GT), "SINK", "PIPE", "IRR"), ("out", (3.2, 7.65, GT + 0.10), "SOURCE", "PIPE", "IRR")],
                      systems=["IRR", "CTRL"], predefined="USERDEFINED", object_type="Solenoid valve set", z=GT)
    m.run("IRR", "Irrigation riser to roof", [(3.2, 7.5, FL - 0.15), (3.2, 7.5, GT)], 0.032, start=it_up, end=VB["in"])
    ring = [(3.2, 7.65, GT + 0.10), (3.2, 8.6, GT - 0.05), (0.8, 8.6, GT - 0.05), (0.8, 11.2, GT - 0.05), (10.2, 11.2, GT - 0.05),
            (10.2, 0.8, GT - 0.05), (0.8, 0.8, GT - 0.05), (0.8, 3.3, GT - 0.05), (4.8, 3.3, GT - 0.05)]
    m.run("IRR", "Roof garden drip ring", ring, 0.016, kind="pex", start=VB["out"])
    (pt_in,), (pt_l, pt_r) = m.junction("IRR", "Planter drip tee", (3.2, 0.27, FL + 0.40), 1, 2, 0.02)
    m.run("IRR", "Planter feed", [(3.2, 7.5, FL - 0.15), (3.2, 7.5, SCR - 0.06), (3.2, 0.27, SCR - 0.06), (3.2, 0.27, FL + 0.40)],
          0.02, kind="pex", start=it_pl, end=pt_in)
    m.run("IRR", "Planter drip line (left)", [(3.2, 0.27, FL + 0.40), (0.2, 0.27, FL + 0.40)], 0.016, kind="pex", start=pt_l)
    m.run("IRR", "Planter drip line (right)", [(3.2, 0.27, FL + 0.40), (10.8, 0.27, FL + 0.40)], 0.016, kind="pex", start=pt_r)
    m.device("IfcSensor", "Cistern level sensor", [m.cyl(6.2, 15.7, 0.03, -1.0, -0.4)], systems=["CTRL", "RW"],
             predefined="LEVELSENSOR", style="device", z=-1.0)
    m.device("IfcSensor", "Soil moisture sensor (roof garden)", [m.cyl(6.0, 10.0, 0.02, GT - 0.2, GT + 0.1)], systems=["CTRL", "IRR"],
             predefined="MOISTURESENSOR", style="device", z=GT)

    # ================================================================ pool filtration
    sk, SK = m.device("IfcPipeFitting", "Pool skimmer", [m.box(7.5, -1.75, -0.30, 7.8, -1.55, 0.0)],
                      [("out", (7.65, -1.65, -0.30), "SOURCE", "PIPE", "POOL")], systems=["POOL"], predefined="ENTRY", z=-0.3)
    ri, RI = m.device("IfcPipeFitting", "Pool return inlet", [m.cyl(7.65, -11.95, 0.05, -0.55, -0.45)],
                      [("in", (7.65, -12.2, -0.5), "SINK", "PIPE", "POOL")], systems=["POOL"], predefined="EXIT", z=-0.55)
    m.run("POOL", "Skimmer suction", [(7.65, -1.65, -0.30), (7.65, -1.65, -0.55), (7.65, 7.0, -0.55), (4.45, 7.0, -0.55),
                                       (4.45, 7.42, -0.55), (4.45, 7.42, 0.20), (4.35, 7.42, 0.20)], 0.05, start=SK["out"], end=PP["in"])
    m.run("POOL", "Pump to filter", [(4.175, 7.42, 0.35), (4.175, 7.42, 0.60), (4.70, 7.42, 0.60)], 0.05, start=PP["out"], end=PF["in"])
    m.run("POOL", "Filtered return", [(4.95, 7.40, 1.0), (4.95, 7.40, 1.3), (5.25, 7.40, 1.3), (5.25, 7.40, -0.65),
                                       (5.25, -12.2, -0.65), (7.65, -12.2, -0.65), (7.65, -12.2, -0.5)], 0.05,
          start=PF["out"], end=RI["in"])

    # ================================================================ extract ventilation
    fan, FAN = m.device("IfcFan", "Roof extract fan (bathrooms)", [m.cyl(SX, 7.45, 0.18, GT, GT + 0.35)],
                        [("in", (SX, 7.45, GT), "SINK", "DUCT", "EXH")], systems=["EXH", "ELEC", "CTRL"],
                        predefined="USERDEFINED", object_type="Rooftop mixed-flow extract fan", z=GT)
    (ej_a, ej_b), (ej_out,) = m.junction("EXH", "Extract junction", (SX, 7.45, CL - 0.15), 2, 1, 0.125, kind="duct")
    for name, gx, gy, port in [("bathroom A", 4.10, 5.20, ej_a), ("bathroom B", 4.20, 6.80, ej_b)]:
        g, G = m.device("IfcAirTerminal", f"Extract grille {name}", [m.box(gx - 0.12, gy - 0.12, CL - 0.08, gx + 0.12, gy + 0.12, CL - 0.05)],
                        [("out", (gx, gy, CL - 0.05), "SOURCE", "DUCT", "EXH")], systems=["EXH"], predefined="GRILLE", z=CL - 0.1)
        m.run("EXH", f"Extract duct {name}", [(gx, gy, CL - 0.05), (gx, gy, CL - 0.15), (gx, 7.45, CL - 0.15), (SX, 7.45, CL - 0.15)],
              0.10, kind="duct", start=G["out"], end=port)
    m.run("EXH", "Extract riser through roof", [(SX, 7.45, CL - 0.15), (SX, 7.45, GT)], 0.125, kind="duct", start=ej_out, end=FAN["in"])
    hood, HOOD = m.device("IfcAirTerminal", "Kitchen extract hood", [m.box(1.05, 3.40, FL + 1.65, 1.75, 3.95, FL + 1.85)],
                          [("out", (1.40, 3.65, FL + 1.85), "SOURCE", "DUCT", "EXH")], systems=["EXH", "ELEC"],
                          predefined="USERDEFINED", object_type="Kitchen hood with fan", z=FL + 1.6)
    cowl, COWL = m.device("IfcAirTerminal", "Kitchen extract roof cowl", [m.cyl(1.40, 3.65, 0.13, GT + 0.30, GT + 0.50)],
                          [("in", (1.40, 3.65, GT + 0.30), "SINK", "DUCT", "EXH")], systems=["EXH"], predefined="LOUVRE", z=GT)
    m.run("EXH", "Kitchen extract duct", [(1.40, 3.65, FL + 1.85), (1.40, 3.65, GT + 0.30)], 0.15, kind="duct",
          start=HOOD["out"], end=COWL["in"])

    # ================================================================ electrical
    mp, MP = m.device("IfcFlowMeter", "Electricity meter pillar", [m.box(0.30, -15.80, 0.0, 0.95, -15.50, 1.20)],
                      [("in", (0.55, -15.65, 0.0), "SINK", "CABLECARRIER", "ELEC"), ("out", (0.70, -15.65, 0.0), "SOURCE", "CABLECARRIER", "ELEC")],
                      systems=["ELEC"], predefined="ENERGYMETER", style="device", z=0)
    m.run("ELEC", "Utility supply duct", [(0.55, -16.5, -0.6), (0.55, -15.65, -0.6), (0.55, -15.65, 0.0)], 0.063, kind="conduit", end=MP["in"])
    m.run("ELEC", "Submain duct to MDB", [(0.70, -15.65, 0.0), (0.70, -15.65, -0.6), (0.70, 4.70, -0.6), (2.975, 4.70, -0.6),
                                          (2.975, 4.70, 1.0)], 0.063, kind="conduit", start=MP["out"], end=MDB["in"])
    TR = (0.20, 0.06)
    (tj_in,), (tj_up, tj_uf) = m.junction("ELEC", "Tray junction (shaft base)", (3.45, 7.45, 2.50), 1, 2, 0.2, kind="tray")
    m.run("ELEC", "Plant room cable tray", [(2.975, 4.70, 1.90), (2.975, 4.70, 2.50), (3.45, 4.70, 2.50), (3.45, 7.45, 2.50)],
          TR, kind="tray", start=MDB["tray"], end=tj_in)
    m.run("ELEC", "Riser cable tray to roof", [(3.45, 7.45, 2.50), (3.45, 7.45, GT - 0.05)], TR, kind="tray", start=tj_up)
    ufb, UFB = m.device("IfcElectricDistributionBoard", "Upper floor consumer unit", [m.box(8.38, 6.50, FL + 0.80, 8.46, 7.20, FL + 1.60)],
                        [("in", (8.42, 6.85, FL + 0.80), "SINK", "CABLE", "ELEC")], systems=["ELEC", "LTG", "CTRL"],
                        predefined="CONSUMERUNIT", style="device", z=FL + 0.8)
    m.run("ELEC", "Submain cable to upper consumer unit", [(3.45, 7.45, 2.50), (3.45, 7.45, SCR - 0.03), (3.45, 8.25, SCR - 0.03),
                                                           (8.42, 8.25, SCR - 0.03), (8.42, 6.85, SCR - 0.03), (8.42, 6.85, FL + 0.80)],
          0.025, kind="cable", start=tj_uf, end=UFB["in"])

    def light(name, x, y, z, sys_=("LTG",), hang_down=True):
        r = 0.15
        el, pp = m.device("IfcLightFixture", name, [m.sphere((x, y, z - r if hang_down else z + r), r)],
                          [("in", (x, y, z), "SINK", "CABLE", "LTG"), ("out", (x, y, z), "SOURCE", "CABLE", "LTG")],
                          systems=list(sys_), predefined="POINTSOURCE", style="light", rtype="CSG", z=z)
        return pp

    def chain(sys_key, name, start_port, start_pt, fixtures_pts, z_route, make, kind="cable"):
        prev_port, prev_pt = start_port, start_pt
        for i, (fx, fy, fz) in enumerate(fixtures_pts):
            pp = make(f"{name} {i + 1}", fx, fy, fz)
            pts = [prev_pt, (prev_pt[0], prev_pt[1], z_route), (fx, prev_pt[1], z_route), (fx, fy, z_route), (fx, fy, fz)]
            pts = [p for j, p in enumerate(pts) if j == 0 or p != pts[j - 1]]
            m.run(sys_key, f"{name} circuit leg {i + 1}", pts, 0.02, kind=kind, start=prev_port, end=pp["in"])
            prev_port, prev_pt = pp["out"], (fx, fy, fz)

    xs4 = [1.375, 4.125, 6.875, 9.625]
    mdb_l = m.port(mdb, (2.975, 4.30, 1.90), "SOURCE", "CABLE", "LTG")
    chain("LTG", "Soffit light front", mdb_l, (2.975, 4.30, 1.90), [(x, 2.0, E.BOTTOM - 0.02) for x in xs4], E.BOTTOM + 0.04,
          lambda n, x, y, z: light(n, x, y, z))
    mdb_l2 = m.port(mdb, (2.975, 5.10, 1.90), "SOURCE", "CABLE", "LTG")
    chain("LTG", "Soffit light back", mdb_l2, (2.975, 5.10, 1.90), [(x, 10.0, E.BOTTOM - 0.02) for x in xs4], E.BOTTOM + 0.04,
          lambda n, x, y, z: light(n, x, y, z))
    for tag, y in [("front zone", 2.2), ("back zone", 10.0)]:
        up = m.port(ufb, (8.42, 6.85, FL + 1.60), "SOURCE", "CABLE", "LTG")
        chain("LTG", f"Ceiling light {tag}", up, (8.42, 6.85, FL + 1.60), [(x, y, CL) for x in reversed(xs4)], CL + 0.06,
              lambda n, x, y, z: light(n, x, y, z))
    up = m.port(ufb, (8.42, 6.70, FL + 1.60), "SOURCE", "CABLE", "LTG")
    chain("LTG", "Ceiling light core + corridor", up, (8.42, 6.70, FL + 1.60),
          [(9.6, 6.0, CL), (4.6, 4.6, CL), (4.6, 7.0, CL), (1.4, 6.0, CL)], CL + 0.06, lambda n, x, y, z: light(n, x, y, z))
    pool_l = m.port(mdb, (2.975, 4.50, 1.00), "SOURCE", "CABLE", "LTG")
    chain("LTG", "Pool light", pool_l, (2.975, 4.50, 1.00), [(6.5, -1.65, -0.6), (8.8, -1.65, -0.6)], -0.75,
          lambda n, x, y, z: light(n, x, y, z, hang_down=False), kind="cable")
    # floor power outlets (upper floor)
    def outlet(name, x, y, z):
        el, pp = m.device("IfcOutlet", name, [m.box(x - 0.08, y - 0.08, z - 0.06, x + 0.08, y + 0.08, z)],
                          [("in", (x, y, z - 0.06), "SINK", "CABLE", "ELEC"), ("out", (x, y, z - 0.06), "SOURCE", "CABLE", "ELEC")],
                          systems=["ELEC"], predefined="POWEROUTLET", style="device", z=z)
        return {"in": pp["in"], "out": pp["out"]}
    for tag, pts_ in [("front", [(9.6, 1.5, FL), (6.9, 1.5, FL), (4.1, 1.5, FL), (1.4, 2.8, FL)]),
                      ("back", [(9.6, 10.5, FL), (6.9, 10.5, FL), (4.1, 10.5, FL), (1.4, 10.5, FL)])]:
        up = m.port(ufb, (8.42, 7.00, FL + 0.80), "SOURCE", "CABLE", "ELEC")
        chain("ELEC", f"Floor outlet {tag}", up, (8.42, 7.00, FL + 0.80), pts_, SCR - 0.035, outlet)

    # ================================================================ photovoltaics
    tilt = math.radians(10)
    panels = []
    for row, (y0, y1) in enumerate([(8.45, 10.05), (10.15, 11.55)]):
        for col in range(9):
            x0 = 0.45 + col * 1.10
            x1 = x0 + 1.00
            z0 = GT + 0.25
            z1 = z0 + (y1 - y0) * math.tan(tilt)
            prof = m.f.createIfcArbitraryClosedProfileDef("AREA", None, m.f.createIfcPolyline(
                [m.f.createIfcCartesianPoint(p) for p in [(y0, z0), (y1, z1), (y1, z1 + 0.035), (y0, z0 + 0.035), (y0, z0)]]))
            pos = m.f.createIfcAxis2Placement3D(m.P((x0, 0, 0)), m.D((1, 0, 0)), m.D((0, 1, 0)))
            slab = m.f.createIfcExtrudedAreaSolid(prof, pos, m.D((0, 0, 1)), x1 - x0)
            legs = [m.box(x0 + 0.05, y0 + 0.05, GT, x0 + 0.09, y0 + 0.09, z0),
                    m.box(x1 - 0.09, y1 - 0.09, GT, x1 - 0.05, y1 - 0.05, z1),
                    m.box(x0 + 0.05, y1 - 0.09, GT, x0 + 0.09, y1 - 0.05, z1),
                    m.box(x1 - 0.09, y0 + 0.05, GT, x1 - 0.05, y0 + 0.09, z0)]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            el, pp = m.device("IfcSolarDevice", f"PV module R{row + 1}C{col + 1} 400 Wp", [slab] + legs,
                              [("in", (cx, cy, z0 - 0.05), "SINK", "CABLE", "PV"), ("out", (cx, cy, z0 - 0.05), "SOURCE", "CABLE", "PV")],
                              systems=["PV"], predefined="SOLARPANEL", style="pv", z=GT)
            panels.append((row, (cx, cy, z0 - 0.05), pp))
    (cb_in1, cb_in2), (cb_out,) = m.junction("PV", "PV string combiner", (3.45, 8.30, GT + 0.10), 2, 1, 0.08,
                                             kind="cable", object_type="DC combiner box")
    for row, cb_in in [(0, cb_in1), (1, cb_in2)]:
        string = [p for p in panels if p[0] == row]
        if row == 1:
            string = list(reversed(string))
        for a, b in zip(string, string[1:]):
            m.run("PV", f"PV string {row + 1} DC cable", [a[1], b[1]], 0.012, kind="cable", start=a[2]["out"], end=b[2]["in"])
        last = string[-1]
        m.run("PV", f"PV string {row + 1} home run", [last[1], (last[1][0], 8.30, last[1][2]), (3.45, 8.30, last[1][2]),
                                                      (3.45, 8.30, GT + 0.10)], 0.012, kind="cable", start=last[2]["out"], end=cb_in)
    m.run("PV", "PV DC main to inverter", [(3.45, 8.30, GT + 0.10), (3.45, 7.45, GT + 0.10), (3.45, 7.45, 2.45),
                                          (3.10, 7.45, 2.45), (3.10, 5.55, 2.45), (2.975, 5.55, 2.45), (2.975, 5.55, 1.80)],
          0.02, kind="cable", start=cb_out, end=INV["dc"])
    mdb_pv = m.port(mdb, (2.975, 5.10, 1.50), "SINK", "CABLE", "PV")
    m.run("PV", "Inverter AC to MDB", [(2.975, 5.30, 1.50), (2.975, 5.10, 1.50)], 0.02, kind="cable", start=INV["ac"], end=mdb_pv)

    # ================================================================ automation, security, fire
    for k in range(4):
        cx = (k + 0.5) * E.BAY
        m.device("IfcActuator", f"Blind motor {k + 1}", [m.cyl(cx, 0.05, 0.03, CL + 0.02, CL + 0.10)], systems=["CTRL", "ELEC"],
                 predefined="ELECTRICACTUATOR", style="device", z=CL)
    for name, x, y in [("front zone", 10.7, 3.0), ("back zone", 10.7, 9.0), ("corridor", 10.7, 6.0), ("side zone", 0.3, 6.0)]:
        m.device("IfcSensor", f"Room temperature / humidity sensor {name}", [m.box(x - 0.05, y - 0.05, FL + 1.45, x + 0.05, y + 0.05, FL + 1.55)],
                 systems=["CTRL", "HTG"], predefined="TEMPERATURESENSOR", style="device", z=FL + 1.4)
    for name, x, y in [("front zone", 5.5, 2.0), ("back zone", 5.5, 10.0), ("corridor", 9.6, 5.0)]:
        m.device("IfcSensor", f"Smoke detector {name}", [m.cyl(x, y, 0.06, CL - 0.05, CL)], systems=["SEC", "CTRL"],
                 predefined="SMOKESENSOR", style="device", z=CL - 0.05)
    m.device("IfcSensor", "Weather station (wind, rain, light)", [m.cyl(10.4, 11.3, 0.03, GT, GT + 1.4), m.cyl(10.4, 11.3, 0.10, GT + 1.4, GT + 1.55)],
             systems=["CTRL"], predefined="WINDSENSOR", style="device", z=GT)
    for name, x, y, z in [("street gate", 0.6, -15.6, 2.4), ("front soffit", 0.3, 0.3, E.BOTTOM - 0.1), ("back soffit", 10.7, 11.7, E.BOTTOM - 0.1)]:
        m.device("IfcAudioVisualAppliance", f"Security camera {name}", [m.box(x - 0.06, y - 0.06, z - 0.12, x + 0.06, y + 0.06, z)],
                 systems=["SEC"], predefined="CAMERA", style="device", z=z)
    bus = [(2.98, 6.20, 1.70), (2.98, 6.20, 2.45), (3.40, 6.20, 2.45), (3.40, 7.40, 2.45), (3.40, 7.40, GT + 0.05), (10.4, 7.40, GT + 0.05),
           (10.4, 11.3, GT + 0.05)]
    m.run("CTRL", "KNX bus trunk (controller -> shaft -> roof weather station)", bus, 0.012, kind="cable")

    return m.count
