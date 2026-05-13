#!/usr/bin/env python3
"""Patch script: Insert new features into egbim_mcp_server.py"""
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src", "egbim_mcp", "egbim_mcp_server.py")

with open(SRC, "r", encoding="utf-8") as f:
    code = f.read()

# ============================================================
# PART A: Insert helper methods + 5 feature methods into IcadConnection
# Insert BEFORE "    # -- entity creation"
# ============================================================

NEW_METHODS = r'''
    # -- helpers ---------------------------------------------------------------

    def _make_point(self, pt):
        """list -> COM VARIANT point (3D)."""
        return win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_R8,
            [pt[0], pt[1], pt[2] if len(pt) > 2 else 0.0]
        )

    def _run_lisp_with_result(self, lisp_code, timeout_iter=80):
        """SendCommand + temp file pattern.
        lisp_code must contain {TMP} placeholder for the temp path.
        Sends ESC first to cancel any pending command.
        Reads result with cp949 encoding."""
        import time as _t
        fd, tmp_raw = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        os.remove(tmp_raw)
        tmp = tmp_raw.replace("\\", "/")
        lisp_code = lisp_code.replace("{TMP}", tmp)
        self.doc.SendCommand("\x03\x03")
        self.doc.SendCommand(lisp_code + "\n")
        for _ in range(timeout_iter):
            if os.path.exists(tmp_raw):
                break
            _t.sleep(0.1)
        if not os.path.exists(tmp_raw):
            raise RuntimeError(
                "LISP \uc2e4\ud589 \ud6c4 \uacb0\uacfc \ud30c\uc77c\uc774 "
                "\uc0dd\uc131\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4"
            )
        with open(tmp_raw, "r", encoding="cp949", errors="replace") as f:
            result = f.read().strip()
        os.remove(tmp_raw)
        return result

    # -- offset ----------------------------------------------------------------

    def offset_entity(self, handle, distance, point_on_side):
        """Offset entity via OFFSET command + entlast."""
        px, py = point_on_side[0], point_on_side[1]
        lisp = (
            '(setq _eh (handent "' + handle + '"))'
            '(setq _f (open "{TMP}" "w"))'
            '(if _eh'
            '  (progn'
            '    (setq _before (entlast))'
            '    (command "._OFFSET" ' + str(distance)
            + ' _eh (list ' + str(px) + ' ' + str(py) + ' 0.0) "")'
            '    (setq _after (entlast))'
            '    (if (not (eq _before _after))'
            '      (write-line (cdr (assoc 5 (entget _after))) _f)'
            '      (write-line "FAIL" _f)))'
            '  (write-line "NOTFOUND" _f))'
            '(close _f)'
        )
        result = self._run_lisp_with_result(lisp)
        if result == "NOTFOUND":
            raise ValueError(
                "\ud578\ub4e4 '" + handle + "'\uc5d0 \ud574\ub2f9\ud558\ub294 "
                "\uc5d4\ud2f0\ud2f0\ub97c \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4"
            )
        if result == "FAIL":
            raise RuntimeError(
                "OFFSET \uc2e4\ud328. \uc5d4\ud2f0\ud2f0\uac00 OFFSET\uc744 "
                "\uc9c0\uc6d0\ud558\uc9c0 \uc54a\uc744 \uc218 \uc788\uc2b5\ub2c8\ub2e4"
            )
        return {"source_handle": handle, "new_handle": result, "distance": distance}

    # -- hatch -----------------------------------------------------------------

    def create_hatch(self, boundary_handles, pattern_name="SOLID",
                     pattern_type=1, scale=1.0, angle=0.0,
                     color=None, layer=None):
        """Create hatch. COM first, LISP fallback."""
        ents = []
        for h in boundary_handles:
            try:
                ents.append(self.doc.HandleToObject(h))
            except Exception:
                raise ValueError(
                    "\uacbd\uacc4 \uc5d4\ud2f0\ud2f0 \ud578\ub4e4 '"
                    + h + "'\uc744 \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4"
                )
        # Try COM
        try:
            hatch = self.mspace.AddHatch(pattern_type, pattern_name, False)
            ent_array = win32com.client.VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, ents
            )
            hatch.AppendOuterLoop(ent_array)
            hatch.PatternScale = scale
            hatch.PatternAngle = math.radians(angle)
            if layer:
                hatch.Layer = layer
            if color is not None:
                hatch.Color = color
            hatch.Evaluate()
            hatch.Update()
            return {
                "handle": hatch.Handle, "type": "Hatch",
                "pattern": pattern_name, "method": "COM",
            }
        except Exception as com_err:
            logger.warning("COM AddHatch failed (%s), trying SendCommand", com_err)

        # Fallback: LISP -BHATCH
        sel_lisp = "(setq _ss (ssadd))"
        for h in boundary_handles:
            sel_lisp += '(ssadd (handent "' + h + '") _ss)'
        lisp = (
            sel_lisp
            + '(command "._-BHATCH" "P" "' + pattern_name + '" '
            + str(scale) + " " + str(angle)
            + ' "S" _ss "" "")'
            + '(setq _f (open "{TMP}" "w"))'
            + "(setq _new (entlast))"
            + "(write-line (cdr (assoc 5 (entget _new))) _f)"
            + "(close _f)"
        )
        result = self._run_lisp_with_result(lisp)
        if not result:
            raise RuntimeError(
                "HATCH \uc0dd\uc131 \uc2e4\ud328. "
                "\uacbd\uacc4\uac00 \ub2eb\ud600\uc788\ub294\uc9c0 \ud655\uc778\ud558\uc138\uc694"
            )
        try:
            h_ent = self.doc.HandleToObject(result)
            if layer:
                h_ent.Layer = layer
            if color is not None:
                h_ent.Color = color
            h_ent.Update()
        except Exception:
            pass
        return {
            "handle": result, "type": "Hatch",
            "pattern": pattern_name, "method": "SendCommand",
        }

    # -- dimension -------------------------------------------------------------

    def create_dim_aligned(self, ext1, ext2, text_pos,
                           text_override="", layer=None,
                           color=None, dim_style=None):
        """Create aligned dimension."""
        p1, p2, tp = self._make_point(ext1), self._make_point(ext2), self._make_point(text_pos)
        try:
            dim = self.mspace.AddDimAligned(p1, p2, tp)
        except Exception:
            # LISP fallback
            lisp = (
                '(command "._DIMALIGNED" '
                '(list ' + str(ext1[0]) + ' ' + str(ext1[1]) + ') '
                '(list ' + str(ext2[0]) + ' ' + str(ext2[1]) + ') '
                '(list ' + str(text_pos[0]) + ' ' + str(text_pos[1]) + '))'
                '(setq _f (open "{TMP}" "w"))'
                '(write-line (cdr (assoc 5 (entget (entlast)))) _f)'
                '(close _f)'
            )
            result = self._run_lisp_with_result(lisp)
            dim = self.doc.HandleToObject(result)
        if text_override:
            dim.TextOverride = text_override
        if layer:
            dim.Layer = layer
        if color is not None:
            dim.Color = color
        if dim_style:
            try:
                dim.StyleName = dim_style
            except Exception:
                pass
        dim.Update()
        return {"handle": dim.Handle, "type": "DimAligned"}

    def create_dim_rotated(self, ext1, ext2, text_pos,
                           rotation_angle=0.0, text_override="",
                           layer=None, color=None, dim_style=None):
        """Create rotated dimension."""
        p1, p2, tp = self._make_point(ext1), self._make_point(ext2), self._make_point(text_pos)
        try:
            dim = self.mspace.AddDimRotated(p1, p2, tp, math.radians(rotation_angle))
        except Exception:
            lisp = (
                '(command "._DIMROTATED" '
                + str(rotation_angle) + ' '
                '(list ' + str(ext1[0]) + ' ' + str(ext1[1]) + ') '
                '(list ' + str(ext2[0]) + ' ' + str(ext2[1]) + ') '
                '(list ' + str(text_pos[0]) + ' ' + str(text_pos[1]) + '))'
                '(setq _f (open "{TMP}" "w"))'
                '(write-line (cdr (assoc 5 (entget (entlast)))) _f)'
                '(close _f)'
            )
            result = self._run_lisp_with_result(lisp)
            dim = self.doc.HandleToObject(result)
        if text_override:
            dim.TextOverride = text_override
        if layer:
            dim.Layer = layer
        if color is not None:
            dim.Color = color
        if dim_style:
            try:
                dim.StyleName = dim_style
            except Exception:
                pass
        dim.Update()
        return {"handle": dim.Handle, "type": "DimRotated"}

    def create_dim_radial(self, center, chord_point, leader_length,
                          text_override="", layer=None,
                          color=None, dim_style=None):
        """Create radial dimension."""
        cp, ch = self._make_point(center), self._make_point(chord_point)
        try:
            dim = self.mspace.AddDimRadial(cp, ch, leader_length)
        except Exception:
            lisp = (
                '(command "._DIMRADIUS" '
                '(list ' + str(chord_point[0]) + ' ' + str(chord_point[1]) + ') '
                + str(leader_length) + ')'
                '(setq _f (open "{TMP}" "w"))'
                '(write-line (cdr (assoc 5 (entget (entlast)))) _f)'
                '(close _f)'
            )
            result = self._run_lisp_with_result(lisp)
            dim = self.doc.HandleToObject(result)
        if text_override:
            dim.TextOverride = text_override
        if layer:
            dim.Layer = layer
        if color is not None:
            dim.Color = color
        if dim_style:
            try:
                dim.StyleName = dim_style
            except Exception:
                pass
        dim.Update()
        return {"handle": dim.Handle, "type": "DimRadial"}

    def create_dim_angular(self, vertex, point1, point2, text_pos,
                           text_override="", layer=None,
                           color=None, dim_style=None):
        """Create angular dimension."""
        vp = self._make_point(vertex)
        p1, p2 = self._make_point(point1), self._make_point(point2)
        tp = self._make_point(text_pos)
        try:
            dim = self.mspace.AddDimAngular(vp, p1, p2, tp)
        except Exception:
            lisp = (
                '(command "._DIMANGULAR" "" '
                '(list ' + str(vertex[0]) + ' ' + str(vertex[1]) + ') '
                '(list ' + str(point1[0]) + ' ' + str(point1[1]) + ') '
                '(list ' + str(point2[0]) + ' ' + str(point2[1]) + ') '
                '(list ' + str(text_pos[0]) + ' ' + str(text_pos[1]) + '))'
                '(setq _f (open "{TMP}" "w"))'
                '(write-line (cdr (assoc 5 (entget (entlast)))) _f)'
                '(close _f)'
            )
            result = self._run_lisp_with_result(lisp)
            dim = self.doc.HandleToObject(result)
        if text_override:
            dim.TextOverride = text_override
        if layer:
            dim.Layer = layer
        if color is not None:
            dim.Color = color
        if dim_style:
            try:
                dim.StyleName = dim_style
            except Exception:
                pass
        dim.Update()
        return {"handle": dim.Handle, "type": "DimAngular"}

    # -- measure ---------------------------------------------------------------

    def measure_distance(self, point1, point2):
        """Calculate distance between two points."""
        dx = point2[0] - point1[0]
        dy = point2[1] - point1[1]
        dz = (point2[2] if len(point2) > 2 else 0.0) - (point1[2] if len(point1) > 2 else 0.0)
        d2 = math.sqrt(dx * dx + dy * dy)
        d3 = math.sqrt(dx * dx + dy * dy + dz * dz)
        ang = math.degrees(math.atan2(dy, dx))
        return {
            "distance_2d": round(d2, 6),
            "distance_3d": round(d3, 6),
            "delta": {"dx": round(dx, 6), "dy": round(dy, 6), "dz": round(dz, 6)},
            "angle_deg": round(ang, 4),
        }

    def measure_entity(self, handle):
        """Measure length, area, perimeter of an entity."""
        ent = self.doc.HandleToObject(handle)
        etype = ent.EntityName
        result = {"handle": handle, "type": etype}

        if hasattr(ent, "Length"):
            try:
                result["length"] = round(ent.Length, 6)
            except Exception:
                pass

        if hasattr(ent, "Area"):
            try:
                result["area"] = round(ent.Area, 6)
            except Exception:
                pass

        if hasattr(ent, "Closed"):
            result["closed"] = bool(ent.Closed)

        if hasattr(ent, "Radius"):
            try:
                r = ent.Radius
                result["radius"] = round(r, 6)
                result["circumference"] = round(2 * math.pi * r, 6)
                if "area" not in result:
                    result["area"] = round(math.pi * r * r, 6)
            except Exception:
                pass

        if hasattr(ent, "ArcLength"):
            try:
                result["arc_length"] = round(ent.ArcLength, 6)
            except Exception:
                pass

        # Shoelace fallback for area from coordinates
        if "area" not in result and hasattr(ent, "Coordinates"):
            try:
                raw = ent.Coordinates
                pts = []
                for pt in raw:
                    try:
                        pts.append((pt.X, pt.Y))
                    except Exception:
                        pts.append((pt.x, pt.y))
                if len(pts) >= 3:
                    n = len(pts)
                    area = 0.0
                    for i in range(n):
                        j = (i + 1) % n
                        area += pts[i][0] * pts[j][1]
                        area -= pts[j][0] * pts[i][1]
                    result["area"] = round(abs(area) / 2.0, 6)
                    peri = 0.0
                    for i in range(n):
                        j = (i + 1) % n
                        ddx = pts[j][0] - pts[i][0]
                        ddy = pts[j][1] - pts[i][1]
                        peri += math.sqrt(ddx * ddx + ddy * ddy)
                    result["perimeter"] = round(peri, 6)
                    result["vertex_count"] = n
                    result["note_shoelace"] = (
                        "Shoelace formula used; "
                        "arc-bulge segments may cause inaccuracy"
                    )
            except Exception:
                pass

        return result

'''

