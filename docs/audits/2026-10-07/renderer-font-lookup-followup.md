# Renderer family lookup 후속 수정안

2026-10-07. 앞부분은 최초 읽기 전용 진단이며, 같은 날 이어진 renderer 후보 구현과 검증은 아래에 구분해 기록한다. 앱 코드·설치 폰트·품질 기준은 변경하지 않았다. 후보 wheel은 전역 설치와 분리해 검증한다.

## 실제 조회 근거

원본 고3 영어 4쪽 제목의 subset `ArialBlack`과 설치된 `C:/Windows/Fonts/ariblk.ttf`는 검증한 글자들의 advance가 일치한다. 설치 폰트의 legacy family/name1은 `Arial Black`, typographic family/name16은 `Arial`, subfamily/name17은 `Black`, intrinsic weight는 900이다. source의 bold=false는 이 무거운 face를 보통 Arial400으로 바꾸라는 뜻이 아니다.

| 조회 | fontdb 0.23 | Windows Skia 0.97.2 |
| --- | --- | --- |
| `Arial Black`, normal400 | 미발견 | 미발견 |
| `Arial Black`, weight900 | 미발견 | 미발견 |
| `Arial`, normal400 | ArialMT400 | ArialMT400 |
| `Arial`, 명시 bold700 | Arial-BoldMT700 | Arial-BoldMT700 |
| `Arial`, weight900 | Arial-Black900 | Arial-Black900 |
| 현재 fallback chain의 첫 지원 face | PDF 경로는 MalgunGothic400 | PNG 경로와 같은 chain의 `R`은 Noto-Sans-KR400 |

Windows probe는 실제 Windows에서 system `FontMgr`의 335개 family를 사용했다. renderer의 `FontMgr::default()`는 같은 `FontMgr::new()`로 이어진다. `skia/text_replay.rs`와 같은 family 순서 및 normal style을 사용하고, 실제 `unichar_to_glyph('R')`가 0이 아닌 첫 face를 찾았다. Noto face 선택은 눈으로 얇아 보인다는 추측과 구별되는 직접 조회 결과다. document/font path 옵션에서 custom face를 따로 제공하는 경우는 이 기본 경로의 결론에 포함하지 않는다.

독립 Rust fontdb에서는 설치된 Arial regular/bold/black와 Malgun Gothic 파일을 읽었다. **증명된 Arial-Black face에만** legacy name1 alias를 scratch 등록하니 `Arial Black` normal query가 intrinsic900 face를 골랐고, 일반 `Arial` normal query는 계속 ArialMT400을 골랐다. 단순히 unresolved family의 weight를 900으로 바꾸는 것으로는 fontdb의 이름 미발견이 해결되지 않았다.

증거:

- `tmp/september-font-probe/fontdb-query-probe.json`, `fontdb-query-probe.log`, `src/main.rs`: offline Rust fontdb query, exit0.
- `tmp/september-font-probe/windows-skia-query-probe.json`, `windows-skia/build.log`, `windows-skia/src/main.rs`: Windows Skia 실제 family/style/glyph 조회, build/실행 exit0.
- `tmp/september-audit/high3-font-alias-current/pdf-painted-title-fonts-exact.json`: 실제 PDF title glyph 66개의 MalgunGothic 선택.
- `english-source-frame-font-diagnostics.md`: source subset/설치 font 및 가변 advance의 별도 증거.

## 좁은 후보

기존 요청 family/style 조회가 성공하면 그 결과를 그대로 쓴다. **조회가 실패한 경우에만**, 실제 로드된 face의 legacy name1 또는 정확한 PostScript name이 요청 이름과 대응하는지 확인하는 보조 lookup을 후보로 삼는다. 공백·하이픈 제거와 대소문자 정규화는 qualified 정확 대응에만 쓰고, `Black` 포함 여부·유사 이름·파일명으로 family나 weight를 추측하지 않는다.

