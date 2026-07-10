"""
[경보 지도 - 서비스]
alert_id로 조회되는 경보 세션(위치정보·적군자산·경보수준 등)을 실제 DB(satellite_intel)에서
조회해 지도에 필요한 값(위도·경도·경보수준·제목·변화요약·지역)으로 정리하는 함수 모음.

연결 경로 (FK):
  alert.change_id -> change_event.change_id
  change_event.current_image_id -> image_analysis.image_id
  image_analysis.region_id -> region.region_id   (위도·경도는 region 테이블에 있다)
  change_event.equipment_id -> equipment.equipment_id (적군자산 이름)

위성사진은 image_analysis.original_image_path/result_image_path에 아직 실제 경로가
채워져 있지 않아, 우선 프로젝트 루트의 result_image/ 폴더에 있는 사진을 대신 사용한다.
파일명 끝의 HHMMSS(예: 100000 -> 10:00:00)를 촬영 시각으로 보고 시간순 정렬한다.

지도(EO 위성 배경) 생성 로직은 view.py·detail_view.py가 똑같이 쓰므로 build_eo_map()
하나로 공용화했다. 아군 자산은 아직 DB에 friendly_asset류 테이블이 없어 목업으로 둔다.
"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import ee
import folium
from sqlalchemy import text

from shared.database import get_engine

_DB = "satellite_intel"

# DB에 저장된 alert_level(enum) 값 -> 화면 표시용 한글/색상 매핑
ALERT_LEVEL_LABELS = {
    "URGENT": "긴급",
    "IMPORTANT": "중요",
    "NOTICE": "특이",
}
ALERT_LEVEL_COLORS = {
    "URGENT": "red",
    "IMPORTANT": "orange",
    "NOTICE": "blue",
}
DEFAULT_MARKER_COLOR = "gray"  # 알 수 없는 경보수준이 들어와도 지도가 깨지지 않도록

# 지도에는 전체 경보 이력이 아니라, 가장 최근에 생성된 경보 1건만 표시한다.
# (예: alert 테이블에 행이 16개 있어도 그중 가장 최신 1개만 가져온다.)
MAX_ALERTS_ON_MAP = 1

# 위성사진이 들어있는 폴더 (프로젝트 루트 바로 아래 result_image/).
# 지금은 alert_id별로 나뉘어 있지 않고, 이 폴더 안 사진을 공통으로 보여준다.
IMAGE_ROOT_DIR = Path(__file__).resolve().parents[2] / "result_image"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
MAX_IMAGES_PER_ALERT = 3

# 파일명 끝의 "HHMMSS.확장자" 부분에서 시각을 뽑아내는 정규식.
# 예: "425-1_개풍군_1_EO_2023-12-30 100000.png" -> "100000" (10:00:00)
_TIME_SUFFIX_RE = re.compile(r"(\d{6})\.\w+$")


def _image_time_key(path: Path) -> str:
    """정렬용 키: 파일명 끝의 HHMMSS. 못 찾으면 파일명 그대로를 키로 쓴다."""
    match = _TIME_SUFFIX_RE.search(path.name)
    return match.group(1) if match else path.name


def image_time_label(path: Path) -> str:
    """파일명 끝의 HHMMSS를 'HH:MM' 표시용 라벨로 바꾼다 (못 찾으면 파일명)."""
    match = _TIME_SUFFIX_RE.search(path.name)
    if not match:
        return path.stem
    hhmmss = match.group(1)
    return f"{hhmmss[0:2]}:{hhmmss[2:4]}"

# alert -> change_event -> image_analysis -> region / equipment 순서로 조인해
# 지도에 필요한 값을 한 번에 가져온다. region_id가 없는 image는 자동으로 제외된다.
_ALERT_QUERY = f"""
    SELECT
        a.alert_id, a.alert_level, a.title, a.message,
        eq.class_name,
        r.region_name, r.latitude, r.longitude
    FROM `{_DB}`.`alert` a
    JOIN `{_DB}`.`change_event` ce ON a.change_id = ce.change_id
    JOIN `{_DB}`.`image_analysis` ia ON ce.current_image_id = ia.image_id
    JOIN `{_DB}`.`region` r ON ia.region_id = r.region_id
    JOIN `{_DB}`.`equipment` eq ON ce.equipment_id = eq.equipment_id