# Insert before "    # -- entity creation"
marker = "    # -- entity creation -------------------------------------------------------"
if marker in code:
    code = code.replace(marker, NEW_METHODS + "\n" + marker)
    print("Part A: IcadConnection methods inserted")
else:
    print("ERROR: entity creation marker not found")


# ============================================================
# PART B: Replace get_layers to add new properties
# ============================================================

OLD_GET_LAYERS = '''    def get_layers(self) -> list:
        layers = []
        for layer in self.doc.Layers:
            layers.append({
                "name": layer.Name,
                "on": layer.LayerOn,
                "frozen": layer.Freeze,
                "locked": layer.Lock,
                "color": layer.Color,
                "linetype": layer.Linetype,
            })
        return layers'''

NEW_GET_LAYERS = '''    def get_layers(self) -> list:
        layers = []
        for layer in self.doc.Layers:
            info = {
                "name": layer.Name,
                "on": layer.LayerOn,
                "frozen": layer.Freeze,
                "locked": layer.Lock,
                "color": layer.Color,
                "linetype": layer.Linetype,
            }
            try:
                info["lineweight"] = layer.Lineweight
            except Exception:
                pass
            try:
                info["plottable"] = layer.Plottable
            except Exception:
                pass
            layers.append(info)
        return layers'''

