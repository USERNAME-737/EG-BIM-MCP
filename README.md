# EG-BIM MCP

EG-BIM MCP는 Windows에서 실행 중인 EG-BIM, IntelliCAD 기반 CAD 엔진을 Model Context Protocol(MCP)로 연결하는 서버입니다.
AI assistant가 도면을 조회하고, 레이어와 객체를 분석하고, 간단한 도형 작성 및 수정 명령을 실행할 수 있도록 돕습니다.

> 현재 서버는 Windows COM 자동화를 사용합니다. EG-BIM 또는 IntelliCAD가 실행 중이어야 안정적으로 연결됩니다.

## 주요 활용 Skill

이 저장소의 MCP 서버는 아래와 같은 CAD 작업 흐름에 맞춰 사용할 수 있습니다.

| Skill | 설명 | 관련 MCP tools |
| --- | --- | --- |
| CAD 연결 상태 확인 | EG-BIM 실행 여부, 활성 도면, 버전 정보를 확인합니다. | `ping`, `get_icad_info`, `get_drawing_info` |
| 도면 관리 | 열려 있는 도면을 확인하고, 도면을 열거나 저장하거나 활성 도면을 전환합니다. | `list_documents`, `open_drawing`, `save_drawing`, `close_drawing`, `activate_document` |
| 레이어 조사 | 도면의 레이어 목록과 속성을 확인하고, 현재 레이어를 바꿉니다. | `get_layers`, `set_layer`, `set_active_layer` |
| 객체 수량 파악 | 특정 레이어나 객체 유형의 개수를 먼저 확인해 큰 도면 작업의 범위를 줄입니다. | `count_entities` |
| 객체 조회 | LINE, LWPOLYLINE, TEXT, INSERT 등 객체 정보를 레이어, 유형, 영역 조건으로 조회합니다. | `get_entities`, `get_entity` |
| 문자 검색 | 도면 안의 TEXT/MTEXT에서 키워드를 찾고 필요하면 해당 위치로 화면을 이동합니다. | `find_text` |
| 도형 작성 | 선, 폴리라인, 원, 호, 단일행/다중행 문자를 생성합니다. | `create_line`, `create_polyline`, `create_circle`, `create_arc`, `create_text`, `create_mtext` |
| 객체 수정 | 객체의 레이어, 색상, 선종류 등 속성을 바꾸거나 이동/복사/삭제합니다. | `modify_entity`, `move_entity`, `copy_entity`, `delete_entity` |
| 일괄 편집 | 여러 객체를 한 번에 이동, 복사, 삭제합니다. | `move_entities`, `copy_entities`, `delete_entities` |
| 블록 작업 | 블록 정의를 조회하고, 블록을 삽입하거나 속성값을 읽고 수정합니다. | `get_blocks`, `insert_block`, `get_block_attributes`, `set_block_attribute` |
| 화면 제어와 캡처 | 전체 보기, 영역 확대, 재생성, 현재 CAD 화면 캡처를 수행합니다. | `zoom_extents`, `zoom_window`, `regen`, `capture_view` |
| AutoLISP/명령 실행 | IntelliCAD 명령줄에 직접 명령 또는 AutoLISP 표현식을 전달합니다. | `send_command`, `undo`, `redo` |
| 횡단면 보조 작성 | 도면 안의 횡단 기준선과 표고 문자 정보를 이용해 횡단면 작성 흐름을 보조합니다. | `draw_cross_section` |

## 요구 사항

