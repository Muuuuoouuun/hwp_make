# macOS 운영 가능성 감사

2026-10-09 사용자의 Mac 사용 가능 확인, 실제 L Windows14개 probe와 최신 app198 전달용 ZIP 완료 반영. **실제 Mac 런타임 검증은 수행하지 않았다.** 최신 묶음은 전체51종 H를 실행한 현재 Windows 제품의 일반 페이지복귀·편지 수정을 포함한다.

## 실제 Mac 실행에 사용할 묶음

[최신 진단 ZIP](../../../tmp/mac-basic-runtime-20261009-app198/hwp-make-mac-diagnostic-app198.zip)은 현재 app198과 실제 영어PDF3종·H고3HWPX를 담았다. 앱+matrix 해시는 실제 H `70bf7ab8…`와 같으며, ZIP SHA-256은 `64dc6b3503924eef2832e6b7a7904d238ac345460f555f6464443e5bd6839244`다. 정적41개·제품/출처6개와 root독립238파일 ZIP 전체 바이트/CRC/경로·현재제품·stdlib validate-only 검사가 통과했다. source/app·vendor resource·static 외에 privateDB/설정/.env/key/Windows폰트/nativewheel은 포함하지 않았다. 이전 app197 묶음·증거는 그대로 보존했다.

압축을 푼 `hwp-make-mac-diagnostic` 폴더에서 `sh run_mac.sh --english3`를 실행한다. 실제 Darwin을 확인한 뒤 폴더 안 venv에 원본lock에서 파생한 Mac pin을 설치하고 실제14probe 및 같은 영어3 API를 실행한다. 결과는 `reports/run-…/bundle-result.json`과 `runtime-macos.json`이다. 설치·일반Macrhwp0.7.0의 버전/TAB 차이·변환/품질 실패도 보존한다. 자동 외부전송은 하지 않는다. [실행 설명](../../../tmp/mac-basic-runtime-20261009-app198/hwp-make-mac-diagnostic/README.ko.md).

최신 ZIP은 새 일반 페이지복귀 v5와 적용된 편지 physical row·terminal spacing 수정을 포함하는 고정 기준이다. 기존 app197 ZIP은 그 두 수정 전의 별도 기준이다. `runtime-preflight-real-windows-l-public16.json`의14PASS는 당시 Windows Tk/native5 실측이며 Mac 성공 근거가 아니다. 실제 Mac 결과를 받은 뒤 설치·글꼴·renderer·변환 실패를 구분한다.

별도 C 독립 전달 검증26/26도 ZIP64dc·manifest6da·현재198/H참고파일·Unicode 공백 경로의 validate-only를 확인했다. `tmp/mac-basic-runtime-20261009-app198-independent-c/report.json`에 있으며 Mac/native/설치/API 실행과 외부전송은 하지 않았다.

현재 판정은 **소스 실행 가능성은 있으나, Windows와 같은 변환 품질이나 Mac 설치 앱 제공 준비 완료는 미확인**이다. 세 단계는 서로 독립적이다.

| 단계 | 현재 판정 | 근거 |
| --- | --- | --- |
| Python 소스 설치·실행 | 가능성 있음, Mac 실검증 필요 | 일반 `rhwp-python 0.7.0`에 arm64/x86_64 wheel이 있고 launcher에 Darwin 분기가 있다. Mac의 Python/Tk·모든 native dependency import·실제 GUI/worker 실행은 확인하지 않았다. |
| 렌더·변환 품질 동등성 | 충족 근거 없음 | Windows는 프로젝트 수정 renderer, Mac은 일반 PyPI renderer를 설치한다. Windows 폰트 탐색 경로도 남아 있다. 현재 Windows 시험지 점수와 회귀 PASS를 Mac 점수로 전용할 수 없다. |
| Mac 설치 앱 배포 | 현재 구성으로 제공 불가 | 기존 체인은 Windows venv, PyInstaller EXE/COLLECT, Inno Setup이다. Mac .app BUNDLE·target별 native renderer·서명/배포 검증이 없다. |

