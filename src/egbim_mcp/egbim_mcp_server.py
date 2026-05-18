#!/usr/bin/env python3
"""
EG-BIM (IntelliCAD) MCP Server - COM automation for IntelliCAD via MCP
"""

import logging
import json
import math
import array
import subprocess
import os
import tempfile
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Optional

import pythoncom
import win32com.client

from mcp.server.fastmcp import FastMCP, Context

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("EgbimMCPServer")

# IntelliCAD COM ProgID
ICAD_PROGID = "Icad.Application.1.3.x64"

# --- IntelliCAD COM wrapper ---------------------------------------------------

class IcadConnection:
    """Wrapper around IntelliCAD COM automation."""

    def __init__(self):
        self.app = None

    # -- lifecycle -------------------------------------------------------------

    def connect(self) -> bool:
        """Attach to a running IntelliCAD (EG-BIM) instance."""
        try:
            pythoncom.CoInitialize()
            self.app = win32com.client.GetActiveObject(ICAD_PROGID)
            logger.info("Connected to IntelliCAD: %s", self.app.Caption)
            return True
        except Exception:
            # Fallback: try without version suffix
            try:
                self.app = win32com.client.GetActiveObject("Icad.Application")
                logger.info("Connected to IntelliCAD (fallback ProgID)")
                return True
            except Exception as exc:
                logger.error("Cannot connect to IntelliCAD: %s", exc)
                self.app = None
                return False

    def disconnect(self):
        self.app = None

    @property
    def doc(self):
        """Shortcut to ActiveDocument."""
        if not self.app:
            raise RuntimeError("Not connected to IntelliCAD")
        return self.app.ActiveDocument

    @property
    def mspace(self):
        """Shortcut to ModelSpace."""
        return self.doc.ModelSpace

    # -- info ------------------------------------------------------------------

    def ping(self) -> dict:
        _ = self.doc.Name
        return {"status": "pong", "drawing": self.doc.Name}

    def health_check(self) -> dict:
        import time
        result = {
            "progid": ICAD_PROGID,
            "connected": self.app is not None,
        }
        if self.app is None:
            return result

        try:
            result["caption"] = self.app.Caption
            result["version"] = getattr(self.app, "Version", "unknown")
        except Exception as exc:
            result["app_error"] = f"{type(exc).__name__}: {exc}"
            return result

        try:
            result["documents_count"] = self.app.Documents.Count
        except Exception as exc:
            result["documents_error"] = f"{type(exc).__name__}: {exc}"

        t0 = time.perf_counter()
        try:
            doc_name = self.doc.Name
            result["active_document"] = doc_name
            result["active_document_path"] = self.doc.FullName
            result["ping_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            result["responsive"] = True
        except Exception as exc:
            result["ping_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            result["responsive"] = False
            result["doc_error"] = f"{type(exc).__name__}: {exc}"
        return result

    def get_info(self) -> dict:
        app = self.app
        return {
            "application": app.Caption,
            "version": getattr(app, "Version", "unknown"),
            "drawing": self.doc.Name,
            "path": self.doc.Path,
            "full_name": self.doc.FullName,
        }

    def list_documents(self) -> list:
        docs = self.app.Documents
        result = []
        for i in range(docs.Count):
            doc = docs.Item(i)
            result.append({
                "index": i,
                "name": doc.Name,
                "full_name": doc.FullName,
                "active": doc.FullName == self.app.ActiveDocument.FullName,
            })
        return result

    def activate_document(self, name: str) -> dict:
        docs = self.app.Documents
        for i in range(docs.Count):
            doc = docs.Item(i)
            if name.lower() in doc.Name.lower() or name.lower() in doc.FullName.lower():
                doc.Activate()
                return {"activated": doc.FullName}
        raise ValueError(f"도면을 찾을 수 없습니다: {name}")

    # -- drawing management ----------------------------------------------------

    def open_drawing(self, path: str, read_only: bool = False) -> dict:
        doc = self.app.Documents.Open(path, read_only)
        return {"opened": doc.FullName}

    def save_drawing(self, path: Optional[str] = None) -> dict:
        if path:
            self.doc.SaveAs(path)
        else:
            self.doc.Save()
        return {"saved": self.doc.FullName}

    def close_drawing(self, save: bool = True) -> dict:
        name = self.doc.FullName
        if save:
            self.doc.Save()
        self.doc.Close()
        return {"closed": name}

    def get_drawing_info(self) -> dict:
        doc = self.doc
        try:
            limits = {
                "lower_left": [doc.GetVariable("LIMMIN")[0], doc.GetVariable("LIMMIN")[1]],
                "upper_right": [doc.GetVariable("LIMMAX")[0], doc.GetVariable("LIMMAX")[1]],
            }
        except Exception:
            limits = "unavailable"
        return {
            "name": doc.Name,
            "path": doc.Path,
            "full_name": doc.FullName,
            "saved": doc.Saved,
            "limits": limits,
        }

    # -- layer management ------------------------------------------------------

    def get_layers(self) -> list:
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
        return layers

    def set_layer(self, name: str, color: Optional[int] = None,
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

        return {"layer": name, "action": "set"}

    def set_active_layer(self, name: str) -> dict:
        layer = self.doc.Layers.Item(name)
        self.doc.ActiveLayer = layer
        return {"active_layer": name}

    # -- entity query ----------------------------------------------------------

    @staticmethod
    def _get_color(ent) -> Optional[int]:
        """ColorIndex를 정수로 반환. ByLayer=256, ByBlock=0."""
        try:
            return int(ent.ColorIndex)
        except Exception:
            pass
        try:
            return int(ent.Color.ColorIndex)
        except Exception:
            pass
        return None

    def get_entities(self, layer: Optional[str] = None,
                     entity_type: Optional[str] = None,
                     limit: int = 100,
                     bbox_min: Optional[List[float]] = None,
                     bbox_max: Optional[List[float]] = None) -> list:
        """List entities in ModelSpace, optionally filtered.
        bbox_min/bbox_max: [x,y] 영역 필터. 지정 시 해당 영역과 겨치는 엔티티만 반환."""
        results = []
        count = 0
        use_bbox = bbox_min is not None and bbox_max is not None
        for i in range(self.mspace.Count):
            if count >= limit:
                break
            ent = self.mspace.Item(i)
            if layer and ent.Layer != layer:
                continue
            if entity_type and ent.EntityName.lower() != entity_type.lower():
                continue
            # Bounding box — GetBoundingBox() returns COM SAFEARRAY; index access works, list() does not
            ent_bbox_min = None
            ent_bbox_max = None
            try:
                _min, _max = ent.GetBoundingBox()
                ent_bbox_min = [_min[0], _min[1]]
                ent_bbox_max = [_max[0], _max[1]]
            except Exception:
                pass
            # Fallback for entities where GetBoundingBox fails (e.g. TEXT): use InsertionPoint as a point
            if ent_bbox_min is None and hasattr(ent, 'InsertionPoint'):
                try:
                    ip = ent.InsertionPoint
                    try:
                        x, y = ip[0], ip[1]
                    except (TypeError, AttributeError):
                        x, y = ip.X, ip.Y
                    ent_bbox_min = [x, y]
                    ent_bbox_max = [x, y]
                except Exception:
                    pass
            # bbox filter: skip if entity bbox doesn't overlap query bbox
            if use_bbox:
                if ent_bbox_min is None:
                    continue  # no bbox = skip
                if (ent_bbox_max[0] < bbox_min[0] or ent_bbox_min[0] > bbox_max[0] or
                        ent_bbox_max[1] < bbox_min[1] or ent_bbox_min[1] > bbox_max[1]):
                    continue
            info = {
                "index": i,
                "handle": ent.Handle,
                "type": ent.EntityName,
                "layer": ent.Layer,
                "color": self._get_color(ent),
                "visible": ent.Visible,
            }
            if ent_bbox_min:
                info["bbox_min"] = ent_bbox_min
                info["bbox_max"] = ent_bbox_max
            results.append(info)
            count += 1
        return results


    def count_entities(self, layer: Optional[str] = None,
                       entity_type: Optional[str] = None) -> dict:
        """엔티티 개수 조회. 전체를 반환하지 않고 개수만 카운트."""
        total = 0
        matched = 0
        for i in range(self.mspace.Count):
            total += 1
            ent = self.mspace.Item(i)
            if layer and ent.Layer != layer:
                continue
            if entity_type and ent.EntityName.lower() != entity_type.lower():
                continue
            matched += 1
        return {"total": total, "matched": matched}

    def get_entity_by_handle(self, handle: str) -> dict:
        ent = self.doc.HandleToObject(handle)

        def safe_get(obj, attr, default=None):
            try:
                val = getattr(obj, attr)
                # COM VARIANT 배열 → list 변환
                if hasattr(val, '__iter__') and not isinstance(val, str):
                    return list(val)
                return val
            except Exception:
                return default

        info = {
            "handle": ent.Handle,
            "type": ent.EntityName,
            "layer": safe_get(ent, "Layer"),
            "color": self._get_color(ent),
            "linetype": safe_get(ent, "Linetype"),
            "visible": safe_get(ent, "Visible"),
        }
        # Bounding box
        try:
            _min, _max = ent.GetBoundingBox()
            info["bbox_min"] = [_min[0], _min[1]]
            info["bbox_max"] = [_max[0], _max[1]]
        except Exception:
            pass
        # Polyline-specific: coordinates
        # IntelliCAD COM returns Coordinates as a collection of Point objects with .X/.Y/.Z
        if hasattr(ent, "Coordinates"):
            try:
                raw = ent.Coordinates
                pts = []
                for pt in raw:
                    try:
                        pts.append([pt.X, pt.Y])
                    except Exception:
                        # fallback: index access
                        pts.append([pt.x, pt.y])
                info["coordinates"] = pts
                info["vertex_count"] = len(pts)
            except Exception as e:
                info["coordinates_error"] = str(e)
        # Text-specific — COM BSTR for Korean text may arrive as Latin-1 bytes; decode as cp949
        if hasattr(ent, "TextString"):
            text = safe_get(ent, "TextString") or ""
            try:
                text = text.encode("latin-1").decode("cp949")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
            info["text"] = text
        if hasattr(ent, "InsertionPoint"):
            try:
                ip = ent.InsertionPoint
                try:
                    info["insertion_point"] = [ip[0], ip[1]]
                except (TypeError, AttributeError):
                    info["insertion_point"] = [ip.X, ip.Y]
            except Exception:
                pass
        # Circle/Arc-specific
        if hasattr(ent, "Radius"):
            info["radius"] = safe_get(ent, "Radius")
        if hasattr(ent, "Center"):
            info["center"] = safe_get(ent, "Center")
        return info

    # -- selection info --------------------------------------------------------

    def get_selection_count(self) -> dict:
        """Get selection set info via PICKFIRST or SelectionSets."""
        try:
            # Try getting active selection via system variable
            ss_count = self.doc.SelectionSets.Count
            return {"selection_sets": ss_count}
        except Exception as exc:
            return {"error": str(exc)}

    # -- entity creation -------------------------------------------------------

    def create_line(self, start: List[float], end: List[float],
                    layer: Optional[str] = None, color: Optional[int] = None) -> dict:
        sp = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                     [start[0], start[1], start[2] if len(start) > 2 else 0.0])
        ep = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                     [end[0], end[1], end[2] if len(end) > 2 else 0.0])
        line = self.mspace.AddLine(sp, ep)
        if layer:
            line.Layer = layer
        if color is not None:
            line.Color = color
        return {"handle": line.Handle, "type": "Line"}

    def create_polyline(self, points: List[List[float]],
                        closed: bool = False,
                        layer: Optional[str] = None,
                        color: Optional[int] = None) -> dict:
        """Create a lightweight polyline from 2D points [[x,y], ...]."""
        flat = []
        for pt in points:
            flat.extend([pt[0], pt[1]])
        pts_variant = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, flat)
        pline = self.mspace.AddLightWeightPolyline(pts_variant)
        if closed:
            pline.Closed = True
        if layer:
            pline.Layer = layer
        if color is not None:
            pline.Color = color
        return {"handle": pline.Handle, "type": "Polyline", "vertex_count": len(points)}

    def create_circle(self, center: List[float], radius: float,
                      layer: Optional[str] = None, color: Optional[int] = None) -> dict:
        cp = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                     [center[0], center[1], center[2] if len(center) > 2 else 0.0])
        circle = self.mspace.AddCircle(cp, radius)
        if layer:
            circle.Layer = layer
        if color is not None:
            circle.Color = color
        return {"handle": circle.Handle, "type": "Circle"}

    def create_arc(self, center: List[float], radius: float,
                   start_angle: float, end_angle: float,
                   layer: Optional[str] = None, color: Optional[int] = None) -> dict:
        cp = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                     [center[0], center[1], center[2] if len(center) > 2 else 0.0])
        arc = self.mspace.AddArc(cp, radius,
                                 math.radians(start_angle), math.radians(end_angle))
        if layer:
            arc.Layer = layer
        if color is not None:
            arc.Color = color
        return {"handle": arc.Handle, "type": "Arc"}

    def create_text(self, text: str, insertion_point: List[float],
                    height: float = 2.5,
                    layer: Optional[str] = None,
                    color: Optional[int] = None,
                    rotation: float = 0.0) -> dict:
        ip = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                     [insertion_point[0], insertion_point[1],
                                      insertion_point[2] if len(insertion_point) > 2 else 0.0])
        txt = self.mspace.AddText(text, ip, height)
        if rotation:
            txt.Rotation = math.radians(rotation)
        if layer:
            txt.Layer = layer
        if color is not None:
            txt.Color = color
        return {"handle": txt.Handle, "type": "Text", "content": text}

    def create_mtext(self, text: str, insertion_point: List[float],
                     height: float = 2.5, width: float = 0.0,
                     layer: Optional[str] = None, color: Optional[int] = None) -> dict:
        ip = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                     [insertion_point[0], insertion_point[1],
                                      insertion_point[2] if len(insertion_point) > 2 else 0.0])
        mtxt = self.mspace.AddMText(ip, width, text)
        mtxt.Height = height
        if layer:
            mtxt.Layer = layer
        if color is not None:
            mtxt.Color = color
        return {"handle": mtxt.Handle, "type": "MText", "content": text}

    # -- entity modification ---------------------------------------------------

    def modify_entity(self, handle: str, **props) -> dict:
        """Modify entity properties by handle. Supported: layer, color, linetype, visible, rotation, text."""
        ent = self.doc.HandleToObject(handle)
        changed = []
        for key, val in props.items():
            if val is None:
                continue
            if key == "layer":
                ent.Layer = val
            elif key == "color":
                ent.Color = val
            elif key == "linetype":
                ent.Linetype = val
            elif key == "visible":
                ent.Visible = val
            elif key == "rotation" and hasattr(ent, "Rotation"):
                ent.Rotation = math.radians(val)
            elif key == "text" and hasattr(ent, "TextString"):
                ent.TextString = val
            elif key == "height" and hasattr(ent, "Height"):
                ent.Height = val
            else:
                continue
            changed.append(key)
        ent.Update()
        return {"handle": handle, "modified": changed}

    def delete_entity(self, handle: str) -> dict:
        ent = self.doc.HandleToObject(handle)
        ent.Delete()
        return {"handle": handle, "deleted": True}

    def copy_entity(self, handle: str, dx: float = 0, dy: float = 0, dz: float = 0) -> dict:
        ent = self.doc.HandleToObject(handle)
        new_ent = ent.Copy()
        if dx or dy or dz:
            disp = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [dx, dy, dz])
            new_ent.Move(
                win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [0, 0, 0]),
                disp
            )
        return {"handle": new_ent.Handle, "type": new_ent.EntityName}

    def move_entity(self, handle: str, dx: float = 0, dy: float = 0, dz: float = 0) -> dict:
        ent = self.doc.HandleToObject(handle)
        from_pt = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [0, 0, 0])
        to_pt = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [dx, dy, dz])
        ent.Move(from_pt, to_pt)
        return {"handle": handle, "moved": [dx, dy, dz]}


    # -- batch operations ----------------------------------------------------------

    def delete_entities(self, handles: List[str]) -> dict:
        """여러 엔티티 일괄 삭제."""
        deleted = []
        errors = []
        for h in handles:
            try:
                ent = self.doc.HandleToObject(h)
                ent.Delete()
                deleted.append(h)
            except Exception as e:
                errors.append({"handle": h, "error": str(e)})
        return {"deleted": len(deleted), "errors": errors}

    def move_entities(self, handles: List[str], dx: float = 0, dy: float = 0, dz: float = 0) -> dict:
        """여러 엔티티 일괄 이동."""
        from_pt = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [0, 0, 0])
        to_pt = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [dx, dy, dz])
        moved = []
        errors = []
        for h in handles:
            try:
                ent = self.doc.HandleToObject(h)
                ent.Move(from_pt, to_pt)
                moved.append(h)
            except Exception as e:
                errors.append({"handle": h, "error": str(e)})
        return {"moved": len(moved), "displacement": [dx, dy, dz], "errors": errors}

    def copy_entities(self, handles: List[str], dx: float = 0, dy: float = 0, dz: float = 0) -> dict:
        """여러 엔티티 일괄 복사."""
        copied = []
        errors = []
        for h in handles:
            try:
                ent = self.doc.HandleToObject(h)
                new_ent = ent.Copy()
                if dx or dy or dz:
                    disp = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [dx, dy, dz])
                    new_ent.Move(
                        win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [0, 0, 0]),
                        disp
                    )
                copied.append({"original": h, "new_handle": new_ent.Handle})
            except Exception as e:
                errors.append({"handle": h, "error": str(e)})
        return {"copied": len(copied), "new_entities": copied, "errors": errors}

    # -- undo / redo ---------------------------------------------------------------

    def undo(self, count: int = 1) -> dict:
        """Undo 실행."""
        for _ in range(count):
            self.doc.SendCommand("U\n")
        return {"undo": count}

    def redo(self) -> dict:
        """Redo 실행."""
        self.doc.SendCommand("REDO\n")
        return {"redo": True}

    # -- blocks ----------------------------------------------------------------

    def get_blocks(self) -> list:
        blocks = []
        for blk in self.doc.Blocks:
            if blk.Name.startswith("*"):
                continue  # skip internal blocks
            blocks.append({
                "name": blk.Name,
                "count": blk.Count,
                "origin": list(blk.Origin),
            })
        return blocks

    def insert_block(self, name: str, insertion_point: List[float],
                     x_scale: float = 1.0, y_scale: float = 1.0, z_scale: float = 1.0,
                     rotation: float = 0.0,
                     layer: Optional[str] = None) -> dict:
        ip = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                     [insertion_point[0], insertion_point[1],
                                      insertion_point[2] if len(insertion_point) > 2 else 0.0])
        ref = self.mspace.InsertBlock(ip, name, x_scale, y_scale, z_scale,
                                      math.radians(rotation))
        if layer:
            ref.Layer = layer
        return {"handle": ref.Handle, "type": "BlockRef", "block_name": name}

    def get_block_attributes(self, handle: str) -> list:
        ref = self.doc.HandleToObject(handle)
        attrs = []
        if ref.HasAttributes:
            for att in ref.GetAttributes():
                attrs.append({
                    "tag": att.TagString,
                    "value": att.TextString,
                })
        return attrs

    def set_block_attribute(self, handle: str, tag: str, value: str) -> dict:
        ref = self.doc.HandleToObject(handle)
        if ref.HasAttributes:
            for att in ref.GetAttributes():
                if att.TagString == tag:
                    att.TextString = value
                    att.Update()
                    return {"handle": handle, "tag": tag, "value": value}
        return {"error": f"Attribute '{tag}' not found"}

    # -- text search -----------------------------------------------------------

    def find_text(self, keyword: str) -> list:
        """TEXT/MTEXT에서 키워드 검색 → 일치 엔티티의 좌표 목록 반환 (TEMP 파일 경유)."""
        import tempfile, os, time
        fd, tmp_raw = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        os.remove(tmp_raw)  # LISP이 직접 생성하므로 미리 삭제
        tmp = tmp_raw.replace("\\", "/")
        lisp = (
            f'(setq _ss (ssget "X" (list (cons 0 "TEXT,MTEXT") (cons 1 "*{keyword}*"))))'
            f'(setq _f (open "{tmp}" "w"))'
            f'(if _ss'
            f'  (progn (setq _i 0)'
            f'    (while (< _i (sslength _ss))'
            f'      (setq _e (entget (ssname _ss _i)))'
            f'      (setq _pt (cdr (assoc 10 _e)))'
            f'      (setq _txt (cdr (assoc 1 _e)))'
            f'      (write-line (strcat (rtos (car _pt) 2 4) "," (rtos (cadr _pt) 2 4) "," _txt) _f)'
            f'      (setq _i (1+ _i))))'
            f'  (write-line "NOTFOUND" _f))'
            f'(close _f)'
        )
        self.doc.SendCommand(lisp + "\n")
        for _ in range(50):
            if os.path.exists(tmp):
                break
            time.sleep(0.1)
        if not os.path.exists(tmp):
            raise RuntimeError(f"LISP 실행 후 결과 파일이 생성되지 않았습니다: {tmp}")
        with open(tmp, "r", encoding="cp949", errors="replace") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        os.remove(tmp)
        if lines == ["NOTFOUND"]:
            return []
        results = []
        for line in lines:
            parts = line.split(",", 2)
            if len(parts) >= 2:
                results.append({
                    "x": float(parts[0]),
                    "y": float(parts[1]),
                    "text": parts[2] if len(parts) > 2 else "",
                })
        return results

    def draw_cross_section(self,
                           layer: str,
                           left_x: float, left_y: float,
                           right_x: float, right_y: float,
                           origin_x: float, origin_y: float,
                           v_scale: float = 1.0,
                           label_height: float = 0.4,
                           label_offset: float = 0.3,
                           output_layer: str = "0",
                           bbox_x1: float = 0, bbox_y1: float = 0,
                           bbox_x2: float = 0, bbox_y2: float = 0,
                           bbox_buffer: float = 20.0) -> dict:
        """지정 레이어에서 표고 텍스트를 LISP으로 추출하여 횡단면 폴리선+라벨 작도.
        ssget '_X' + 수동 bbox 필터 사용으로 대용량 도면에서도 빠름."""
        import time

        # bbox 자동 계산 (미지정 시 endpoints ± buffer)
        if bbox_x1 == 0 and bbox_y1 == 0 and bbox_x2 == 0 and bbox_y2 == 0:
            bbox_x1 = min(left_x, right_x) - bbox_buffer
            bbox_y1 = min(left_y, right_y) - bbox_buffer
            bbox_x2 = max(left_x, right_x) + bbox_buffer
            bbox_y2 = max(left_y, right_y) + bbox_buffer

        tmp = "C:/temp/_cs_extract.txt"
        if os.path.exists(tmp):
            os.remove(tmp)

        lisp = (
            f'(progn'
            f' (setq _ss (ssget "_X" (list (cons 8 "{layer}"))))'
            f' (setq _fp (open "{tmp}" "w"))'
            f' (setq _x1 {bbox_x1:.4f} _y1 {bbox_y1:.4f} _x2 {bbox_x2:.4f} _y2 {bbox_y2:.4f})'
            f' (if _ss (progn (setq _i 0 _n (sslength _ss))'
            f'   (while (< _i _n)'
            f'     (setq _e (entget (ssname _ss _i)) _et (cdr (assoc 0 _e)) _pt (cdr (assoc 10 _e)))'
            f'     (if (and _pt (>= (car _pt) _x1) (<= (car _pt) _x2)'
            f'              (>= (cadr _pt) _y1) (<= (cadr _pt) _y2))'
            f'       (cond'
            f'         ((= _et "LWPOLYLINE")'
            f'          (write-line "P" _fp)'
            f'          (foreach _a _e (if (= (car _a) 10)'
            f'            (write-line (strcat "V " (rtos (cadr _a) 2 4) " " (rtos (caddr _a) 2 4)) _fp))))'
            f'         ((or (= _et "TEXT") (= _et "MTEXT"))'
            f'          (write-line (strcat "T " (rtos (car _pt) 2 4) " " (rtos (cadr _pt) 2 4) " " (cdr (assoc 1 _e))) _fp))))'
            f'     (setq _i (1+ _i)))))'
            f' (write-line "END" _fp)'
            f' (close _fp))'
        )

        self.doc.SendCommand(lisp + "\n")

        for _ in range(300):
            if os.path.exists(tmp):
                break
            time.sleep(0.1)
        if not os.path.exists(tmp):
            raise RuntimeError("LISP 추출 시간 초과 (30초) — 레이어명/IntelliCAD 상태 확인")

        with open(tmp, "r", encoding="cp949", errors="replace") as f:
            lines = [l.strip() for l in f if l.strip()]
        os.remove(tmp)

        # 텍스트 파싱 + 표고 필터
        elev_texts = []
        for line in lines:
            if not line.startswith("T "):
                continue
            parts = line[2:].split(None, 2)
            if len(parts) < 3:
                continue
            txt = parts[2].strip()
            # X=/Y= 좌표 주석 라벨 제외
            if txt.upper().startswith("X=") or txt.upper().startswith("Y="):
                continue
            val_str = txt.replace("EL=", "").replace("EL =", "").strip()
            try:
                elev_texts.append({"x": float(parts[0]), "y": float(parts[1]), "elev": float(val_str)})
            except ValueError:
                pass

        if not elev_texts:
            raise RuntimeError("유효한 표고 텍스트 없음 — 레이어명/bbox 확인 필요")

        # 측점거리 계산 (좌안 기준 벡터 투영)
        dx = right_x - left_x
        dy = right_y - left_y
        L = math.sqrt(dx * dx + dy * dy)
        if L < 0.001:
            raise RuntimeError("좌안/우안 좌표가 같습니다")

        section_pts = sorted(
            [{"station": ((t["x"] - left_x) * dx + (t["y"] - left_y) * dy) / L,
              "elev": t["elev"]} for t in elev_texts],
            key=lambda p: p["station"]
        )

        # 레이어 생성 (없는 경우)
        out_layer = output_layer if output_layer else "0"
        if out_layer != "0":
            try:
                self.doc.Layers.Item(out_layer)
            except Exception:
                self.doc.Layers.Add(out_layer)

        # 폴리선 작도
        poly_2d = [[origin_x + p["station"], origin_y + p["elev"] * v_scale] for p in section_pts]
        self.create_polyline(poly_2d, layer=out_layer if out_layer != "0" else None)

        # 표고 라벨 작도
        for p in section_pts:
            x = origin_x + p["station"]
            y = origin_y + p["elev"] * v_scale + label_offset
            self.create_text(f"{p['elev']:.2f}", [x, y], height=label_height,
                             layer=out_layer if out_layer != "0" else None)

        xs = [pt[0] for pt in poly_2d]
        ys = [pt[1] for pt in poly_2d]

        return {
            "drawn": len(section_pts),
            "total_length": round(L, 3),
            "elev_min": round(min(p["elev"] for p in section_pts), 3),
            "elev_max": round(max(p["elev"] for p in section_pts), 3),
            "zoom_bbox": {
                "x1": round(min(xs) - label_height * 2, 3),
                "y1": round(min(ys) - label_height * 2, 3),
                "x2": round(max(xs) + label_height * 2, 3),
                "y2": round(max(ys) + label_height * 3, 3),
            },
        }

    # -- command / AutoLISP ----------------------------------------------------

    def send_command(self, command: str) -> dict:
        """Send a raw command string to IntelliCAD command line.
        AutoLISP expressions OK. Trailing blanks are stripped so IntelliCAD
        does not treat an extra Enter as a repeat of the previous command."""
        safe_command = command.rstrip()
        self.doc.SendCommand(safe_command + "\n")
        return {"sent": safe_command}

    def _cancel_command_line(self) -> bool:
        """Cancel any command prompt state left open by IntelliCAD commands."""
        try:
            self.doc.SendCommand(chr(27) + chr(27))
            return True
        except Exception:
            return False

    # -- capture / view --------------------------------------------------------

    def capture_view(self, output_path: str = "") -> dict:
        """IntelliCAD 창을 스크린 캡처하여 PNG로 저장."""
        if not output_path:
            output_path = os.path.join(tempfile.gettempdir(), "egbim_capture.png")
        output_path = os.path.normpath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class Win32Cap {{
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [StructLayout(LayoutKind.Sequential)] public struct RECT {{ public int Left, Top, Right, Bottom; }}
}}
'@
$proc = Get-Process | Where-Object {{ $_.MainWindowTitle -like '*IntelliCAD*' -or $_.MainWindowTitle -like '*.dwg*' -or $_.ProcessName -like '*icad*' -or $_.ProcessName -like '*Grimi*' }} | Select-Object -First 1
if (-not $proc) {{ Write-Error 'IntelliCAD window not found'; exit 1 }}
$hwnd = $proc.MainWindowHandle
[Win32Cap]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Milliseconds 300
$rect = New-Object Win32Cap+RECT
[Win32Cap]::GetWindowRect($hwnd, [ref]$rect) | Out-Null
$w = $rect.Right - $rect.Left; $h = $rect.Bottom - $rect.Top
$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, [System.Drawing.Size]::new($w, $h))
$g.Dispose()
$bmp.Save('{output_path.replace(chr(92), "/")}', [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Host 'OK'
'''
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"캡처 실패: {result.stderr.strip()}")
        return {"path": output_path, "captured": True}

    # -- zoom / view -----------------------------------------------------------

    def zoom_extents(self) -> dict:
        before = self._cancel_command_line()
        self.app.ZoomExtents()
        after = self._cancel_command_line()
        return {"zoom": "extents", "command_cancel_before": before, "command_cancel_after": after}

    def zoom_window(self, lower_left: List[float], upper_right: List[float]) -> dict:
        before = self._cancel_command_line()
        method = "com"
        try:
            ll = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                         [lower_left[0], lower_left[1], 0.0])
            ur = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                         [upper_right[0], upper_right[1], 0.0])
            self.app.ZoomWindow(ll, ur)
        except Exception:
            method = "command"
            self.doc.SendCommand(
                f"_.ZOOM _W {lower_left[0]},{lower_left[1]} {upper_right[0]},{upper_right[1]}\n"
            )
        finally:
            after = self._cancel_command_line()
        return {
            "zoom": "window",
            "method": method,
            "command_cancel_before": before,
            "command_cancel_after": after,
        }

    def regen(self) -> dict:
        self.doc.Regen(0)  # acActiveViewport = 0
        return {"regen": True}

    def prepare_lisp_file(
        self,
        code: str,
        encoding: str = "cp949",
        line_ending: str = "crlf",
        filename: Optional[str] = None,
    ) -> dict:
        if line_ending == "crlf":
            normalized = code.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
        elif line_ending == "lf":
            normalized = code.replace("\r\n", "\n").replace("\r", "\n")
        else:
            raise ValueError(f"line_ending must be 'crlf' or 'lf', got: {line_ending}")

        try:
            payload = normalized.encode(encoding)
        except UnicodeEncodeError as exc:
            raise ValueError(
                f"{encoding}로 인코딩할 수 없는 문자가 포함되어 있습니다: {exc}"
            ) from exc

        if filename:
            target = os.path.join(tempfile.gettempdir(), filename)
            with open(target, "wb") as fp:
                fp.write(payload)
        else:
            fd, target = tempfile.mkstemp(suffix=".lsp", prefix="egbim_", text=False)
            with os.fdopen(fd, "wb") as fp:
                fp.write(payload)

        return {
            "path": target,
            "load_expr": f'(load "{target.replace(chr(92), "/")}")',
            "encoding": encoding,
            "line_ending": line_ending,
            "bytes": len(payload),
        }


# --- Global connection --------------------------------------------------------

_icad: Optional[IcadConnection] = None


def get_icad() -> IcadConnection:
    global _icad
    if _icad is not None:
        try:
            _ = _icad.doc.Name
            return _icad
        except Exception:
            logger.warning("IntelliCAD connection lost, reconnecting...")
            _icad = None

    _icad = IcadConnection()
    if not _icad.connect():
        _icad = None
        raise RuntimeError(
            "EG-BIM (IntelliCAD)에 연결할 수 없습니다. "
            "EG-BIM이 실행 중인지 확인하세요."
        )
    return _icad


# --- MCP server ---------------------------------------------------------------

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    logger.info("EG-BIM MCP server starting")
    try:
        icad = get_icad()
        logger.info("Connected to IntelliCAD on startup: %s", icad.app.Caption)
    except Exception as exc:
        logger.warning("Could not connect on startup: %s", exc)
    yield {}
    global _icad
    if _icad:
        _icad.disconnect()
        _icad = None
    logger.info("EG-BIM MCP server shut down")


mcp = FastMCP(
    "egbim_mcp",
    instructions="EG-BIM (IntelliCAD) integration through the Model Context Protocol",
    lifespan=server_lifespan,
)


def _ok(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def _err(exc: Exception, hint: str = "") -> str:
    payload = {
        "ok": False,
        "error": {
            "type": type(exc).__name__,
            "message": str(exc),
        },
    }
    if hint:
        payload["error"]["hint"] = hint
    return json.dumps(payload, ensure_ascii=False)


# -- connection / info ---------------------------------------------------------

@mcp.tool()
def ping(ctx: Context) -> str:
    """EG-BIM 연결 확인. 'pong'과 현재 도면명 반환."""
    try:
        return _ok(get_icad().ping())
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_icad_info(ctx: Context) -> str:
    """IntelliCAD 어플리케이션 및 현재 도면 정보."""
    try:
        return _ok(get_icad().get_info())
    except Exception as e:
        return _err(e)


@mcp.tool()
def health_check(ctx: Context) -> str:
    """EG-BIM 상태 진단: ProgID, 활성 도면, 응답시간(ms), Documents 수.

    ping이 느리거나 실패할 때 원인 진단용. 연결 실패해도 부분 정보 반환.
    """
    global _icad
    try:
        icad = get_icad()
        return _ok(icad.health_check())
    except Exception as e:
        # 연결 자체가 실패해도 진단 정보를 최대한 반환
        info = {
            "progid": ICAD_PROGID,
            "connected": False,
            "connect_error": f"{type(e).__name__}: {e}",
            "hint": "EG-BIM(IntelliCAD)이 실행 중인지, ProgID가 맞는지 확인하세요.",
        }
        return _ok(info)


@mcp.tool()
def prepare_lisp_file(
    ctx: Context,
    code: str,
    encoding: str = "cp949",
    line_ending: str = "crlf",
    filename: str = "",
) -> str:
    """AutoLISP 코드를 임시 파일로 저장 (실행하지 않음).

    EG-BIM/IntelliCAD가 안전하게 load 할 수 있도록 인코딩/개행을 정규화한
    LISP 파일을 만들어 경로를 반환한다. 실행은 호출자가 send_command로
    `(load "...")` 형태로 직접 수행한다 (의도 왜곡 방지).

    Args:
        code: AutoLISP 소스 코드.
        encoding: 파일 인코딩 (기본 'cp949', 'utf-8' 등 가능).
        line_ending: 'crlf' 또는 'lf' (기본 'crlf').
        filename: 지정 시 해당 이름으로 TEMP에 저장. 빈 문자열이면 자동 생성.

    Returns:
        path, load_expr, encoding, line_ending, bytes 를 담은 JSON.
    """
    try:
        result = get_icad().prepare_lisp_file(
            code=code,
            encoding=encoding,
            line_ending=line_ending,
            filename=filename if filename else None,
        )
        return _ok(result)
    except Exception as e:
        return _err(e, hint="encoding/line_ending 값을 확인하거나 코드의 비-CP949 문자를 점검하세요.")


# -- drawing management --------------------------------------------------------

@mcp.tool()
def list_documents(ctx: Context) -> str:
    """현재 IntelliCAD 인스턴스에 열려있는 도면 목록 반환."""
    try:
        return _ok(get_icad().list_documents())
    except Exception as e:
        return _err(e)


@mcp.tool()
def activate_document(ctx: Context, name: str) -> str:
    """도면명(일부 포함)으로 활성 도면 전환. 예: '보성강 평면도'"""
    try:
        return _ok(get_icad().activate_document(name))
    except Exception as e:
        return _err(e)


@mcp.tool()
def open_drawing(ctx: Context, path: str, read_only: bool = False) -> str:
    """도면 파일(.dwg) 열기."""
    try:
        return _ok(get_icad().open_drawing(path, read_only))
    except Exception as e:
        return _err(e)


@mcp.tool()
def save_drawing(ctx: Context, path: str = "") -> str:
    """현재 도면 저장. path 지정 시 다른이름으로 저장."""
    try:
        return _ok(get_icad().save_drawing(path if path else None))
    except Exception as e:
        return _err(e)


@mcp.tool()
def close_drawing(ctx: Context, save: bool = True) -> str:
    """현재 도면 닫기."""
    try:
        return _ok(get_icad().close_drawing(save))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_drawing_info(ctx: Context) -> str:
    """현재 도면 정보 (이름, 경로, 저장 여부, 한계)."""
    try:
        return _ok(get_icad().get_drawing_info())
    except Exception as e:
        return _err(e)


# -- layers --------------------------------------------------------------------

@mcp.tool()
def get_layers(ctx: Context) -> str:
    """도면의 모든 레이어 목록 및 속성."""
    try:
        return _ok(get_icad().get_layers())
    except Exception as e:
        return _err(e)


@mcp.tool()
def set_layer(ctx: Context, name: str, color: int = -1,
              on: bool = True, locked: bool = False,
              linetype: str = "") -> str:
    """레이어 생성 또는 속성 설정. 없으면 자동 생성."""
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
        return _err(e)


@mcp.tool()
def set_active_layer(ctx: Context, name: str) -> str:
    """활성 레이어 변경."""
    try:
        return _ok(get_icad().set_active_layer(name))
    except Exception as e:
        return _err(e)


# -- entity query --------------------------------------------------------------

@mcp.tool()
def get_entities(ctx: Context, layer: str = "", entity_type: str = "",
                 limit: int = 100,
                 bbox_x1: float = 0, bbox_y1: float = 0,
                 bbox_x2: float = 0, bbox_y2: float = 0) -> str:
    """ModelSpace 엔티티 목록. layer, entity_type으로 필터 가능.
    bbox_x1/y1/x2/y2: 영역 필터 (좌하-우상). 모두 0이면 영역 필터 사용 안 함."""
    try:
        bbox_min = None
        bbox_max = None
        if bbox_x1 != 0 or bbox_y1 != 0 or bbox_x2 != 0 or bbox_y2 != 0:
            bbox_min = [min(bbox_x1, bbox_x2), min(bbox_y1, bbox_y2)]
            bbox_max = [max(bbox_x1, bbox_x2), max(bbox_y1, bbox_y2)]
        return _ok(get_icad().get_entities(
            layer=layer or None,
            entity_type=entity_type or None,
            limit=limit,
            bbox_min=bbox_min,
            bbox_max=bbox_max,
        ))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_entity(ctx: Context, handle: str) -> str:
    """핸들로 엔티티 상세 정보 조회."""
    try:
        return _ok(get_icad().get_entity_by_handle(handle))
    except Exception as e:
        return _err(e)



@mcp.tool()
def count_entities(ctx: Context, layer: str = "", entity_type: str = "") -> str:
    """엔티티 개수 조회. 전체를 반환하지 않고 개수만 카운트. 대규모 작업 전 피쳐 수 확인용."""
    try:
        return _ok(get_icad().count_entities(
            layer=layer or None,
            entity_type=entity_type or None,
        ))
    except Exception as e:
        return _err(e)


# -- entity creation -----------------------------------------------------------

@mcp.tool()
def create_line(ctx: Context, start_x: float, start_y: float,
                end_x: float, end_y: float,
                layer: str = "", color: int = -1) -> str:
    """선(Line) 생성."""
    try:
        return _ok(get_icad().create_line(
            [start_x, start_y], [end_x, end_y],
            layer=layer or None, color=color if color >= 0 else None,
        ))
    except Exception as e:
        return _err(e)


@mcp.tool()
def create_polyline(ctx: Context, points: str, closed: bool = False,
                    layer: str = "", color: int = -1) -> str:
    """폴리선(LWPolyline) 생성. points는 JSON 배열: [[x1,y1],[x2,y2],...]"""
    try:
        pts = json.loads(points)
        return _ok(get_icad().create_polyline(
            pts, closed=closed,
            layer=layer or None, color=color if color >= 0 else None,
        ))
    except Exception as e:
        return _err(e)


@mcp.tool()
def create_circle(ctx: Context, center_x: float, center_y: float,
                  radius: float, layer: str = "", color: int = -1) -> str:
    """원(Circle) 생성."""
    try:
        return _ok(get_icad().create_circle(
            [center_x, center_y], radius,
            layer=layer or None, color=color if color >= 0 else None,
        ))
    except Exception as e:
        return _err(e)


@mcp.tool()
def create_arc(ctx: Context, center_x: float, center_y: float,
               radius: float, start_angle: float, end_angle: float,
               layer: str = "", color: int = -1) -> str:
    """호(Arc) 생성. 각도는 도(degree) 단위."""
    try:
        return _ok(get_icad().create_arc(
            [center_x, center_y], radius, start_angle, end_angle,
            layer=layer or None, color=color if color >= 0 else None,
        ))
    except Exception as e:
        return _err(e)


@mcp.tool()
def create_text(ctx: Context, text: str, x: float, y: float,
                height: float = 2.5, rotation: float = 0.0,
                layer: str = "", color: int = -1) -> str:
    """단일행 텍스트(Text) 생성."""
    try:
        return _ok(get_icad().create_text(
            text, [x, y], height=height, rotation=rotation,
            layer=layer or None, color=color if color >= 0 else None,
        ))
    except Exception as e:
        return _err(e)


@mcp.tool()
def create_mtext(ctx: Context, text: str, x: float, y: float,
                 height: float = 2.5, width: float = 0.0,
                 layer: str = "", color: int = -1) -> str:
    """다중행 텍스트(MText) 생성."""
    try:
        return _ok(get_icad().create_mtext(
            text, [x, y], height=height, width=width,
            layer=layer or None, color=color if color >= 0 else None,
        ))
    except Exception as e:
        return _err(e)


# -- entity modification -------------------------------------------------------

@mcp.tool()
def modify_entity(ctx: Context, handle: str,
                  layer: str = "", color: int = -1,
                  linetype: str = "", visible: bool = True,
                  rotation: float = -1.0, text: str = "",
                  height: float = -1.0) -> str:
    """엔티티 속성 수정 (핸들 기준). 변경할 속성만 지정."""
    try:
        props = {}
        if layer:
            props["layer"] = layer
        if color >= 0:
            props["color"] = color
        if linetype:
            props["linetype"] = linetype
        props["visible"] = visible
        if rotation >= 0:
            props["rotation"] = rotation
        if text:
            props["text"] = text
        if height >= 0:
            props["height"] = height
        return _ok(get_icad().modify_entity(handle, **props))
    except Exception as e:
        return _err(e)


@mcp.tool()
def delete_entity(ctx: Context, handle: str) -> str:
    """엔티티 삭제 (핸들 기준)."""
    try:
        return _ok(get_icad().delete_entity(handle))
    except Exception as e:
        return _err(e)


@mcp.tool()
def copy_entity(ctx: Context, handle: str,
                dx: float = 0, dy: float = 0, dz: float = 0) -> str:
    """엔티티 복사. dx/dy/dz만큼 이동된 복사본 생성."""
    try:
        return _ok(get_icad().copy_entity(handle, dx, dy, dz))
    except Exception as e:
        return _err(e)


@mcp.tool()
def move_entity(ctx: Context, handle: str,
                dx: float = 0, dy: float = 0, dz: float = 0) -> str:
    """엔티티 이동."""
    try:
        return _ok(get_icad().move_entity(handle, dx, dy, dz))
    except Exception as e:
        return _err(e)




# -- batch operations --------------------------------------------------------------

@mcp.tool()
def delete_entities(ctx: Context, handles: str) -> str:
    """여러 엔티티 일괄 삭제. handles는 JSON 문자열 배열: ["handle1","handle2",...]"""
    try:
        h_list = json.loads(handles)
        return _ok(get_icad().delete_entities(h_list))
    except Exception as e:
        return _err(e)


@mcp.tool()
def move_entities(ctx: Context, handles: str,
                  dx: float = 0, dy: float = 0, dz: float = 0) -> str:
    """여러 엔티티 일괄 이동. handles는 JSON 문자열 배열."""
    try:
        h_list = json.loads(handles)
        return _ok(get_icad().move_entities(h_list, dx, dy, dz))
    except Exception as e:
        return _err(e)


@mcp.tool()
def copy_entities(ctx: Context, handles: str,
                  dx: float = 0, dy: float = 0, dz: float = 0) -> str:
    """여러 엔티티 일괄 복사. handles는 JSON 문자열 배열. 새 핸들 목록 반환."""
    try:
        h_list = json.loads(handles)
        return _ok(get_icad().copy_entities(h_list, dx, dy, dz))
    except Exception as e:
        return _err(e)


# -- undo / redo -------------------------------------------------------------------

@mcp.tool()
def undo(ctx: Context, count: int = 1) -> str:
    """Undo 실행. count만큼 되돌리기."""
    try:
        return _ok(get_icad().undo(count))
    except Exception as e:
        return _err(e)


@mcp.tool()
def redo(ctx: Context) -> str:
    """Redo 실행."""
    try:
        return _ok(get_icad().redo())
    except Exception as e:
        return _err(e)


# -- blocks --------------------------------------------------------------------

@mcp.tool()
def get_blocks(ctx: Context) -> str:
    """도면의 블록 정의 목록 (내부 블록 제외)."""
    try:
        return _ok(get_icad().get_blocks())
    except Exception as e:
        return _err(e)


@mcp.tool()
def insert_block(ctx: Context, name: str, x: float, y: float,
                 x_scale: float = 1.0, y_scale: float = 1.0, z_scale: float = 1.0,
                 rotation: float = 0.0, layer: str = "") -> str:
    """블록 참조 삽입. rotation은 도(degree) 단위."""
    try:
        return _ok(get_icad().insert_block(
            name, [x, y],
            x_scale=x_scale, y_scale=y_scale, z_scale=z_scale,
            rotation=rotation, layer=layer or None,
        ))
    except Exception as e:
        return _err(e)


@mcp.tool()
def get_block_attributes(ctx: Context, handle: str) -> str:
    """블록 참조의 속성(Attribute) 목록."""
    try:
        return _ok(get_icad().get_block_attributes(handle))
    except Exception as e:
        return _err(e)


@mcp.tool()
def set_block_attribute(ctx: Context, handle: str, tag: str, value: str) -> str:
    """블록 참조의 속성값 변경."""
    try:
        return _ok(get_icad().set_block_attribute(handle, tag, value))
    except Exception as e:
        return _err(e)


# -- text search ---------------------------------------------------------------

@mcp.tool()
def find_text(ctx: Context, keyword: str, zoom: bool = True, margin: float = 200.0) -> str:
    """도면에서 텍스트/MTEXT 키워드 검색. zoom=True면 첫 번째 결과로 자동 줌.
    margin: 줌 여백 (도면 단위, 기본 200)"""
    try:
        results = get_icad().find_text(keyword)
        if not results:
            return _ok({"found": 0, "results": []})
        if zoom and results:
            first = results[0]
            x, y = first["x"], first["y"]
            get_icad().zoom_window([x - margin, y - margin], [x + margin, y + margin])
        return _ok({"found": len(results), "results": results})
    except Exception as e:
        return _err(e)


# -- cross-section -------------------------------------------------------------

@mcp.tool()
def draw_cross_section(ctx: Context,
                       layer: str,
                       left_x: float, left_y: float,
                       right_x: float, right_y: float,
                       origin_x: float, origin_y: float,
                       v_scale: float = 1.0,
                       label_height: float = 0.4,
                       label_offset: float = 0.3,
                       output_layer: str = "0",
                       bbox_x1: float = 0, bbox_y1: float = 0,
                       bbox_x2: float = 0, bbox_y2: float = 0,
                       bbox_buffer: float = 20.0) -> str:
    """횡단면 자동 작도. 지정 레이어에서 폴리선+표고 텍스트를 LISP으로 추출 후 횡단면 폴리선+라벨 생성.
    left_x/y: 좌안 CAD 좌표. right_x/y: 우안 CAD 좌표 (CAD좌표 = 토목좌표 X/Y 반전).
    origin_x/y: 횡단면 기준점 (예: 측선 우측 오프셋). v_scale: 수직 과장 (1.0=무과장, 10.0=10배).
    bbox_x1~y2: 검색 영역 (모두 0이면 endpoints±bbox_buffer 자동 계산).
    반환값의 zoom_bbox를 zoom_window 툴에 전달하면 자동 줌인 가능."""
    try:
        result = get_icad().draw_cross_section(
            layer=layer,
            left_x=left_x, left_y=left_y,
            right_x=right_x, right_y=right_y,
            origin_x=origin_x, origin_y=origin_y,
            v_scale=v_scale,
            label_height=label_height,
            label_offset=label_offset,
            output_layer=output_layer,
            bbox_x1=bbox_x1, bbox_y1=bbox_y1,
            bbox_x2=bbox_x2, bbox_y2=bbox_y2,
            bbox_buffer=bbox_buffer,
        )
        return _ok(result)
    except Exception as e:
        return _err(e)


# -- command / AutoLISP --------------------------------------------------------

@mcp.tool()
def send_command(ctx: Context, command: str) -> str:
    """IntelliCAD 명령줄에 문자열 전송. AutoLISP 표현식도 가능.
    예: '(+ 1 2)', 'LINE 0,0 100,100 ', 'ZOOM E'"""
    try:
        return _ok(get_icad().send_command(command))
    except Exception as e:
        return _err(e)


# -- capture / view ------------------------------------------------------------

@mcp.tool()
def capture_view(ctx: Context, output_path: str = "") -> str:
    """현재 IntelliCAD 뷰를 PNG 이미지로 캡처. Claude가 도면 형태를 시각적으로 인식할 수 있도록 함.
    output_path 미지정 시 TEMP 폴더에 저장."""
    try:
        return _ok(get_icad().capture_view(output_path))
    except Exception as e:
        return _err(e)


# -- view / zoom ---------------------------------------------------------------

@mcp.tool()
def zoom_extents(ctx: Context) -> str:
    """전체 범위로 줌."""
    try:
        return _ok(get_icad().zoom_extents())
    except Exception as e:
        return _err(e)


@mcp.tool()
def zoom_window(ctx: Context, x1: float, y1: float, x2: float, y2: float) -> str:
    """지정 영역으로 줌."""
    try:
        return _ok(get_icad().zoom_window([x1, y1], [x2, y2]))
    except Exception as e:
        return _err(e)


@mcp.tool()
def regen(ctx: Context) -> str:
    """도면 재생성 (Regen)."""
    try:
        return _ok(get_icad().regen())
    except Exception as e:
        return _err(e)


# -- entry point ---------------------------------------------------------------

def main():
    mcp.run()


if __name__ == "__main__":
    main()
