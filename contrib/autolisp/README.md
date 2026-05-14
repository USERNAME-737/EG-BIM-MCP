# AutoLISP 보조 유틸리티

이 폴더에는 EG-BIM MCP 서버와 함께 사용할 수 있는 보조 AutoLISP 파일을 모아 둡니다.
MCP 서버의 필수 구성요소는 아니며, 필요할 때 CAD에서 직접 로드해서 사용하는 유틸리티입니다.

## 포함 파일

| 파일 | 명령어 | 용도 |
| --- | --- | --- |
| `화면지정.LSP` | `VV1`~`VV9`, `V1`~`V9` | 현재 화면 영역을 저장하고 다시 불러옵니다. |
| `DGC(엔티티 없어졌을 때).lsp` | `DGC` | AutoCAD에서 작업된 도면을 EG-BIM/IntelliCAD에서 열 때 일부 객체가 사라지거나 비정상 DXF 값이 있는 경우를 점검하고 일부 값을 정리합니다. |
| `MINI.lsp` | `MINI` | 이미지 파일 여러 장을 선택해 한 줄로 삽입합니다. |

## 사용 방법

CAD 명령줄에서 LISP를 로드한 뒤 각 명령어를 실행합니다.

```lisp
(load "contrib/autolisp/MINI.lsp")
```

경로에 한글이나 공백이 있으면 CAD 환경에 따라 로드가 실패할 수 있습니다.
그 경우 파일을 짧은 영문 경로에 복사한 뒤 로드하세요.

## 주의 사항

- 실제 업무 도면에서는 실행 전 DWG 백업을 만드세요.
- `DGC`는 도면 엔티티 데이터를 직접 수정합니다. 먼저 복사본 도면에서 테스트하는 것을 권장합니다.
- `DGC`는 검사 결과를 `C:\temp\dgc_fix.csv`에 기록합니다. 필요하면 `C:\temp` 폴더를 먼저 만들어 주세요.
- `MINI`는 이미지 다중 선택을 위해 로컬 PowerShell을 실행합니다. 신뢰할 수 있는 PC와 파일에서만 사용하세요.
- `화면지정.LSP`는 `HKEY_CURRENT_USER\Software\ViewPortCustom` 아래에 화면 정보를 저장합니다.
- 일부 LISP는 AutoCAD/Visual LISP 계열 함수 또는 Windows 전용 기능을 사용합니다. EG-BIM/IntelliCAD 버전에 따라 동작이 다를 수 있습니다.

## MCP와의 관계

이 파일들은 MCP tool이 아니라 CAD에서 직접 실행하는 LISP입니다.
AI assistant가 `send_command`로 `(load "...")`를 호출하게 할 수는 있지만, 도면 수정 명령은 실행 전에 사용자가 의도를 확인하는 것을 권장합니다.