## 수행한 검증과 한계

- `python -X utf8 scripts/verify_desktop_macos_paths.py`: **PASS, exit 0**. 로그는 `tmp/macos-audit-2026-10-07/verify_desktop_macos_paths.log`이다. 별도 `HWP_MAKE_DATA_DIR`와 `HWP_MAKE_SETTINGS_DIR`로 실행해 기존 DB·설정을 사용하지 않았다.
- 이 검사는 import 뒤 `sys.platform='darwin'`으로 바꾸고 subprocess를 stub한다. `open` 명령, Application Support 경로, 열기 실패의 `OSError`만 검사한다. Tk 창·UI_FONT·아이콘 guard·실제 파일 열기·frozen worker·렌더 품질을 검사한 것으로 보지 않는다.
- 현재 패키징 정적 검증 **PASS, exit 0**: renderer manifest의 파일 17개 SHA-256, `0.7.0+nativecell5` wheel METADATA의 버전과 `cp310-abi3-win_amd64` tag가 일치한다. wheel 내부 28개 파일과 실제 설치 파일이 정확히 같으며 `_rhwp.pyd` SHA-256은 `864c06ff8a30a9c15dd60d2042d8cc3ce4a24bb77920965da78aae336914ef88`이다. 결과는 `tmp/macos-audit-2026-10-07/renderer-static-proof-nativecell5.json`이다. Mac wheel은 0개다. 이는 설치 바이트의 일치 검사이며 Mac 호환성을 입증한 검사가 아니다. 기존 nativecell1/nativecell3 정적 검사 근거는 같은 폴더에 보존했다.
- Windows nativecell5의 실제 TAB 순서·소수 폭 수정은 Rust focused 47개, 앱 회귀 14개 및 fresh 영어 3종의 원문·열기·편집·렌더 검사를 통과했다. 이후 현재 native 글자 폭 측정을 제품의 공개 저장 경로에 적용해 실제 17번의 마지막/중간 선택지 편집과 재저장 열 정렬도 통과했다. 현재 J에서는 40번 source→native 답란 자동 생성도 적용·검증했으며 전체 페이지 품질 gate는 미달이다. 이 Windows 결과를 Mac 결과로 전용하지 않는다.
- 제공된 Apple 도구 `mcp__xcodebuildmcp__list_sims({})`의 읽기 호출은 `spawn xcrun ENOENT`로 실패했다. 이 세션에서 사용할 수 있는 Mac 실행 환경을 확인하지 못했다. 다른 프로젝트를 탐색하지 않았다.

## 확인된 차이와 오류 요소

| 우선순위 | 구체적 근거 | 영향 |
| --- | --- | --- |
| P1: custom renderer 누락 | `requirements.txt`, `requirements.lock.txt`: Windows AMD64만 `0.7.0+nativecell5`, Mac은 PyPI 패키지. `packaging/renderer/manifest.json` target은 `x86_64-pc-windows-msvc`. | 이 저장소의 중첩 글상자, 인라인 개체, 셀 배경·비인라인 표 offset, 정확한 글꼴 별칭 및 셀 안 SQUARE 그림 배치·문단 TAB 순서·소수 폭 패치를 Mac에 설치하지 않는다. 해당 기능의 Mac 렌더 결과가 동일하다는 보장이 없다. |
| P1: Mac 빌드 체인 부재 | `scripts/build_desktop.ps1:6`은 `venv\Scripts\python.exe`, `:16`은 `ISCC.exe`, `:27`은 Windows 설치 EXE. `packaging/basic.spec:23–26`은 EXE/COLLECT로 끝난다. | 기존 설치물은 Mac 앱이 아니다. Mac .app 구성과 native dependency 수집·서명이 별도로 필요하다. |
| P1: Windows 폰트 탐색 | `app/pdf_layout_writer.py:612–642`: Windows 파일명 목록과 `SystemRoot` 또는 `C:\Windows/Fonts`만 사용한다. | Mac에 동일 폰트가 설치되어 있어도 `_calib_font`가 찾지 못한다. None으로 후퇴하므로 전체 충돌로 단정할 수 없지만, 설치 폰트 기반 폭 보정이 사라진다. |
| P2: 렌더러 버전 재현성 | 기본 requirements는 Mac `rhwp-python>=0.7`, lock은 `==0.7.0`. | 설치 방법에 따라 다른 renderer/core를 사용할 수 있다. 새 버전이 자체적으로 custom patch와 동등하다고 가정하면 안 된다. |
| P2: 브라우저 앱 데이터 위치 | `app/storage.py:18–19`, `app/web_store.py:20–25`의 기본값은 저장소 아래 data다. | 개발 checkout 실행과 별개로, 프리미엄/웹 앱을 읽기 전용 설치 위치에 넣으면 사용자 데이터 디렉터리를 지정해야 한다. Basic은 이미 Application Support/job별 data를 사용한다. |
| 미검증: 실제 Mac 편집기 | 현재 open probe는 `scripts/probe_hwp_open.ps1`의 COM/UIAutomation/Hwp.exe 경로다. | Mac에서 한글/Word 실제 열기·편집·재저장·인쇄를 이 probe로 검증할 수 없다. 구조 검사는 실제 편집기 검증을 대체하지 않는다. |

