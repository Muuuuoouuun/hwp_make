# 중첩 글상자·실제 폰트 조회·셀 그림 배치 렌더러 수정본

Windows x64 / Python 3.10 이상에서 `rhwp-python 0.7.0+nativecell3`를 사용한다.
프로젝트 루트에서 `python -m pip install -r requirements.txt`로 설치한다.
공식 배포판이 아닌 이 프로젝트의 수정 빌드이며, 코어 버전 문자열은 0.7.13을 유지한다.

원본 소스 커밋, wheel·패치·Cargo.lock SHA-256은 `manifest.json`에 기록했다.
두 MIT 라이선스를 보존한다. Rust 바인딩 코드는 변경하지 않았다.

수정한 실제 렌더 경로:

- 문항 글상자 안의 표 셀에서 인라인 글상자를 전체 셀 경로와 함께 그린다.
- 일반 텍스트가 없는 수식·글상자 줄에서도 위치를 등록하고 각 개체의 폭을 사용한다.
- 셀의 인라인 글상자 줄 높이를 글자 높이로 줄이지 않는다.
- 글상자 안의 비인라인 표는 자체 가로 정렬과 위치 값을 사용한다.
- 글상자 안의 표 셀에서도 이미지·패턴 배경을 일반 표와 같은 경로로 그린다.
- PNG에서 내부 U+FFFC 개체 표시 문자를 글리프로 그리지 않는다. SVG·웹 캔버스와 같은 동작이다.
- PNG/Skia와 PDF/fontdb에서 기존 family/style 조회가 실패할 때만 실제 로드된 face의 legacy family/name1 또는 PostScript/name6를 정확히 대응한다. 공백·하이픈 및 대소문자 정규화 후 유일한 face여야 하며 실제 width/slant와 intrinsic weight를 유지한다.
- 수평·상단 정렬된 셀에 유효한 줄 캐시와 단일 non-TAC/flowWithText/Square/PARA 그림이 있을 때, 기존 body-picture 위치·그리기 경로를 사용한다. 소유 문단의 실제 첫 TextLine에 한 번만 anchor하며 그림 높이를 문단 높이에 다시 더하지 않는다. 그림 아래까지 후속 의미 문단도 자신의 캐시 cs/sw를 유지한다. TAC·다른 wrap·페이지 anchor·수식/다른 control·잘못된 캐시는 기존 경로를 유지한다.
- 복구한 Latin face가 지원하지 않는 문자는 PDF의 기존 CSS 선택 face와 fallback을 유지한다. 서로 다른 fallback chain이 충돌하면 alias 복구를 포기한다. 일반 Arial400·명시 bold700·italic 및 모르는 이름은 기존 경로를 유지한다.

문서를 이미지로 덮거나 출력 SVG/PNG를 후처리하는 변경은 없다.
다른 OS/아키텍처에는 이 wheel을 적용하지 않으며 해당 환경의 새 빌드는 검증하지 않았다.
기존 원본 보존·실제 표시 검사는 지원되지 않는 출력의 제공을 계속 차단한다.
이전 `nativecell1`과 폰트 수정만 적용한 `nativecell2` wheel을 재현·비교용으로 함께 보존한다. `nativecell3`가 셀 Square 그림 배치를 추가한다. 실제 고2 Q27 prototype의 그림 위치 오차는 x +0.00224px / y −0.08456px이며, 이 결과는 전체 문서의 목표 품질 달성을 의미하지 않는다. 앱의 public edit/save 재캐시는 별도 검증 대상이다.

## 소스에서 재빌드

WSL Ubuntu의 준비된 Rust/LLVM 환경에서 `sh packaging/renderer/rebuild-windows.sh`를 실행한다.
필요한 패키지는 git, build-essential, clang, lld, llvm, pkg-config, python3-venv,
ca-certificates, ninja-build이다. Rust 1.98.1, maturin 1.15.0, cargo-xwin 0.23.1을 사용한다.
빌드 스크립트는 별도 캐시 디렉터리에 정확한 소스 커밋을 체크아웃하고 패치와 lock을 적용한다.
완성 wheel은 캐시의 `wheels`에 남기며 배포본을 자동 교체하지 않는다.
MSVC/SDK는 cargo-xwin으로 준비하며 네트워크 다운로드가 필요하다.
바이너리 해시가 동일한 재빌드까지 검증한 것은 아니다.

검증 명령은 프로젝트 루트에서 실행한다:

```powershell
python -X utf8 scripts/verify_native_nested_textbox_editing.py
python -X utf8 scripts/verify_native_mixed_table_paragraphs.py
python -X utf8 scripts/verify_native_inline_label_writer.py
python -X utf8 scripts/verify_native_inline_label_audit.py
python -X utf8 scripts/verify_native_background_rendering.py
python -X utf8 scripts/verify_native_background_frame_flow.py
```

이 검사는 실제 출력, 라벨 교체, 문단 +162자 편집, 재저장, 8개 빈칸 보존,
다음 문단과의 겹침, 내부 개체 문자의 불필요한 잉크를 포함한다.

폰트 변경은 폰트 수정 이전 `nativecell1`과 비교한다. 양쪽에 **동일한 HWPX**를 전달한다:

```powershell
python -m pip install --no-deps --target tmp/renderer-baseline packaging/renderer/wheels/rhwp_python-0.7.0+nativecell1-cp310-abi3-win_amd64.whl
python -m pip install --no-deps --target tmp/renderer-candidate packaging/renderer/wheels/rhwp_python-0.7.0+nativecell3-cp310-abi3-win_amd64.whl
python -X utf8 packaging/renderer/verify-font-alias.py --baseline-site tmp/renderer-baseline --candidate-site tmp/renderer-candidate --artifacts tmp/renderer-font-comparison
```

전역 설치를 이미 바꿨다면 보존한 `nativecell1` wheel을 다른 `pip --target` 디렉터리에 설치하고 `--baseline-site`로 그 디렉터리를 지정한다. 이 비교는 실제 Arial/Arial Black/Blackadder ITC 및 한글 폰트가 설치된 Windows 검증 환경을 사용한다.

검사는 regular/bold/italic, 알 수 없는 이름, 잘못된 suffix/slant, Blackadder ITC, 순수·혼합 한글 fallback, 실제 heavy family/PostScript를 포함한다. SVG/page geometry를 유지하고, 기존 경로의 PNG pixels/PDF face·glyph bounds가 동일한지 확인한다. 공통 Rust resolver의 unit tests는 존재하지 않는 이름·width/slant 불일치·여러 실제 face의 모호성·동일 identity 중복도 검사한다. 원본 66glyph의 독립 actual 검증과 세부 로그는 `docs/audits/2026-10-07/renderer-font-lookup-followup.md`를 참고한다.

## 셀 Square 그림의 적용 범위 검사

폰트 수정본 `nativecell2`와 `nativecell3`를 각각 별도 site에 설치하고 같은 실제 Q27 HWPX를 전달한다:

```powershell
python -X utf8 scripts/verify_renderer_embedded_cell_square.py --hwpx tmp/renderer-square/prototype-input.hwpx --baseline-site tmp/renderer-font-lookup/font1-final-site --candidate-site tmp/renderer-square/final-site --artifacts tmp/renderer-square/final-scope
```

최종 격리 검사에서 그림 위치가 바뀌는 positive와 18개의 지원 범위 밖 negative를 분리했다. TAC, 다른 wrap, PAGE/PAPER anchor, 음수 offset, 누락/잘못된 캐시, 복수 그림, 중앙 정렬, 수식 control은 SVG·PNG·페이지 수가 기존과 정확히 같다. 수식·혼합 표·중첩 글상자·공유 표·문항 편집 5개 회귀와 같은 입력 폰트 11개 PNG/SVG/PDF face·bounds 동일성도 통과했다. 패치의 clean upstream 적용과 실제 빌드 source 일치는 `tmp/renderer-square/final-artifacts/patch-replay-proof.json`에 기록했다. 실제 source glyph·최종 public edit/reopen 판단은 앱의 producer/save 변경과 함께 독립 검사한다.

## macOS

이 Windows ABI3 wheel은 macOS에서 사용할 수 없다. macOS 배포는 동일 upstream commit·공통 source patch·Cargo.lock으로 arm64/x86_64 native wheel을 각각 빌드하고, 로드한 실제 폰트의 name table·intrinsic style·CoreText/Skia 조회·PDF 한글 fallback을 확인해야 한다. Windows 전용 weight나 폰트 파일명을 새로 하드코딩하지 않았다. 실제 Mac runtime이 없어 Mac 빌드·실행·서명·품질 동등성은 미검증이다. 비Windows requirements의 PyPI 경로에는 이 수정본과의 패치 동일성을 보장하지 않는다.