code = code.replace(OLD_GET_LAYERS, NEW_GET_LAYERS)
print("Part B: get_layers updated")


# ============================================================
# PART C: Replace set_layer to add lineweight, freeze, plottable
# ============================================================

OLD_SET_LAYER = '''    def set_layer(self, name: str, color: Optional[int] = None,
                  on: Optional[bool] = None, locked: Optional[bool] = None,
                  linetype: Optional[str] = None) -> dict:
        """Create layer if it doesn't exist, then set properties."""
        try:
            layer = self.doc.Layers.Item(name)
        except Exception:
            layer = self.doc.Layers.Add(name)

        if color is not None:
            layer.Color = color
        if on is not None:
            layer.LayerOn = on
        if locked is not None:
            layer.Lock = locked
        if linetype is not None:
            layer.Linetype = linetype

        return {"layer": name, "action": "set"}'''

NEW_SET_LAYER = '''    def set_layer(self, name: str, color: Optional[int] = None,
                  on: Optional[bool] = None, locked: Optional[bool] = None,
                  linetype: Optional[str] = None,
                  lineweight: Optional[int] = None,
                  frozen: Optional[bool] = None,
                  plottable: Optional[bool] = None) -> dict:
        """Create layer if it doesn't exist, then set properties.
        lineweight: 1/100 mm (-3=Default, 0,5,9,13,...,211).
        frozen: True=freeze (cannot freeze active layer)."""
        try:
            layer = self.doc.Layers.Item(name)
        except Exception:
            layer = self.doc.Layers.Add(name)

        changed = []
        if color is not None:
            layer.Color = color
            changed.append("color")
        if on is not None:
            layer.LayerOn = on
            changed.append("on")
        if locked is not None:
            layer.Lock = locked
            changed.append("locked")
        if linetype is not None:
            layer.Linetype = linetype
            changed.append("linetype")
        if lineweight is not None:
            try:
                layer.Lineweight = lineweight
                changed.append("lineweight")
            except Exception as e:
                logger.warning("Lineweight set failed: %s", e)
        if frozen is not None:
            if frozen and layer.Name == self.doc.ActiveLayer.Name:
                raise ValueError(
                    "\ud604\uc7ac \ud65c\uc131 \ub808\uc774\uc5b4\ub294 "
                    "\ub3d9\uacb0\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4"
                )
            layer.Freeze = frozen
            changed.append("frozen")
        if plottable is not None:
            try:
                layer.Plottable = plottable
                changed.append("plottable")
            except Exception as e:
                logger.warning("Plottable set failed: %s", e)

        return {"layer": name, "action": "set", "changed": changed}'''

