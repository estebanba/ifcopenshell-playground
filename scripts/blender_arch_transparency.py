"""Toggle see-through architecture in Bonsai so MEP can be inspected (viewport only; the IFC is untouched).

Run inside Blender (Text Editor > Run Script, or via the MCP `execute_blender_code` tool).
Set ALPHA to 1.0 to restore the original look. Original material alphas are remembered in a
custom property on each material, so glass and water keep their own transparency on restore.

Architecture = every IFC object that is NOT an IfcDistributionElement (pipes, ducts, cables,
fittings, terminals, equipment and controls stay opaque). Spaces, openings and shading
devices (dozens of stacked slats stay dark even when transparent) are hidden while
transparency is on.
"""
import bpy
import bonsai.tool as tool

ALPHA = 0.12


def apply(alpha=ALPHA):
    arch_mats, n_arch, n_mep = set(), 0, 0
    for obj in bpy.data.objects:
        el = tool.Ifc.get_entity(obj) if obj.type in ("MESH", "CURVE") else None   # swept pipes load as curves
        if el is None:
            continue
        if el.is_a("IfcDistributionElement"):
            n_mep += 1
            continue
        if el.is_a("IfcSpace") or el.is_a("IfcOpeningElement") or el.is_a("IfcShadingDevice"):
            obj.hide_set(alpha < 1.0)
            continue
        n_arch += 1
        arch_mats.update(s.material for s in obj.material_slots if s.material)
    for mat in arch_mats:
        if "_orig_alpha" not in mat:
            mat["_orig_alpha"] = mat.diffuse_color[3]
        a = mat["_orig_alpha"] if alpha >= 1.0 else min(alpha, mat["_orig_alpha"])
        c = mat.diffuse_color
        mat.diffuse_color = (c[0], c[1], c[2], a)
        if mat.use_nodes:
            bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf:
                bsdf.inputs["Alpha"].default_value = a
        try:
            mat.surface_render_method = "BLENDED" if a < 1.0 else "DITHERED"
        except (AttributeError, TypeError):
            pass
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            area.spaces.active.shading.color_type = "MATERIAL"
    return n_arch, n_mep, len(arch_mats)


if __name__ == "__main__":
    print("architecture objects, MEP objects, materials changed:", apply())