"""


@dataclass
class Alert:
    """alert_id 세션 하나를 담은 것 (위치정보·적군자산·경보수준·제목 등)."""
    alert_id: int
    latitude: float
    longitude: float
    alert_level: str       # DB enum 원본값 (URGENT/IMPORTANT/NOTICE)
    asset_name: str = ""   # 적군자산(장비) 이름
    title: str = ""        # 경보제목
    summary: str = ""      # 변화요약(경보 발생 근거)
    region: str = ""       # 지역


def _row_to_alert(row) -> Alert:
    m = dict(row._mapping)
    return Alert(
        alert_id=m["alert_id"],
        latitude=float(m["latitude"]),
        longitude=float(m["longitude"]),
        alert_level=m["alert_level"],
        asset_name=m["class_name"] or "",
        title=m["title"] or "",
        summary=m["message"] or "",
        region=m["region_name"] or "",
    )


def get_alerts(limit: int = MAX_ALERTS_ON_MAP) -> List[Alert]:
    """지도에 표시할 경보 목록을 DB에서 최신순으로 limit개만 조회한다."""
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(_ALERT_QUERY + " ORDER BY a.created_at DESC LIMIT :limit"),
            {"limit": limit},
        )
        return [_row_to_alert(row) for row in rows]


def get_alert_by_id(alert_id: int) -> Optional[Alert]:
    """alert_id 하나에 해당하는 경보를 DB에서 조회한다 (없으면 None)."""
    with get_engine().connect() as conn:
        row = conn.execute(
            text(_ALERT_QUERY + " WHERE a.alert_id = :alert_id"),
            {"alert_id": alert_id},
        ).fetchone()
    return _row_to_alert(row) if row else None


def get_alert_images(alert_id: int) -> List[Path]:
    """result_image/ 폴더의 위성사진을 촬영 시각(파일명 끝 HHMMSS)순으로 최대 3장 찾는다.

    실제 위성사진 경로(image_analysis.original_image_path)는 아직 DB에 채워져 있지
    않고, alert_id별 폴더 구분도 없어서 지금은 이 공용 폴더를 그대로 사용한다.
    (alert_id는 나중에 alert별 폴더가 생기면 쓸 수 있도록 인자만 남겨둔다.)
    """
    if not IMAGE_ROOT_DIR.is_dir():
        return []
    images = sorted(
        (p for p in IMAGE_ROOT_DIR.iterdir()
         if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS),
        key=_image_time_key,
    )
    return images[:MAX_IMAGES_PER_ALERT]


def marker_color(alert_level: str) -> str:
    """경보수준(enum) 문자열을 folium 마커 색상 이름으로 바꾼다."""
    return ALERT_LEVEL_COLORS.get(alert_level, DEFAULT_MARKER_COLOR)


def marker_label(alert_level: str) -> str:
    """경보수준(enum) 문자열을 화면 표시용 한글(긴급/중요/특이)로 바꾼다."""
    return ALERT_LEVEL_LABELS.get(alert_level, alert_level)


# =====================================================================
# EO 위성 배경 지도 (경보 지도 화면·경보 상세 화면 공용)
# =====================================================================

def _add_ee_layer(self, ee_image_object, vis_params, name):
    """geemap 없이 Folium에 Earth Engine 레이어를 추가하는 함수 (folium.Map에 매서드로 붙인다)."""
    map_id_dict = ee.Image(ee_image_object).getMapId(vis_params)
    folium.raster_layers.TileLayer(
        tiles=map_id_dict['tile_fetcher'].url_format,
        attr='Google Earth Engine',
        name=name,
        overlay=True,
        control=True,
    ).add_to(self)


folium.Map.add_ee_layer = _add_ee_layer


def build_eo_map(location=(36.5, 127.5), zoom_start: int = 7) -> folium.Map:
    """한반도 Sentinel-2 EO 레이어가 깔린 기본 지도를 만든다 (지도·상세 화면 공용)."""
    # GEE 초기화 (인증 안 되어있으면 터미널에 링크 뜸)
    try:
        ee.Initialize(project='project-501908')
    except Exception:
        ee.Authenticate()
        ee.Initialize(project='project-501908')

    m = folium.Map(location=list(location), zoom_start=zoom_start)

    dataset = ee.ImageCollection('COPERNICUS/S2_SR') \
                  .filterBounds(ee.Geometry.Point([location[1], location[0]])) \
                  .filterDate('2023-01-01', '2023-12-31') \
                  .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10)) \
                  .median()
    vis_params = {'bands': ['B4', 'B3', 'B2'], 'min': 0, 'max': 3000}
    m.add_ee_layer(dataset, vis_params, 'Sentinel-2 (True Color)')
    folium.LayerControl(collapsed=False).add_to(m)
    return m


# =====================================================================
# 아군 자산 (목업) - DB에 friendly_asset류 테이블이 아직 없어 임시로 둔다.
# 나중에 실제 테이블이 생기면 get_mock_friendly_assets()만 DB 조회로 바꾸면 된다.
# =====================================================================

FRIENDLY_MARKER_COLOR = "cadetblue"
FRIENDLY_MARKER_ICON = "flag"


@dataclass
class FriendlyAsset:
    """아군 자산 하나 (이름·종류·위치)."""
    name: str
    asset_type: str
    latitude: float
    longitude: float


def get_mock_friendly_assets() -> List[FriendlyAsset]:
    """아군 자산 목업 목록. 실제 friendly_asset 테이블이 생기면 DB 조회로 교체한다."""
    return [
        FriendlyAsset("제1군단 사령부", "지휘소", 37.90, 127.20),
        FriendlyAsset("아군 기갑여단", "기갑부대", 38.05, 127.05),
        FriendlyAsset("해군 2함대", "함대", 36.95, 126.60),
    ]
