
# -- offset --------------------------------------------------------------------

@mcp.tool()
def offset_entity(ctx: Context, handle: str, distance: float,
                  side_x: float, side_y: float) -> str:
    """엔티티 간격띄우기(Offset). handle: 대상 엔티티 핸들.
    distance: 간격 거리. side_x/side_y: 오프셋 방향을 나타내는 점.
    Line, Polyline, Arc, Circle 지원."""
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
    """해치(Hatch) 생성. boundary_handles: 경계 엔티티 핸들 JSON 배열 (예: '["A1","A2"]').
    pattern_name: SOLID, ANSI31, ANSI37, EARTH, GRAVEL 등.
    pattern_type: 0=사용자정의, 1=사전정의, 2=사용자.
    scale: 패턴 축척. angle: 패턴 각도(도)."""
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
    """치수선 생성. dim_type: aligned | rotated | radial.
    aligned/rotated: (x1,y1)-(x2,y2) 치수보조선 원점, (text_x,text_y) 치수문자 위치.
    rotated: rotation_angle=치수선 각도(도).
    radial: (x1,y1)=중심, (x2,y2)=원주점, rotation_angle=지시선 길이.
    text_override: 치수 문자 강제 지정."""
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
                "지원하지 않는 치수 유형: " + dim_type
                + ". aligned, rotated, radial 중 선택하세요"
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
    """각도 치수선 생성. vertex: 꼭짓점, p1/p2: 두 선의 끝점, text: 치수문자 위치."""
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
    """두 점 간 거리 측정. 2D/3D 거리, 각도, 델타값 반환."""
    try:
        return _ok(get_icad().measure_distance([x1, y1, z1], [x2, y2, z2]))
    except Exception as e:
        return _err(e)


@mcp.tool()
def measure_entity(ctx: Context, handle: str) -> str:
    """엔티티 측정. Polyline(면적/둘레), Circle(면적/둘레),
    Line(길이), Arc(호 길이) 등. Shoelace 공식 폴백 포함."""
    try:
        return _ok(get_icad().measure_entity(handle))
    except Exception as e:
        return _err(e)