| 항목 | 요구 사항 |
| --- | --- |
| OS | Windows 10/11 |
| Python | 3.12 이상 |
| Package manager | [uv](https://docs.astral.sh/uv/) 권장 |
| CAD | EG-BIM 또는 IntelliCAD 기반 CAD 실행 환경 |

Python 의존성은 `pyproject.toml`에 정의되어 있습니다.

- `mcp[cli]`
- `pywin32`

## 설치

### 1. 저장소 복제

```bash
git clone https://github.com/USERNAME-737/EG-BIM-MCP.git
cd EG-BIM-MCP
```

### 2. 의존성 준비

```bash
uv sync
```

### 3. MCP 서버 실행 확인

```bash
uv run src/egbim_mcp/egbim_mcp_server.py
```

또는 `pyproject.toml`의 script entrypoint를 사용할 수 있습니다.

```bash
uv run egbim-mcp
```

## Claude Code 등록 예시

```bash
claude mcp add egbim -- uv --directory "C:\path\to\EG-BIM-MCP" run src/egbim_mcp/egbim_mcp_server.py
```

직접 설정 파일에 등록하는 경우 예시는 다음과 같습니다.

```json
{
  "mcpServers": {
    "egbim": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\EG-BIM-MCP",
        "run",
        "src/egbim_mcp/egbim_mcp_server.py"
      ],
      "env": {}
    }
  }
}
```

## Claude Desktop 등록 예시

`%APPDATA%\Claude\claude_desktop_config.json`에 다음 항목을 추가합니다.

```json
{
  "mcpServers": {
    "egbim": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\EG-BIM-MCP",
        "run",
        "src/egbim_mcp/egbim_mcp_server.py"
      ]
    }
  }
}
```

## 연결 확인

CAD를 실행하고 도면을 연 뒤, assistant에게 다음처럼 요청합니다.

```text
EG-BIM 연결 상태 확인해줘.
```

정상 연결 시 `ping` tool은 대략 다음 형태의 응답을 반환합니다.

```json
{
  "status": "pong",
  "drawing": "현재도면.dwg"
}
```

## 권장 작업 흐름

큰 도면에서는 바로 전체 객체를 조회하기보다 범위를 좁혀서 접근하는 편이 안전합니다.

1. `ping`으로 CAD 연결과 활성 도면을 확인합니다.
2. `get_layers`로 레이어 이름과 상태를 확인합니다.
3. `count_entities`로 대상 레이어/객체 수를 먼저 파악합니다.
4. 필요한 경우 `zoom_window` 또는 CAD 화면 조작으로 범위를 좁힙니다.
5. `get_entities` 또는 `send_command` 기반 AutoLISP로 필요한 데이터만 추출합니다.
6. 결과가 맞는지 `capture_view`로 CAD 화면을 함께 확인합니다.

## 예시 프롬프트

```text
현재 열린 EG-BIM 도면 이름과 저장 경로를 확인해줘.
```

```text
레이어 목록을 보여주고, 꺼져 있거나 잠긴 레이어가 있는지 알려줘.
```

```text
#work 레이어의 LWPOLYLINE 개수를 먼저 세어줘.
```

```text
도면에서 "교량"이라는 문자를 찾아서 위치와 핸들을 알려줘.
```

```text
현재 화면을 캡처해서 어떤 영역이 보이는지 설명해줘.
```

```text
좌표 (0, 0)에서 (100, 0)까지 TEMP 레이어에 선을 하나 그려줘.
```

```text
선택한 객체의 핸들을 기준으로 레이어를 CHECK로 바꿔줘.
```

## AutoLISP 사용 시 주의 사항

- IntelliCAD 9.x 환경에서는 `vlax-*` 계열 함수가 안정적으로 동작하지 않을 수 있습니다.
- 가능하면 기본 AutoLISP 함수 중심으로 작성하는 것을 권장합니다.
- 큰 도면에서 전체 선택을 반복하면 CAD가 멈추거나 타임아웃될 수 있습니다.
- `send_command`는 명령 문자열의 끝 공백을 제거한 뒤 실행합니다. 불필요한 Enter가 이전 명령을 반복 실행하지 않도록 하기 위한 안전장치입니다.

## 개발자 참고

이 저장소는 MCP 서버 자체를 공개 대상으로 관리합니다. 실험용 도면, 수량산출 검토 자료, 프로젝트별 분석 스크립트는 로컬 작업 공간에서 관리하고 저장소에는 포함하지 않는 것을 권장합니다.

공개 저장소에 올리기 전 확인할 항목은 다음과 같습니다.

- DWG, GBK, BAK 등 CAD 원본/백업 파일 제외
- 프로젝트별 임시 CSV/TXT/PNG 제외
- 민감한 도면명, 좌표, 발주처 정보 포함 여부 확인
- 큰 도면 작업은 `count_entities`로 규모 확인 후 진행

## License

MIT
