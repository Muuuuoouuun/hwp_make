# Linux 개발·검증 환경 설치 결과

## 최종 갱신 및 로컬 검증 인계

아래 초기 설치 기록 이후 Linux 렌더러를 `0.7.0+nativecell1.fontcache1`로 빌드해
프로젝트 가상 환경에 설치했다. 최신 wheel 경로·SHA-256은
`packaging/renderer/manifest-linux.json`에 기록되어 있다. Windows wheel에는 글꼴 캐시를 적용하지 않았다.

Linux 글자 폭 보정 누락을 고쳐 기존 합성 배치 검사가 통과했고,
최종 전체 실행은 **137개 중 121 통과·13 미검증·3 실패**다.
실물 12종·104쪽의 문항 인식·가져오기는 380/380 일치하지만,
엄격 배치 점수 평균 **88.53**, 최저 **77.13**으로 목표 94/92에 미달한다.
추가 3월 영어 표본은 14번을 중복 인식해 45문항을 46문항으로 잡는다.
추가 표본 전체 변환과 정식 한컴·브라우저 검증은 사용자가 로컬에서 진행한다.

최종 근거는 `tmp/layout-improve-20261023/final-verification/report.json`,
`final-corpus/report.json`, `march-recognition.json`이며, 아래 장부는 초기 설치 당시의 기록이다.

## 초기 설치 기록

2026-10-23 KST. 환경 미설치 상태를 해결하기 위해 필요한 도구를 직접 설치하고,
저장소의 Windows 수정 렌더러와 같은 소스·패치를 Linux용으로 빌드했다.

| 구성 | 설치 결과 |
| --- | --- |
| Rust | 사용자 경로에 Rust 1.98.1·Cargo·rustup 설치 |
| Python 빌드 | 격리 환경에 maturin 1.15.0·patchelf 0.17.2.4 설치 |
| 글꼴 개발 파일 | Debian의 FreeType·fontconfig와 의존 패키지를 사용자 빌드 sysroot에 준비 |
| 수정 렌더러 | `rhwp-python 0.7.0+nativecell1`, 코어 0.7.13을 프로젝트 `.venv`와 검증용 venv에 설치 |
| 한국어 OCR | `pytesseract 0.3.13`·한국어 traineddata 설치. 기존 영어·방향 인식 모델도 유지 |

Linux wheel은 `tmp/renderer-linux-build/wheels/`에 보관한다. `manylinux_2_38_x86_64`
태그이며 Debian 13 x86_64 / Python 3.12.14에서 실검증했다. 다른 배포판과 Python 버전은
실검증하지 않았다. 이전 공식 wheel에서 필요했던 시스템 FreeType 강제 preload 없이
새 wheel을 로드하고 실제 SVG·PNG 렌더를 확인했다. 소스 커밋·패치·lock·wheel 해시는
[manifest-linux.json](../../../packaging/renderer/manifest-linux.json)에 기록했다.

빌드 방법은 [렌더러 README](../../../packaging/renderer/README.md)와
[Linux 재빌드 스크립트](../../../packaging/renderer/rebuild-linux.sh)에 남겼다.
Windows 배포 wheel은 교체하지 않았다. Linux wheel은 저장소·외부 서비스에 배포하지 않았다.

## 실제 검증

렌더 회귀 6개가 **6 통과·0 미검증·0 실패**다. 검사기의 기준이나 누락 검출 조건은 바꾸지 않았다.

- 원본 배경과 셀 배경의 실제 표시, 페이지 밖으로 숨긴 배경 거부.
- 표 셀 안의 중첩 글상자·라벨 교체·편집·재저장과 개체 표시 문자 비노출.
- 실물 6월 고1 수학 14번의 문단 추가 편집, 수식 192개와 빈칸 8개 보존.
- 실물 영어 안내문의 158~790자 추가 편집·재저장, 장식 프레임·본문의 겹침 검사.
- 라벨 소속·프레임·글자 유실 변이 검출과 잘못된 원본 입력 거부.

실물 수학·영어 표본은 앞서 내려받은 공개 6월 시험지와 SHA-256을 대조한 뒤 기존
회귀 스크립트의 예상 경로에 연결했다. 원본은 교체하지 않았다. 공식 렌더러에서는
이 실물 검사 2개가 실패했고, 같은 표본의 수정 렌더러에서는 통과했다.

한국어 OCR 실동작 시험에서 자동 페이지 배치가 짧고 넓은 문단을 빈 결과로 처리하는
문제를 확인했다. 빈 결과일 때만 문단 모드로 재시도하고 각 외부 OCR 실행에 30초
상한을 추가했다. 실제 한국어 3줄의 모든 글자를 공백 정규화 후 대조하고 이미지
가져오기·저장까지 확인했다. 빈 이미지와 OCR 실패 처리도 통과했다.
이 합성 표본 통과는 일반 스캔 시험지의 인식률 100%를 뜻하지 않는다.

설치 후 프로젝트 `.venv`의 관련 검사 6개는 **5 통과·0 미검증·1 실패**다.
OCR·SVG/PNG 미리보기·PDF 캐시·프레임 판별·저장/보안/동시성은 통과했고,
기존 `verify_pdf_layout_fidelity_suite.py`의 세 가지 전경 겹침 실패는 남았다.
이전 전체 실행과 필요한 재검증을 합산한 최신 장부는 136개 중 115 통과·18 미검증·3 실패이며,
최종 코드·설치 환경에서 전체 136개를 다시 실행한 결과는 아니다.

근거 파일은 저장소의 `tmp/renderer-linux-build/`에 있다:

- `patched-verification/report.json`: 렌더 회귀 6개 결과.
- `official-real-fixtures/report.json`: 같은 실물 표본의 공식 렌더러 실패 재현.
- `installed-verification/report.json`: 프로젝트 환경 설치 후 관련 회귀 결과.
- `korean-ocr-final.log`, `image-import-ocr.json`: 실제 OCR와 이미지 가져오기 결과.
- `fixtures.json`, `build-retry.log`: 표본 해시와 최종 빌드 기록.

OCR 모델은 `~/.local/share/hwp-make/tessdata`에 설치했다. 사용자 경로의 `tesseract`
실행 래퍼가 이 모델을 기본으로 사용하고, 사용자가 설정한 `TESSDATA_PREFIX`는 존중한다.
시스템 tesseract 실행 파일이나 시스템 글꼴 라이브러리를 교체하지 않았다.

## 남은 판정

Linux에서의 개발·렌더 검증은 환경 부재로 막히지 않는다. 한컴 공식 다운로드 센터에서
확인한 최신 데스크톱 설치본은 Windows 11 이상을 요구하며 구매자용 다운로드에는
로그인이 필요하다. 정식 한컴 편집기는 이 Linux 환경에 설치·실행하지 않았다.
현재 검사는 오픈소스 엔진과 문서 API의 편집·재저장 검증이며, 한컴 자체의 편집·재저장은 별도다.

94점 이상·최저 92점 목표는 아직 달성 판정하지 않는다. 원본 배치·그림·문단 복원과
정식 한컴 호환성 검증이 남았고, 이번 렌더러 설치 후 12종 전체 품질 점수는 다시 측정하지 않았다.

공식 설치 조건 근거:
[한컴 다운로드 센터](https://www.hancom.com/support/downloadCenter/download),
[한컴오피스 뷰어](https://www.hancom.com/product/office/officeViewer).