같은 실제 face를 가리키는 alias를 만들거나 그 face 자체를 paint에 전달한다. name16=`Arial` 및 intrinsic900인 실제 Arial-Black face를 찾는 것이 이번 예의 결과이며, 제품에 Arial Black 전용 weight900 규칙을 하드코딩하는 제안은 아니다. 서로 다른 face가 같은 정규화 이름에 걸리면 임의 선택하지 않고 기존 fallback을 유지한다. italic 등의 style 조건과 글자 지원도 확인한다. 실제 지원하지 않는 한글은 기존 글자별 fallback을 유지한다.

Skia에서는 resolved `Typeface`를 기존 후보 chain 앞에 넣는 작은 경로, fontdb에서는 실제 face에 legacy alias를 보존하는 load/resolver 경로를 검토할 수 있다. layout metric table·HWPX 글자 폭·문단 wrap·원문 bold 속성을 변경하지 않고 painting의 실제 face 선택만 바로잡는 범위를 우선 검증한다.

## 필수 회귀와 배포 검증

- 일반 Arial400→ArialMT, 명시 bold700→Arial-BoldMT의 기존 결과·폭·painting을 보존한다. 성공한 기존 query에는 새 경로를 적용하지 않는다.
- Blackadder ITC, 무관한 Black 이름, 존재하지 않는 family, 모호한 alias, 맞지 않는 italic, 잘못된 PostScript suffix는 기존 lookup/fallback을 유지한다.
- 이번 실제 source title 66glyph는 source와 같은 face/outline 및 advance를 사용하는지 확인한다. PNG와 PDF의 선택 face·glyph·페이지 geometry를 각각 검증하며, 한 backend 결과를 다른 backend의 증거로 사용하지 않는다. 전체 품질 98 도달 여부는 새 frozen matrix로 판정한다.
- 혼합 한글/영문·일반 수학·실제 공백과 punctuation·편집 후 wrap/growth/reopen 회귀를 유지한다. source XML·원문 문자·그림 자산이 달라지지 않는지 확인한다.
- renderer 변경은 새 native binary/wheel을 빌드해야 반영된다. 공통 upstream revision/patch/lock과 빌드 provenance를 Windows·macOS 패키징에서 동일하게 관리하고 설치된 binary hash까지 검증해야 한다. 앱의 이름 정규화 한 줄만으로 painting lookup 문제까지 해결됐다고 표시하지 않는다.
- macOS는 CoreText/Skia의 실제 family 등록, 설치 폰트와 intrinsic weight, fontdb의 로드 목록 및 arm64/x86_64 wheel을 **실제 Mac에서** 검증해야 한다. 현재 Mac runtime은 없으며 Windows query 성공을 Mac 검증으로 취급하지 않는다. 설치 가능성·품질 동등성·패키징 검증은 `macos-readiness.md`의 단계 구분을 유지한다.

## Windows 후보 구현

기존 family/style 조회가 실패할 때만 실제 로드된 face의 name1/name6를 검사하는 공통 resolver를 추가했다. ASCII 공백·하이픈 제거 및 대소문자 정규화 후 정확히 대응하는 face가 유일해야 하며, 실제 width/slant와 요청 조건을 확인한다. normal400 요청이 특정 무거운 face의 이름을 직접 지정하면 그 face의 intrinsic weight를 유지한다. 명시 bold에는 실제 굵은 face가 필요하다. Arial 전용 weight 규칙이나 synthetic bold는 없다.

Skia는 실제 `Typeface`의 name table/style을 읽고 기존 조회 실패 때 그 face 자체를 사용한다. fontdb는 실제 로드 파일과 face index를 확인하며, 동일 파일의 중복 로드는 하나로 취급한다. PDF resolver는 CSS family 순서를 유지한다. 복구한 face가 특정 글자를 지원하지 않으면 alias 복구 전에 선택됐을 기존 face와 기존 fallback selector를 사용한다. 같은 alias에 서로 다른 기존 fallback chain이 충돌하면 alias 선택을 포기한다. default-ignorable shaping은 변경하지 않는다.

최초 후보에서 한글만 지정한 문서의 PDF fallback이 MalgunGothic에서 Batang으로 바뀌는 negative를 재현했다. 이를 위의 기존 fallback 보존 경로로 수정하며, 성공한 일반 family 조회와 무관한 fallback을 바꾸지 않는 회귀를 함께 둔다. 최초 후보·실패 로그는 scratch에 보존한다.