code = code.replace(OLD_SET_LAYER, NEW_SET_LAYER)
print("Part C: set_layer updated")


# ============================================================
# PART D: Replace MCP set_layer tool wrapper
# ============================================================

OLD_SET_LAYER_TOOL = '''@mcp.tool()
def set_layer(ctx: Context, name: str, color: int = -1,
              on: bool = True, locked: bool = False,
              linetype: str = "") -> str:
    """\ub808\uc774\uc5b4 \uc0dd\uc131 \ub610\ub294 \uc18d\uc131 \uc124\uc815. \uc5c6\uc73c\uba74 \uc790\ub3d9 \uc0dd\uc131."""
    try:
        kwargs = {}
        if color >= 0:
            kwargs["color"] = color
        kwargs["on"] = on
        kwargs["locked"] = locked
        if linetype:
            kwargs["linetype"] = linetype
        return _ok(get_icad().set_layer(name, **kwargs))
    except Exception as e:
        return _err(e)'''

NEW_SET_LAYER_TOOL = '''@mcp.tool()
def set_layer(ctx: Context, name: str, color: int = -1,
              on: bool = True, locked: bool = False,
              linetype: str = "", lineweight: int = -99,
              frozen: bool = False, plottable: bool = True) -> str:
    """\ub808\uc774\uc5b4 \uc0dd\uc131 \ub610\ub294 \uc18d\uc131 \uc124\uc815. \uc5c6\uc73c\uba74 \uc790\ub3d9 \uc0dd\uc131.
    lineweight: \uc120 \uac00\uc911\uce58 (1/100mm). -3=Default, 0/5/9/13/15/18/20/25/30/35/40/50/60/80/100/120/140/200/211.
    frozen: True=\ub3d9\uacb0 (\ud65c\uc131 \ub808\uc774\uc5b4 \ubd88\uac00). plottable: \ucd9c\ub825 \uc5ec\ubd80."""
    try:
        kwargs = {}
        if color >= 0:
            kwargs["color"] = color
        kwargs["on"] = on
        kwargs["locked"] = locked
        if linetype:
            kwargs["linetype"] = linetype
        if lineweight != -99:
            kwargs["lineweight"] = lineweight
        if frozen:
            kwargs["frozen"] = frozen
        if not plottable:
            kwargs["plottable"] = plottable
        return _ok(get_icad().set_layer(name, **kwargs))
    except Exception as e:
        return _err(e)'''

