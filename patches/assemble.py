#!/usr/bin/env python3
"""Assemble patches into egbim_mcp_server.py"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(BASE), "src", "egbim_mcp", "egbim_mcp_server.py")

with open(SRC, "r", encoding="utf-8") as f:
    code = f.read()

# Read patch files
with open(os.path.join(BASE, "methods.py"), "r", encoding="utf-8") as f:
    methods_code = f.read()

with open(os.path.join(BASE, "tools.py"), "r", encoding="utf-8") as f:
    tools_code = f.read()

# ── PATCH 1: Insert IcadConnection methods before "# -- entity creation" ──
marker1 = "    # -- entity creation -------------------------------------------------------"
if marker1 not in code:
    print("ERROR: entity creation marker not found")
    exit(1)
code = code.replace(marker1, methods_code + "\n" + marker1)
print("OK: IcadConnection methods inserted")

# ── PATCH 2: Update get_layers to include lineweight/plottable ──
old_get_layers = """    def get_layers(self) -> list:
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
        return layers"""

new_get_layers = """    def get_layers(self) -> list:
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
        return layers"""

if old_get_layers in code:
    code = code.replace(old_get_layers, new_get_layers)
    print("OK: get_layers updated")
else:
    print("WARN: get_layers pattern not matched (may already be patched)")

# ── PATCH 3: Update set_layer method ──
old_set_layer_method = """    def set_layer(self, name: str, color: Optional[int] = None,
                  on: Optional[bool] = None, locked: Optional[bool] = None,
                  linetype: Optional[str] = None) -> dict:
        \"\"\"Create layer if it doesn't exist, then set properties.\"\"\"
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

        return {"layer": name, "action": "set"}"""

new_set_layer_method = """    def set_layer(self, name: str, color: Optional[int] = None,
                  on: Optional[bool] = None, locked: Optional[bool] = None,
                  linetype: Optional[str] = None,
                  lineweight: Optional[int] = None,
                  frozen: Optional[bool] = None,
                  plottable: Optional[bool] = None) -> dict:
        \"\"\"Create layer if it doesn't exist, then set properties.
        lineweight: 1/100 mm (-3=Default, 0,5,9,13,...,211).
        frozen: True=freeze (cannot freeze active layer).\"\"\"
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
                raise ValueError("\\ud604\\uc7ac \\ud65c\\uc131 \\ub808\\uc774\\uc5b4\\ub294 \\ub3d9\\uacb0\\ud560 \\uc218 \\uc5c6\\uc2b5\\ub2c8\\ub2e4")
            layer.Freeze = frozen
            changed.append("frozen")
        if plottable is not None:
            try:
                layer.Plottable = plottable
                changed.append("plottable")
            except Exception as e:
                logger.warning("Plottable set failed: %s", e)

        return {"layer": name, "action": "set", "changed": changed}"""

if old_set_layer_method in code:
    code = code.replace(old_set_layer_method, new_set_layer_method)
    print("OK: set_layer method updated")
else:
    print("WARN: set_layer method pattern not matched")

# ── PATCH 4: Update set_layer MCP tool wrapper ──
# We need to find and replace the tool wrapper
old_tool = '''@mcp.tool()
def set_layer(ctx: Context, name: str, color: int = -1,
              on: bool = True, locked: bool = False,
              linetype: str = "") -> str:'''

new_tool = '''@mcp.tool()
def set_layer(ctx: Context, name: str, color: int = -1,
              on: bool = True, locked: bool = False,
              linetype: str = "", lineweight: int = -99,
              frozen: bool = False, plottable: bool = True) -> str:'''

if old_tool in code:
    code = code.replace(old_tool, new_tool)
    print("OK: set_layer tool signature updated")
else:
    print("WARN: set_layer tool signature not matched")

# Update the tool docstring and body
old_tool_body = '''    \"\"\"\ub808\uc774\uc5b4 \uc0dd\uc131 \ub610\ub294 \uc18d\uc131 \uc124\uc815. \uc5c6\uc73c\uba74 \uc790\ub3d9 \uc0dd\uc131.\"\"\"
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

new_tool_body = '''    \"\"\"\ub808\uc774\uc5b4 \uc0dd\uc131 \ub610\ub294 \uc18d\uc131 \uc124\uc815. \uc5c6\uc73c\uba74 \uc790\ub3d9 \uc0dd\uc131.
    lineweight: \uc120 \uac00\uc911\uce58 (1/100mm). frozen: \ub3d9\uacb0(\ud65c\uc131\ub808\uc774\uc5b4 \ubd88\uac00). plottable: \ucd9c\ub825\uc5ec\ubd80.\"\"\"
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

if old_tool_body in code:
    code = code.replace(old_tool_body, new_tool_body)
    print("OK: set_layer tool body updated")
else:
    print("WARN: set_layer tool body not matched")

# ── PATCH 5: Insert new MCP tools before entry point ──
marker2 = "# -- entry point ---------------------------------------------------------------"
if marker2 not in code:
    print("ERROR: entry point marker not found")
    exit(1)
code = code.replace(marker2, tools_code + "\n" + marker2)
print("OK: New MCP tools inserted")

# ── WRITE ──
with open(SRC, "w", encoding="utf-8") as f:
    f.write(code)

# Count lines
line_count = code.count("\n") + 1
print(f"\nDone! Total lines: {line_count}")