최종 `0.7.0+nativecell2` 후보는 분리 설치에서 11개 실제 backend 사례와 22개 검사를 통과했다. 순수 한글의 PNG pixels와 PDF font·glyph bounds가 기존과 동일하고, 혼합 문서도 한글 face/bounds를 유지하면서 Latin만 실제 Arial-Black으로 복구한다. 일반 Arial400/bold700/italic, 미확인 이름·suffix/slant·Blackadder ITC는 동일 HWPX의 PNG pixels와 PDF 결과가 그대로다. 최종 PDF 변경 영향 회귀 6개도 모두 PASS다.

이 후보 wheel SHA-256은 `a4e36d7d27598796dff1d0f0d7f73e2ce66e18afa90c3809459c0c5eafe7117e`, 분리 설치 `_rhwp.pyd`는 `ae185d9f7e60cd92067e031906e242e071cc86dd4a75434962468450a76fb257`다. 전역 설치는 후보 검증 중 변경하지 않았다.

현재 증거 경로:

- `tmp/renderer-font-lookup/actual-windows-font-query.json`: 실제 Windows Skia/fontdb 조회. 일반 Arial400, Arial700, 알 수 없는 이름, italic 불일치 및 한글 glyph 미지원 조건을 검증한다.
- `tmp/renderer-font-lookup/unit-tests.log`: 임의의 Example Heavy face로 qualified exact, 스타일 불일치, 서로 다른 face의 모호성, 동일 identity 중복을 검사한다.
- `tmp/renderer-font-lookup/regression-report/report.json`: 최초 후보의 native/math/edit 회귀 14개 모두 PASS.
- `tmp/renderer-font-lookup/backend-final/report.json`, `final-regression-report/report.json`: 최종 fallback 보완 후보의 backend 11사례/22검사 및 PDF/native/math/edit 6게이트 PASS.
- `tmp/renderer-font-lookup/font1-final-patch-replay-proof.json`: 배포 패치를 upstream exact revision에 깨끗하게 적용한 소스와 실제 wheel 빌드 소스가 일치한다.
- `tmp/renderer-font-lookup/high3-height-edit/height-edit-summary.json`: 실제 고3 8p에서 446개 추가/기존 glyph의 bounds, 성장 후 9p 흐름, 다음 문항 이동 및 재열기 보존 PASS.
- `tmp/renderer-font-lookup/root-title-{old,candidate}/report.json` 및 최종 `root-title-font1-final/report.json`: 독립 원본 66glyph advance 차이 0, 기존 PDF MalgunGothic에서 실제 Arial-Black으로 복구, SVG bytes 동일. PNG의 2,452개 변경 픽셀은 제목 밴드 안에만 있고 밖은 0이다.

패치·wheel·lock·라이선스의 배포 provenance는 `packaging/renderer/manifest.json`으로 관리한다. 동일 upstream commit에 패치를 깨끗하게 적용한 파일이 실제 빌드 소스와 일치하는지 별도 검증한다. 후속 cell-SQUARE 변경은 이 폰트 후보와 분리한다.

## macOS 검증 범위

공통 Rust source patch와 Cargo.lock을 동일하게 적용하되 macOS arm64/x86_64용 native wheel은 Mac에서 각각 빌드해야 한다. Windows wheel은 macOS에서 사용할 수 없다. 새 lookup은 실제 font manager가 로드한 name table을 읽으므로 특정 Windows 폰트 경로나 Arial 파일명에 의존하지 않는다. 다만 CoreText가 같은 face를 먼저 성공적으로 조회하는지, name1/name6와 intrinsic style을 어떻게 노출하는지, 한글 fallback 및 PNG/PDF face가 일치하는지는 실제 설치 폰트와 Mac에서 검증해야 한다.

현재 실제 Mac runtime은 없으며 macOS 빌드·서명·배포·렌더 품질 동등성은 미검증이다. 같은 폰트를 임의로 번들하거나 Arial 대체 폰트를 같다고 간주하지 않는다. `macos-readiness.md`의 설치 가능성, 품질 동등성, 배포 검증 단계를 각각 충족해야 한다.