일반 Mac 패키지 자체가 설치 불가능하다는 결론은 아니다. 공식 PyPI 0.7.0은 Python 3.10+의 macOS ARM64 및 x86_64 wheel을 제공한다. 다만 이 저장소의 custom patch 적용 여부는 별개다. [PyPI 파일 목록](https://pypi.org/project/rhwp-python/0.7.0/#files)

Tkinter도 macOS에서 사용할 수 있으나 Python 배포판의 optional module이다. 실제 Mac에서 `python -m tkinter`로 설치와 창 표시를 확인해야 한다. [Python 공식 문서](https://docs.python.org/3/library/tkinter.html)

## 이미 이식성을 고려한 경로

- `run_desktop.py:17,21,30,52,172,283`은 Mac UI 폰트, Application Support, `open`, Windows .ico 호출 차단, 생성 플래그 0, DPI API guard를 포함한다. frozen worker는 `sys.executable --worker <spec>`로 재호출한다(`:168`). 실제 .app에서 이 동작은 아직 미검증이다.
- Basic은 HTTP listener를 실행하지 않고 job별 변환을 수행한다. worker는 main import 전에 job별 `HWP_MAKE_DATA_DIR`를 설정하고 provider key 환경변수를 제거한다(`app/desktop_convert.py:44–48`).
- HWP 가져오기는 rhwp/olefile, HWPX는 XML 경로다(`app/importers.py:3400` 이후). 앱 변환 자체에 COM은 필수가 아니다. Basic 출력은 HWPX/DOCX이며 `.hwp` 직접 저장은 현재 선택지에 없다.
- Python/uvicorn 브라우저 경로는 OS 전용 API에 묶이지 않는다. `run_local.ps1`의 실행기 후보는 Windows 경로를 포함하지만 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8787`로 직접 시작하는 구조는 가능하다. `run_web_prototype.py`는 loopback 8788 및 `webbrowser.open`을 사용한다.
- 현재 Basic 번들은 프리미엄/웹 앱 배포물이 아니다. `packaging/basic.spec:8`은 basic-static을 포함하고 `:20`은 web 모듈을 제외한다. Mac Basic과 프리미엄 브라우저 경로의 검증을 구분해야 한다.
- `app/main.py`의 `_nfc`는 Mac의 분해형 한글 파일명을 고려한다. 실제 파일 대화상자·재열기는 별도 검증이 필요하다.
- 로그인은 SQLite·PBKDF2·해시 세션으로 구현해 Windows credential API에 의존하지 않는다(`app/local_auth.py`, `app/web_store.py`). 쿠키는 HttpOnly/SameSite strict이고 HTTPS에서 Secure를 사용한다. Mac 전용 로그인 차단은 발견하지 못했다.
- AI key는 Keychain이 아닌 JSON이며 POSIX 파일 모드 0600을 적용한다(`app/recognition/settings.py:59–60,245–251`). Keychain 연계는 개선 후보이며 현재 필수 실행 블로커로 보지 않는다.

## 동일 패치를 적용하는 portable renderer build 설계

이 절의 파일명과 옵션은 **제안**이다. 아직 구현하거나 의존성을 교체하지 않았다.

1. 공통 Python build driver에 source 준비와 검증을 모은다. core/binding commit, 두 patch, Cargo.lock, Rust/maturin 버전을 현재 manifest로 고정하고 hash 확인 → fresh build directory → checkout → `git apply --check` → patch 적용 순서를 공통으로 사용한다. 기존 checkout을 지우거나 재사용해 숨은 변경을 포함하지 않는다.
2. target adapter를 구분한다. 기존 `x86_64-pc-windows-msvc`는 cargo-xwin 경로를 유지한다. Mac은 실제 Mac host에서 `aarch64-apple-darwin` 또는 `x86_64-apple-darwin` native build를 수행한다. Windows cross-build 전용 PYO3/XWIN 설정을 Mac native branch에 전파하지 않는다. 첫 배포는 각 아키텍처별 wheel/app으로 검증하고 universal2는 별도 검증 후 추가한다.
3. 공통 source/patch hash와 target별 wheel hash·tag·core version·binding version을 manifest에 기록한다. 같은 patch라는 사실과 각 바이너리의 실행 검증 결과를 구분해 기록한다. 현재 `nativecell5` 버전 이름만으로 동일성을 판정하지 않는다.
4. 설치 파일은 검증된 target wheel을 명시적으로 선택한다. Mac custom wheel이 준비되기 전에 존재하지 않는 wheel 경로를 requirements에 추가하지 않는다. 일반 PyPI fallback은 개발용으로 명시하고, 품질 검증 실행에서는 예상 renderer fingerprint가 없으면 동등성 미확인으로 보고한다.
5. target별 native suite와 같은 실물 PDF 입력의 API/편집·재저장 검사를 수행한다. source-content/문항 소속/원문 보존, 실제 render glyph bounds, frame·inline controls·bitmap background, page count와 기존 품질 점수를 함께 검사한다. 단순 import나 XML 유효성으로 Mac 품질 통과를 표시하지 않는다.

공통 정적 게이트에서 검사할 항목은 manifest 참조 파일 hash, source commit/patch lock, wheel METADATA/WHEEL tag 및 version, 포함 native library 형식·architecture, requirements marker의 target 선택, Windows 전용 XWIN 설정의 Mac branch 유입 여부다. 정적 게이트 통과는 Mac 실행 통과를 의미하지 않는다.

## 독립적으로 진행 가능한 최소 작업과 조율 대상

앱 코드 수정 전 root와 소유 범위를 조율한다.

| 작업 | 먼저 가능한 범위 | 조율/후속 검증 |
| --- | --- | --- |
| Mac 실행 안내·짧은 launcher | source checkout에서 venv/bin/python, Application Support data env, loopback 주소를 지정하는 별도 shell/Python 실행 경로. 기존 Windows launcher는 유지. | 실제 Mac에서 Tk/uvicorn 시작 및 한글 경로 검증. 프리미엄은 data env를 app import 전에 설정해야 한다. |
| runtime preflight | 별도 script에서 Python/Tk/rhwp/PyMuPDF import, renderer version/core/target fingerprint, 쓰기 가능한 data 경로를 검사. 누락 진단은 버전 정보만 출력하고 비밀키는 읽지 않는다. | 새 product startup guard는 기존 Basic/Premium 동작을 막을 수 있으므로 별도 승인·회귀 필요. |
| 공통 renderer 정적 검증 | manifest/file hash/wheel tag/target marker 검증 script는 앱 코드와 분리 가능하다. | 실제 Mac wheel build는 Mac host가 있어야 완료 가능하다. |
| Mac .app 빌드 spec | 별도 BUNDLE/Info.plist/.icns와 Mac venv build 경로 설계. GUI·worker·native libraries 수집을 함께 확인. | 실제 Mac bundle 검사, 서명·권한·최소 OS 및 아키텍처 확인. 배포용 signing/notarization은 로컬 debug와 구분한다. |
| 폰트 탐색·fallback 진단 | OS별 설치 font search 또는 명시적 font path 설정을 설계. | `app/pdf_layout_writer.py`는 root 소유와 조율해야 한다. 동일 폰트 face와 실제 glyph/render 회귀 필요. 설치 폰트를 임의 번들하지 않는다. |

Mac .app의 Info.plist/MacOS/Frameworks/Resources 구조와 native binary signing은 실제 Mac 산출물로 확인해야 한다. Tk 기반 앱에 argv emulation을 무조건 추가하면 안 된다. 공식 문서는 Tk 시작·crash 위험을 명시한다. [PyInstaller app bundle](https://pyinstaller.org/en/stable/usage.html#building-mac-os-x-app-bundles), [binary signing와 event 처리](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing)

## 실제 Mac에서 남은 실검증

- arm64 및 지원 대상 Intel Mac의 Python/Tk/native dependency 설치와 renderer fingerprint.
- source launcher와 frozen .app의 GUI 표시·파일 선택·저장·결과/폴더 열기·worker 재호출·중단/실패 처리.
- Application Support DB/설정/최근 기록, source file과 destination의 권한, NFD/NFC 한글 및 공백 파일명, 기존 데이터와 job isolation.
- Basic 오프라인 실행, 브라우저 Basic/Premium 로그인·쿠키·loopback API·static 자원·재시작 후 세션/설정.
- 한글/영어/수학 font face와 미설치 fallback, 동일 실물 시험지 전체 변환·원문·문항 소속·실제 렌더 품질·편집/재저장.
- Mac 한글/Word에서 열기·수식/표/그림/글상자 편집·재저장·인쇄. 지원되지 않는 binary HWP 저장과 COM probe는 별도 범위로 표시.
- .app 구조, arm64/x86_64 native library와 최소 macOS, clean-user 설치/첫 실행, signing·Gatekeeper·배포 공증 결과.

현재 감사로 설치 가능성에 대한 근거와 수정 후보는 확보했지만, 이 목록의 Mac 실행 항목은 **미검증** 상태다.

## 직전 G 저장 폭 측정의 이식성 범위

전체 G 검증 당시 적용본은 `native_line_metrics.py` (`c7845255…`), `native_line_cache.py` (`a64c665c…`), `question_reflow.py` (`d32d9eae…`)이다. 선택적 native 기능은 운영체제 이름이나 버전 문자열을 신뢰하지 않고 실제 네 개 TAB probe의 동작으로 판정한다. 이 계약을 만족하지 않거나 native import·현재 스타일·연산 한도가 실패하면 기존 보수적 cache로 복귀한다. Windows의 이전 custom native4를 사용한 실제 제품 복귀 검사 6개가 통과했다. 이것은 일반 PyPI renderer나 Mac에서 실행한 검사가 아니다.

현재 `packaging/basic.spec`는 `collect_submodules('hwpx')`를 사용하므로 새 vendor 모듈을 수집하는 정적 경로는 있다. 수정 후 새 desktop 번들 실행은 이 검사에 포함하지 않았다. 최종 Windows 51종 G는 312쪽/1,355문항, 코드·런타임 한 snapshot/STABLE이며 11종 파일 생성·40종 strict 거절이다. 영어 3종은 모두 실제 8쪽/45문항·원문 보존·열기·구조·렌더 검사를 통과했으나 전체 페이지 품질 목표에는 미달이다. 이 수치는 Mac 품질 근거로 사용하지 않는다.

근거: `tmp/renderer-tabs-fractional-20261008/native-line-production-native4-opt1/report.json`, `tmp/september-audit/native-tab-production-q17/report.json`, `tmp/september-exam-matrix/all51-native5-20261008-g/report.json`, `tmp/september-audit/full51-question-priority-native5-g.json`.

## 2026-10-08 밑줄 TAB 저장 경로 추가 확인

이 단계 당시 제품은 metrics `e0172040…`, cache `0a24d2a8…`이며 reflow `d32d9eae…`는 그대로였다. 기존 현재 글꼴·일곱 언어 스타일 검증에 정확한 BOTTOM/SOLID 검정 밑줄을 추가하고, 현재 줄의 같은 스타일 TAB/비공백 라벨/TAB 구간이 실제 가용 폭 안에 들어갈 때만 끝 TAB에 제한된 줄바꿈 예외를 적용했다. Windows native5의 실제 공개 편집·저장 산출물에 대한 독립 페인트20개와 폭·경계 검사12개가 통과했다. source→native 답란/선택지 열 제목 생성은 당시 제품에 적용하지 않았으며, 원본 대비 선 Y·두께와 셀 높이 변화의 한계도 남아 있다. 근거는 `tmp/september-audit/question-only-native5/matrix-d/labeled-rule-tabs/underline-product-independent/{painted-report.json,width-contract-report.json}`이다.

이 추가 범위도 **실제 Mac에서 실행하지 않았다**. Windows native4의 기능 미충족/fallback 검사나 플랫폼 모의 검사는 실제 Mac 동작·품질 근거가 아니다. Windows의 후속 구현·회귀는 외부 도움 없이 계속할 수 있다.

Mac 실검증을 완료하려면 지원 대상 실제 Mac에서 동일 시험지 변환, 공개 편집·저장·재열기와 실제 렌더를 실행할 수 있도록 장비 또는 실행 결과를 제공하는 사용자 도움이 필요하다.

## 2026-10-08 선택지 열 제목 수평 복원 적용

전체 I 영어 3종 검증 당시 선택지 열 제목 적용본은 `app/pdf_source_choice_headers.py` (`3c64e082…`)와 writer (`5b8324d3…`)였다. Windows의 공유 Basic 영어 source-layout 생성 경로에서 실제 source/native 문항 소속·글꼴·열 너비를 증명한 선택지 열 제목의 수평 배치만 복원했다. 답란 source 생성·Y 위치와 프리미엄 양식은 이번 범위에서 제외한다. 당시 실제 적용·독립 검증 근거는 `docs/audits/2026-10-07/source-choice-column-headers-20261008.md`와 `tmp/september-audit/choice-column-header-wrapper-independent-product/report.json`이며, 후자의 강제 validator `RuntimeError` 반환 실패 12/13 기록은 보존했다.

열 제목 wrapper 후속 모듈은 `c737378c…`이며 당시 writer `5b8324d3…`와 native/vendor는 그대로였다. I 당시 적용본에서 파일 wrapper의 `RuntimeError` 복귀 catch만 추가했음을 원시 바이트로 확인했다. 별도 독립 wrapper 13개가 모두 통과하고 정상 산출물도 기존 후보와 바이트까지 같았다. 근거는 `tmp/september-audit/choice-column-header-wrapper-independent-final-c737/report.json`이다. 이 후속 검증은 해당 예외·파일 교체 경계에 한정하며, 전체 I 결과를 새 코드의 전체 재실행 결과로 표시하지 않는다. 최신 J writer와 cache는 아래에 별도로 기록한다.

이 모듈도 **실제 Mac에서는 실행하지 않았다**. 현재 native 글자 폭/TAB 기능 계약을 만족하지 않으면 복원을 생략하고 원본 바이트로 복귀하지만, 이러한 안전 복귀는 Mac에서 선택지 열 제목이 복원되거나 Windows와 같은 품질을 낸다는 증거가 아니다. Mac의 실제 실행·렌더·편집 검증과 프리미엄 양식의 별도 검증을 대신하지 않는다.

## 2026-10-09 J와 실제 호스트 진단

Windows J는 영어 고1·고2·고3 모두 실제 8쪽/45문항, 원문·native 텍스트 보존·열기·편집 구조·렌더 검사를 통과했다. 40번의 문자가 들어간 두 답란도 source→native로 자동 생성한다. 현재 writer는 `98717722…`, source/native 답란 helper는 `bf5f7dba…`/`ddde6979…`, metrics/cache는 `e0172040…`/`589da0bf…`다. 당시 제품 및 공개 저장 관련 251개 검사를 통과했으나, 전체 페이지 품질 gate와 원본 밑줄의 높이·두께 일치는 미완료다. J는 영어 3종의 재실행이며 앞선 전체 51종 G의 새 재실행이 아니다. [적용 범위와 실제 J 증거](source-labeled-answer-rules-20261008.md).

이후 현재 보이는 답란 판정 모듈 `pdf_answer_blanks.py`를 `06517609…`로 보강했다. 실제 제품 기본 import 171개와 최신 K의 영어 3종 API 검사를 마쳤고, 정상 출력의 전체 SVG는 J와 정확히 같다. K 제품 snapshot `c53fddeb…`/renderer `33ab6b67…`는 STABLE이다. 이 수정은 source 판정이며 native 복원 함수·renderer/vendor는 그대로다. K도 나머지 48종 재실행·새 공개 편집·실제 Mac 검증을 뜻하지 않는다. [현재 판정 적용 기록](source-current-answer-rule-paint-20261009.md).

새 `scripts/check_basic_runtime.py`는 **실행한 실제 호스트**의 Python, native dependency 9개, Tk, desktop launcher import, 격리된 한글 파일명 쓰기, 실제 calibration font face 및 HWPX→SVG/PDF를 검사한다. 각 검사는 별도 subprocess와 임시 data/settings 디렉터리를 사용하며 provider credential 환경변수를 제거한다. 입력 HWPX는 읽기·렌더만 하고 실행 전후 SHA를 비교한다. native TAB 검사는 실제 capability가 실행된 경우와 후보 문단에서 검사되지 않은 경우를 구분한다. 실제 검사된 TAB 기능이 미지원이거나 설치 renderer 버전이 repository manifest와 다르면 전체 실패와 exit 1에 반영한다. 버전 문자열 일치는 수정 바이너리의 동등성으로 판정하지 않는다.

실제 Windows AMD64/Python 3.14.3에서 현재 J HWPX(`0828e19a…`)를 넣은 14개 검사가 모두 통과했다. 이번 실행에는 실제 Tk 창의 생성·withdraw·종료도 포함했고, native 문서는 8쪽 모두 표시 텍스트와 PDF를 생성했다. 실제 TAB capability는 `[0,37,150,150]`이며 입력 SHA는 같다. 최신 보고서는 `tmp/macos-audit-2026-10-07/runtime-preflight-real-windows-j-with-tk-aggregation-v2.json`, script SHA는 `13e8fd32…`다. 이전 Tk import만 한 실행과 최소 생성 문서 실행은 별도 보고서로 보존한다. 최소 문서의 최초 실행은 preview text 누락으로 실패했고, 진단 fixture의 preview part를 넣어 재실행했다. 제품 변환기의 결함이나 Mac 실행 실패로 해석하지 않는다.

독립 검토에서 이전 `db62cf77…` 도구는 실제 native4로 J를 렌더한 경우 TAB 미지원과 manifest 버전 불일치를 기록하면서도 전체 성공으로 집계했다. `13e8fd32…`에서 보강 후 실제 native4/J는 두 사유로 exit 1이며 `[0,0,150,150]` 미지원 결과와 입력 불변성을 보존한다. native4 최소 문서는 TAB 검사를 미실시로 구분하고 버전 불일치만으로 exit 1이다. 두 음성 실검사가 통과했다. 독립 transport/settings 22개 검사와 자료는 `tmp/macos-audit-2026-10-07/c-independent-runtime-review/{review-report.json,aggregation-13e8-report.json}`에 있다. 실제 child가 아닌 합성 malformed JSON/non-object marker가 부모 예외를 발생시키는 낮은 우선순위의 경계는 남아 있으며 전체 오류 복구 완료로 표현하지 않는다.

실제 Mac의 source checkout과 해당 venv에서 다음처럼 실행할 수 있다.

```sh
python -X utf8 -B scripts/check_basic_runtime.py --expect-platform darwin --check-tk-window --output runtime-macos.json
```

`--hwpx /절대/경로/실제출력.hwpx`를 추가하면 해당 출력의 실제 렌더·TAB 진단도 함께 기록한다. HWPX를 지정하지 않으면 진단용 최소 문서를 생성하며 문항 변환 품질을 검사하지 않는다. `--expect-platform darwin`은 플랫폼을 바꾸지 않으며 실제 호스트가 다르면 실패로 기록한다. GUI 세션에서 실행해야 Tk 창 생성 여부를 확인할 수 있다.

현재 저장소의 custom Mac wheel은 여전히 0개이며 renderer manifest target은 Windows다. 이 도구의 Windows 성공은 Mac 실행·전체 시험지 변환·한글/Word 편집·앱 번들·서명 성공이 아니다. 사용자가 실제 Mac 사용 가능을 확인했으며, 그 환경의 실행 결과가 필요한 외부 도움이다. Windows 문항 후속 수정에는 추가 사용자 자료가 필요하지 않다.

## 2026-10-09 app199 실제 Mac 전달용 진단 v2

`tmp/mac-basic-runtime-20261009-app199-v2/hwp-make-mac-diagnostic-app199-v2.zip`은 현재 app199 `d79145b4…`와 실제 영어PDF3종·직전 H고3 HWPX를 담은 243파일/5,362,268bytes 묶음이다. ZIP SHA는 `0fa112b16d3c00cfd352c246786242c2e689ad8f68a4888aad120a75b5e3bc8a`다. 원래 vendor LICENSE/NOTICE를 포함하고 Windows wheel·native binary·글꼴·사용자DB·키는 포함하지 않는다. 정적72개·최종CLI/license10개와 root 독립 ZIP/current199 검산22개가 통과했다. 이 수치는 실제 Mac 실행 결과가 아니다.

Mac에서 압축을 푼 `hwp-make-mac-diagnostic` 폴더의 터미널에서 실행한다.

```sh
sh run_mac.sh --english3 --public-edit
```

전용 `.mac-venv`에 Mac 의존성을 설치하고 runtime 진단, 영어3종 초기 변환, H참고파일의 실제 공개 API 편집·저장·재열기·원문 복귀를 별도로 집계한다. 결과는 `reports/run-…/bundle-result.json`과 같은 실행 폴더에 남는다. 실제 편집기의 GUI 조작·Hancom retention은 이 도구의 범위에 포함되지 않는다.

공개 편집 진단은 문항·행 ID를 고정하지 않고 현재 전체45문항과 완전한 XML 선택지 행을 확인한다. Mac의 첫 실제SVG를 자체 baseline으로 삼아 복귀를 검사한다. Windows와의 SVG·쪽수 차이는 실패 관찰로 기록하되 읽기·문항 소속·원문이 유효하면 편집·복귀 진단을 계속한다. 입력바이트·문항/run 유일성·원문 무결성 실패는 중단한다. 일반 PyPI renderer의 TAB/버전 비지원도 실패 또는 unsupported로 남긴다.

현재 실제 Mac 실행·공개 편집 진단은 미실시다. 이전 app197·app198와 app199v1의 조기중단 진단 및 정적68개/ZIP은 보존했다. 새 묶음의 근거는 `HANDOFF.json`(`a414f430…`), `qualification-report.json`, root `tmp/september-audit/mac-app199-v2-root-transport.json`(`c36760fd…`)이다. root 최초 검산에서 file-record dict를 SHA 문자열과 직접 비교한 harness 오류는 별도 보존하고, 수정 검산의 전체 바이트·길이·CRC·경로·원본3개·제품199 일치를 구분했다.
