# 중첩 글상자 렌더러 수정본

Windows x64 / Python 3.10 이상에서 `rhwp-python 0.7.0+nativecell1`을 사용한다.
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

문서를 이미지로 덮거나 출력 SVG/PNG를 후처리하는 변경은 없다.
다른 OS/아키텍처에는 이 Windows wheel을 적용하지 않는다. Linux x86_64 별도 빌드는 아래를 참조한다.
기존 원본 보존·실제 표시 검사는 지원되지 않는 출력의 제공을 계속 차단한다.

## 소스에서 재빌드

WSL Ubuntu의 준비된 Rust/LLVM 환경에서 `sh packaging/renderer/rebuild-windows.sh`를 실행한다.
필요한 패키지는 git, build-essential, clang, lld, llvm, pkg-config, python3-venv,
ca-certificates, ninja-build이다. Rust 1.98.1, maturin 1.15.0, cargo-xwin 0.23.1을 사용한다.
빌드 스크립트는 별도 캐시 디렉터리에 정확한 소스 커밋을 체크아웃하고 패치와 lock을 적용한다.
완성 wheel은 캐시의 `wheels`에 남기며 배포본을 자동 교체하지 않는다.
MSVC/SDK는 cargo-xwin으로 준비하며 네트워크 다운로드가 필요하다.
바이너리 해시가 동일한 재빌드까지 검증한 것은 아니다.

### Linux x86_64에서 빌드

Windows wheel은 Linux에 설치하지 않는다. `rebuild-linux.sh`는 같은 소스 커밋,
패치와 Cargo.lock으로 Linux wheel을 만든다. Linux 추가 패치는 글꼴 후보 검색을
렌더러 인스턴스 안에서 최대 256개 캐시하고 사용자 글꼴 변경 시 비운다.
Linux 빌드 버전은 `0.7.0+nativecell1.fontcache1`이며 기존 Windows wheel에는 이 캐시를 적용하지 않았다.
git, C/C++ 컴파일러, pkg-config,
fontconfig·FreeType 개발 패키지, Python 3.10 이상과 venv, rustup이 필요하다.
Debian/Ubuntu의 개발 패키지 이름은 `build-essential pkg-config libfontconfig-dev libfreetype-dev python3-venv`이다.

```sh
export PATH="$HOME/.cargo/bin:$PATH"
sh packaging/renderer/rebuild-linux.sh
```

Rust 1.98.1과 격리된 maturin 1.15.0·patchelf 0.17.2.4를 준비하며 네트워크가 필요하다.
기본 결과 경로는 `~/.cache/hwp-make-renderer-linux/wheels`이다.
`HWP_RENDERER_BUILD_ROOT`로 빈 빌드 경로, `HWP_RENDERER_BUILD_JOBS`로 병렬 수를 지정할 수 있다.
관리자 권한 없이 개발 패키지를 추출한 경우 `HWP_RENDERER_SYSROOT`로 그 경로를 지정한다.
기존 소스 경로는 덮어쓰지 않는다. 생성 wheel의 플랫폼 태그와 실제 실행 환경을 확인한 뒤
앱의 가상 환경에 `python -m pip install --no-deps <wheel 경로>`로 설치한다.
이 과정은 한컴오피스 설치나 한컴에서의 편집·재저장 검증을 대신하지 않는다.

2026-10-23 KST에 Debian 13 x86_64 / Python 3.12.14에서 빌드·설치하고 아래 렌더 검사
6개를 모두 통과했다. 실물 수학·영어 문단 편집과 재저장을 포함하며 FreeType 강제
preload는 필요하지 않았다. 생성 wheel은 `manylinux_2_38_x86_64` / CPython 3.10 이상
태그지만 다른 배포판·Python 버전은 실검증하지 않았다. 소스·도구·산출물 해시는
`manifest-linux.json`에 기록한다. Linux wheel은 로컬 빌드 캐시에 보관하며 저장소에 넣지 않는다.

글꼴 캐시 추가 후 렌더·미리보기 회귀 7/7을 통과했다. 같은 HWPX의 국어 2쪽·영어 1쪽은
기존 PNG와 픽셀까지 동일했고 렌더 호출 시간이 각각 7.54→0.33초, 6.60→0.20초,
11.87→0.22초로 줄었다. 실제 문서·글꼴·동시 작업에 따라 속도 차이가 달라질 수 있다.

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
