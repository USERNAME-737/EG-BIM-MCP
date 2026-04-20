# EG-BIM MCP

EG-BIM(IntelliCAD)을 **Model Context Protocol(MCP)** 로 연결하는 서버입니다.  
Claude 등 AI 어시스턴트가 실행 중인 IntelliCAD 인스턴스를 직접 제어할 수 있습니다.

## 요구사항

| 항목 | 버전 |
|------|------|
| OS | Windows 10/11 |
| Python | 3.12 이상 |
| [uv](https://docs.astral.sh/uv/) | 최신 버전 |
| EG-BIM (IntelliCAD) | 9.x (x64) |

> IntelliCAD가 실행 중이어야 MCP 서버가 COM 자동화로 연결됩니다.

---

## 설치

### 1. 저장소 클론

```bash
git clone https://github.com/USERNAME-737/EG-BIM-MCP.git
cd EG-BIM-MCP
```

### 2. Claude Code (CLI)에 MCP 서버 등록

```bash
claude mcp add egbim \
  -- uv --directory "경로/EG-BIM-MCP" run src/egbim_mcp/egbim_mcp_server.py
```

또는 `~/.claude/settings.json`에 직접 추가:

```json
{
  "mcpServers": {
    "egbim": {
      "type": "stdio",
      "command": "C:\\Users\\<사용자명>\\.local\\bin\\uv.exe",
      "args": [
        "--directory", "C:\\경로\\EG-BIM-MCP",
        "run", "src/egbim_mcp/egbim_mcp_server.py"
      ],
      "env": {}
    }
  }
}
```

### 3. Claude Desktop에 등록

`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "egbim": {
      "command": "uv",
      "args": [
        "--directory", "C:\\경로\\EG-BIM-MCP",
        "run", "src/egbim_mcp/egbim_mcp_server.py"
      ]
    }
  }
}
```

### 4. 연결 확인

Claude에게 다음을 요청합니다:

```
EG-BIM에 연결 확인해줘
```

`{"status": "pong", "drawing": "도면명.dwg"}` 응답이 오면 정상입니다.

---

## 도구 목록

### 연결 / 정보

| 도구 | 설명 |
|------|------|
| `ping` | 연결 확인, 현재 도면명 반환 |
| `get_icad_info` | IntelliCAD 버전·도면 정보 |
| `get_drawing_info` | 도면 이름, 경로, 저장 여부, 한계 |

### 도면 관리

| 도구 | 설명 |
|------|------|
| `list_documents` | 열려있는 도면 목록 |
| `activate_document` | 도면명으로 활성 도면 전환 |
| `open_drawing` | DWG 파일 열기 |
| `save_drawing` | 저장 / 다른 이름으로 저장 |
| `close_drawing` | 도면 닫기 |

### 레이어

| 도구 | 설명 |
|------|------|
| `get_layers` | 전체 레이어 목록 및 속성 |
| `set_layer` | 레이어 생성 또는 속성 변경 |
| `set_active_layer` | 현재 레이어 변경 |

### 엔티티 조회

| 도구 | 설명 |
|------|------|
| `count_entities` | 엔티티 개수 확인 (대규모 작업 전 권장) |
| `get_entities` | 엔티티 목록 (레이어·타입·영역 필터 지원) |
| `get_entity` | 핸들로 엔티티 상세 정보 조회 |
| `find_text` | TEXT / MTEXT 키워드 검색, 자동 줌 |

### 엔티티 생성

| 도구 | 설명 |
|------|------|
| `create_line` | 선(Line) |
| `create_polyline` | 폴리선(LWPolyline), JSON 좌표 배열 |
| `create_circle` | 원(Circle) |
| `create_arc` | 호(Arc), 각도는 도(°) 단위 |
| `create_text` | 단일행 텍스트 |
| `create_mtext` | 다중행 텍스트(MText) |

### 엔티티 수정

| 도구 | 설명 |
|------|------|
| `modify_entity` | 핸들 기준 속성 변경 (레이어·색상·선종류·회전·텍스트) |
| `move_entity` | 단일 엔티티 이동 (Δx, Δy, Δz) |
| `copy_entity` | 단일 엔티티 복사 |
| `delete_entity` | 단일 엔티티 삭제 |

### 일괄(Batch) 처리

| 도구 | 설명 |
|------|------|
| `move_entities` | 여러 엔티티 동시 이동 |
| `copy_entities` | 여러 엔티티 동시 복사 |
| `delete_entities` | 여러 엔티티 동시 삭제 |

### 블록

| 도구 | 설명 |
|------|------|
| `get_blocks` | 도면 내 블록 정의 목록 |
| `insert_block` | 블록 삽입 (축척·회전 지정 가능) |
| `get_block_attributes` | 블록 참조의 속성(Attribute) 조회 |
| `set_block_attribute` | 블록 속성값 변경 |

### 뷰 / 캡처

| 도구 | 설명 |
|------|------|
| `zoom_extents` | 전체 범위로 줌 |
| `zoom_window` | 지정 영역으로 줌 |
| `regen` | 도면 재생성(Regen) |
| `capture_view` | 현재 뷰를 PNG로 캡처 → Claude가 도면을 시각적으로 인식 |

### 명령 / AutoLISP

| 도구 | 설명 |
|------|------|
| `send_command` | IntelliCAD 명령줄에 문자열 전송 (AutoLISP 포함) |
| `undo` | 되돌리기 (n회) |
| `redo` | 다시 실행 |

---

## 사용 예시

```
# 연결 확인
"EG-BIM 연결 상태 확인해줘"

# 레이어 분석
"현재 도면의 모든 레이어 목록 보여줘"

# 엔티티 조회
"A-WALL 레이어의 폴리선 개수 알려줘"

# 도형 생성
"좌표 (0,0)에서 (100,0)으로 선 하나 그려줘, 레이어는 TEMP"

# 텍스트 검색
"도면에서 '교량' 텍스트 찾아서 줌해줘"

# 도면 캡처
"현재 화면 캡처해서 어떤 도면인지 설명해줘"

# AutoLISP 실행
"LISP으로 모든 레이어 이름 출력해줘"
```

---

## 주의사항

- **Windows 전용** — COM 자동화(`pywin32`)를 사용합니다.
- EG-BIM(IntelliCAD)이 **실행 중**이어야 서버가 연결됩니다.
- `vlax-*` 함수는 지원하지 않습니다 (IntelliCAD 9.x 기준 기본 AutoLISP만 사용).
- 대규모 작업 전 `count_entities`로 엔티티 수를 확인하세요.

---

## 라이선스

MIT
