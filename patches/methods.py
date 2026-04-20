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
            raise RuntimeError("LISP 실행 후 결과 파일이 생성되지 않았습니다")
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
            raise ValueError("핸들 '" + handle + "'에 해당하는 엔티티를 찾을 수 없습니다")
        if result == "FAIL":
            raise RuntimeError("OFFSET 실패. 엔티티가 OFFSET을 지원하지 않을 수 있습니다")
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
                raise ValueError("경계 엔티티 핸들 '" + h + "'을 찾을 수 없습니다")
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
            raise RuntimeError("HATCH 생성 실패. 경계가 닫혀있는지 확인하세요")
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
        """Create aligned dimension. COM first, LISP fallback."""
        p1, p2, tp = self._make_point(ext1), self._make_point(ext2), self._make_point(text_pos)
        try:
            dim = self.mspace.AddDimAligned(p1, p2, tp)
        except Exception:
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
        """Create rotated dimension. COM first, LISP fallback."""
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
        """Create radial dimension. COM first, LISP fallback."""
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
        """Create angular dimension. COM first, LISP fallback."""
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
                    result["note_shoelace"] = "Shoelace formula; arc-bulge segments may be inaccurate"
            except Exception:
                pass

        return result

