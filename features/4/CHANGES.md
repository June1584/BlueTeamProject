# 경보 상세 화면 (features/4) 작업 정리

청출어람 프로젝트의 "한반도 EO 위성 지도 → 경보 상세" 기능 구현 내역 정리.

## 파일 구성

- `features/4/service.py` — DB 조회 · EO 지도 생성 등 로직 모음 (지도/상세 화면 공용)
- `features/4/view.py` — 한반도 위성 지도 화면 (독립 실행 진입점, 상단 메뉴에는 노출 안 됨)
- `features/4/detail_view.py` — 마커 클릭 시 나오는 경보 상세 화면

## 1. 지도 화면 (view.py)

- Google Earth Engine(Sentinel-2 true color) 배경 위에, DB `alert` 테이블에서 조회한 **가장 최신 경보 1건**만 마커로 표시.
- 마커 색상은 경보수준(`alert_level`)에 따라 다름: 🔴 긴급(URGENT) · 🟠 중요(IMPORTANT) · 🔵 특이(NOTICE).
- 마커에는 툴팁만 있고 팝업(클릭 시 텍스트박스)은 없음.
- 마커를 클릭하면 `st.session_state["view"] = "detail"`로 전환되어 상세 화면으로 이동. 상단 내비게이션 메뉴에는 노출되지 않는 "숨겨진" 페이지.
- 상세 화면에서 "← 지도로 돌아가기"를 누르면 지도 컴포넌트의 `key`를 바꿔(`_map_reset_token` 증가) 다시 그리므로, 같은 마커를 재클릭해도 정상적으로 상세 화면 전환이 동작함 (이전엔 좌표 기반 dedup 로직 때문에 재클릭이 씹히는 버그가 있었음 → 수정).
- `st.set_page_config(layout="wide")`, 지도 `use_container_width=True`로 폭 전체 사용.

## 2. 경보 상세 화면 (detail_view.py)

### 레이아웃 (최종본)

페이지를 **3 : 4 : 3** 비율의 3칸으로 분할:

| 왼쪽 (3) | 가운데 (4) | 오른쪽 (3) |
|---|---|---|
| 적군 자산 정보 카드 | 위성사진 (시간 선택) | 아군 자산 위치 지도 |

- 상단 제목("경보 상세")과 `alert_id` 캡션은 최종적으로 제거 (화면 위 여백을 줄이기 위해).
- 페이지 상단 padding은 CSS로 축소하되, Streamlit 툴바에 "← 지도로 돌아가기" 버튼이 가리지 않도록 `3rem` 정도 유지.

### 왼쪽 (3) — 적군 자산 정보

- `alert` + `change_event` + `image_analysis` + `region` + `equipment` 조인 결과(`service.Alert`)를 그대로 사용.
- 표시 항목: 경보수준(색상 뱃지) · 제목 · 변화 요약(`alert.message`) · 지역(`region.region_name`) · 적군 장비 정보(`equipment.class_name` / `category` / `threat_level` / `description`).
- 원래는 페이지 상단에 가로 한 줄(경보정보 · 변화요약 · 지역)로 배치했다가, 3:4:3 레이아웃으로 바뀌면서 왼쪽 세로 카드 형태로 이동.

### 가운데 (4) — 위성사진

- 시간 선택 UI: `[H-4] / [H-2] / [H-Hour]` 3개 버튼 (처음엔 실제 시각 "10:00/12:00/14:00" 라벨이었다가 요청으로 상대 시간 라벨로 변경).
  - `st.button` 3개로 직접 만들었다가 "한 번 눌러야 색이 다음 클릭에야 반영되는" 딜레이 버그가 있어서 `st.segmented_control`로 교체 (위젯이 선택 상태를 직접 관리해서 즉시 반영됨).
  - `@st.fragment`로 감싸서, 시간 버튼을 눌러도 오른쪽 지도(전체 rerun 시 매번 새로 로딩되던 EO 지도)는 다시 그려지지 않도록 함 — 버튼 클릭 시 지도가 로딩 스피너 뜨는 문제 해결.