code = code.replace(OLD_SET_LAYER_TOOL, NEW_SET_LAYER_TOOL)
print("Part D: set_layer MCP tool updated")


# ============================================================
# PART E: Add new MCP tool wrappers before entry point
# ============================================================

NEW_TOOLS = '''
# -- offset --------------------------------------------------------------------

@mcp.tool()
def offset_entity(ctx: Context, handle: str, distance: float,
                  side_x: float, side_y: float) -> str:
    """\uc5d4\ud2f0\ud2f0 \uac04\uaca9\ub744\uc6b0\uae30(Offset). handle: \ub300\uc0c1 \uc5d4\ud2f0\ud2f0 \ud578\ub4e4.
    distance: \uac04\uaca9 \uac70\ub9ac. side_x/side_y: \uc624\ud504\uc14b \ubc29\ud5a5\uc744 \ub098\ud0c0\ub0b4\ub294 \uc810.
    Line, Polyline, Arc, Circle \uc9c0\uc6d0."""
    try:
        return _ok(get_icad().offset_entity(handle, distance, [side_x, side_y]))
    except Exception as e:
        return _err(e)


# -- hatch ---------------------------------------------------------------------

@mcp.tool()
def create_hatch(ctx: Context, boundary_handles: str,
                 pattern_name: str = "SOLID", pattern_type: int = 1,
                 scale: float = 1.0, angle: float = 0.0,
                 layer: str = "", color: int = -1) -> str:
    """\ud574\uce58(Hatch) \uc0dd\uc131. boundary_handles: \uacbd\uacc4 \uc5d4\ud2f0\ud2f0 \ud578\ub4e4 JSON \ubc30\uc5f4 ([\\"A1\\",\\"A2\\"]).
    pattern_name: SOLID, ANSI31, ANSI37, EARTH, GRAVEL \ub4f1.
    pattern_type: 0=\uc0ac\uc6a9\uc790\uc815\uc758, 1=\uc0ac\uc804\uc815\uc758, 2=\uc0ac\uc6a9\uc790.
    scale: \ud328\ud134 \ucd95\uccc. angle: \ud328\ud134 \uac01\ub3c4(\ub3c4)."""
    try:
        handles = json.loads(boundary_handles)
        return _ok(get_icad().create_hatch(
            handles, pattern_name=pattern_name,
            pattern_type=pattern_type, scale=scale, angle=angle,
            color=color if color >= 0 else None,
            layer=layer or None,
        ))
    except Exception as e:
        return _err(e)


# -- dimension -----------------------------------------------------------------

@mcp.tool()
def create_dimension(ctx: Context, dim_type: str,
                     x1: float, y1: float, x2: float, y2: float,
                     text_x: float, text_y: float,
                     rotation_angle: float = 0.0,
                     text_override: str = "",
                     dim_style: str = "",
                     layer: str = "", color: int = -1) -> str:
    """\uce58\uc218\uc120 \uc0dd\uc131. dim_type: aligned | rotated | radial.
    aligned/rotated: (x1,y1)-(x2,y2) \uce58\uc218\ubcf4\uc870\uc120 \uc6d0\uc810, (text_x,text_y) \uce58\uc218\ubb38\uc790 \uc704\uce58.
    rotated: rotation_angle=\uce58\uc218\uc120 \uac01\ub3c4(\ub3c4).
    radial: (x1,y1)=\uc911\uc2ec, (x2,y2)=\uc6d0\uc8fc\uc810, rotation_angle=\uc9c0\uc2dc\uc120 \uae38\uc774.
    text_override: \uce58\uc218 \ubb38\uc790 \uac15\uc81c \uc9c0\uc815."""
    try:
        icad = get_icad()
        kw = {
            "text_override": text_override or "",
            "layer": layer or None,
            "color": color if color >= 0 else None,
            "dim_style": dim_style or None,
        }
        dt = dim_type.lower()
        if dt == "aligned":
            return _ok(icad.create_dim_aligned(
                [x1, y1], [x2, y2], [text_x, text_y], **kw))
        elif dt == "rotated":
            return _ok(icad.create_dim_rotated(
                [x1, y1], [x2, y2], [text_x, text_y],
                rotation_angle=rotation_angle, **kw))
        elif dt == "radial":
            return _ok(icad.create_dim_radial(
                [x1, y1], [x2, y2], leader_length=rotation_angle, **kw))
        else:
            raise ValueError(
                "\uc9c0\uc6d0\ud558\uc9c0 \uc54a\ub294 \uce58\uc218 \uc720\ud615: " + dim_type
                + ". aligned, rotated, radial \uc911 \uc120\ud0dd\ud558\uc138\uc694"
            )
    except Exception as e:
        return _err(e)


@mcp.tool()
def create_dim_angular(ctx: Context,
                       vertex_x: float, vertex_y: float,
                       p1_x: float, p1_y: float,
                       p2_x: float, p2_y: float,
                       text_x: float, text_y: float,
                       text_override: str = "",
                       dim_style: str = "",
                       layer: str = "", color: int = -1) -> str:
    """\uac01\ub3c4 \uce58\uc218\uc120 \uc0dd\uc131. vertex: \uaf2d\uc9d3\uc810, p1/p2: \ub450 \uc120\uc758 \ub05d\uc810, text: \uce58\uc218\ubb38\uc790 \uc704\uce58."""
    try:
        return _ok(get_icad().create_dim_angular(
            [vertex_x, vertex_y], [p1_x, p1_y], [p2_x, p2_y],
            [text_x, text_y],
            text_override=text_override or "",
            layer=layer or None,
            color=color if color >= 0 else None,
            dim_style=dim_style or None,
        ))
    except Exception as e:
        return _err(e)


# -- measure -------------------------------------------------------------------

@mcp.tool()
def measure_distance(ctx: Context, x1: float, y1: float,
                     x2: float, y2: float,
                     z1: float = 0.0, z2: float = 0.0) -> str:
    """\ub450 \uc810 \uac04 \uac70\ub9ac \uce21\uc815. 2D/3D \uac70\ub9ac, \uac01\ub3c4, \ub378\ud0c0\uac12 \ubc18\ud658."""
    try:
        return _ok(get_icad().measure_distance([x1, y1, z1], [x2, y2, z2]))
    except Exception as e:
        return _err(e)


@mcp.tool()
def measure_entity(ctx: Context, handle: str) -> str:
    """\uc5d4\ud2f0\ud2f0 \uce21\uc815. Polyline(\uba74\uc801/\ub458\ub808), Circle(\uba74\uc801/\ub458\ub808),
    Line(\uae38\uc774), Arc(\ud638 \uae38\uc774) \ub4f1. Shoelace \uacf5\uc2dd \ud3f4\ubc31 \ud3ec\ud568."""
    try:
        return _ok(get_icad().measure_entity(handle))
    except Exception as e:
        return _err(e)


'''

# Insert before "# -- entry point"
entry_marker = "# -- entry point ---------------------------------------------------------------"
if entry_marker in code:
    code = code.replace(entry_marker, NEW_TOOLS + entry_marker)
    print("Part E: New MCP tools inserted")
else:
    print("ERROR: entry point marker not found")


# ============================================================
# WRITE
# ============================================================
with open(SRC, "w", encoding="utf-8") as f:
    f.write(code)

print("\nAll patches applied successfully!")