- 사진은 원본이 정확히 **840×840 정사각형**이라, 여러 차례 시행착오 끝에 다음 방식으로 정착:
  - `st.image(width=...)` → 정사각형이 늘어나며 세로가 너무 커져 스크롤 발생 → 실패
  - `object-fit: cover` (고정 높이, 폭 100%) → 좌우/상하가 부자연스럽게 잘림 → 실패
  - `object-fit: contain` (정사각형 유지, 레터박스) → 잘리진 않지만 좌우에 빈 여백(검은 바) 생김 → "풀 스크린샷 느낌"이 아니라서 반려
  - **최종**: 로컬 이미지 파일을 base64 data URI로 인코딩해 `<img>` 태그로 직접 렌더링. 박스 높이를 오른쪽 지도와 **동일한 고정값(480px)** 으로 맞추고 `object-fit: cover`로 폭을 꽉 채움. 오른쪽 지도 캡션 아래에 44px 여백을 넣어서 사진 박스와 지도 박스의 위/아래 끝이 나란히 정렬되도록 함.

### 오른쪽 (3) — 아군 자산 위치

- 왼쪽 지도와 동일한 EO 배경(`build_eo_map()` 공용 함수) 위에, **`strike_asset` DB 테이블**(실제 아군 타격 자산: F-15K, K9A1, 천무 등)을 조회해 마커로 표시.
  - 처음엔 목업 데이터(3개 가짜 부대)로 틀만 만들었다가, `satellite_intel_strike_asset.sql` 스키마를 참고해 실제 DB 조회로 교체.
- 마커를 클릭하면 페이지 이동 없이 지도 바로 아래 정보 패널에 부대명 · 자산명 · 종류 · 사거리 · 대응시간 · 위치를 표시.
- 지도 높이는 왼쪽 사진 박스와 동일한 480px로 통일.

## 3. service.py — DB 연동 정리

### 경보(Alert) 조회

FK 체인: `alert.change_id → change_event.change_id`, `change_event.current_image_id → image_analysis.image_id`, `image_analysis.region_id → region.region_id` (위도·경도), `change_event.equipment_id → equipment.equipment_id` (적군 장비).

- `get_alerts(limit=1)` — 지도에 표시할 **가장 최신 경보 1건**만 조회 (`ORDER BY created_at DESC LIMIT 1`).
- `get_alert_by_id(alert_id)` — 상세 화면용 단건 조회.
- `Alert` dataclass에 적군 장비 관련 필드(`asset_category`, `asset_threat_level`, `asset_description`)를 추가해 `equipment` 테이블 정보까지 함께 반환.

### 위성사진 조회

- `get_alert_images(alert_id)` — **`alert → change_event → image_analysis`** 조인으로, `current_image`와 같은 지역(`region_id`)에서 촬영된 사진들 중 `result_image_path`가 채워진 것만 최신 3장(2시간 간격 = H-4/H-2/H-Hour)을 가져옴.
  - 다만 현재 시드 데이터의 `change_event`는 아직 실제 사진(`image_id` 8199번대)에 연결되어 있지 않아서, DB 조회 결과가 0건이면 프로젝트 루트 `result_image/` 폴더를 직접 스캔하는 방식으로 **자동 대체(fallback)** 하도록 처리. (`change_event`가 실제 사진에 연결되면 자동으로 DB 조회 경로를 타게 됨)
  - `image_time_label(path)` — 파일명 끝 `HHMMSS`를 `HH:MM` 라벨로 변환.

### EO 배경 지도

- `build_eo_map()` — Sentinel-2(`COPERNICUS/S2_SR`) true color 레이어를 올린 folium 지도 생성 함수. 지도 화면과 상세 화면(아군 자산 지도) 양쪽에서 공용으로 사용.
- Leaflet의 레이어 선택 팝업(`folium.LayerControl`)은 불필요한 UI라 제거.

### 아군 타격 자산

- `get_strike_assets()` — `strike_asset` 테이블 조회 (`asset_name`, `name`, `category`, `range_km`, `response_time_min`, `notes`, `location_name`, `latitude`, `longitude`).

## 4. 알려진 이슈 / 후속 작업

- 현재 seed된 `alert` 1~16번은 `change_event.previous_image_id / current_image_id`가 대량 생성된 더미 `image_analysis` row(빈 경로)를 가리키고 있어서, 실제 사진(8199번대)과는 DB상 연결이 안 되어 있음. 지금은 폴더 스캔 fallback으로 데모가 동작하지만, **`change_event`가 실제 이미지에 연결되면** 코드 수정 없이 자동으로 DB 조회 결과를 사용하게 됨.
- 환경 이슈: 로컬에 Python 인터프리터가 여러 개(`miniconda3\envs\streamlit`, `Python312`) 있어서 패키지 설치 시 실제 실행되는 인터프리터를 확인하고 설치해야 함.
