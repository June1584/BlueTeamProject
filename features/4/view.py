import sys
from pathlib import Path

import streamlit as st

# 이 페이지는 나중에 여러 컬럼(정보/사진/지도)을 나란히 써서 넓은 화면이 필요하다.
# app.py의 멀티페이지 내비게이션에 아직 안 붙어있어 독립 실행되므로 여기서 직접 설정한다.
try:
    st.set_page_config(layout="wide")
except Exception:
    pass  # 이미 다른 곳에서 설정된 경우(추후 app.py에 편입 시) 조용히 넘어간다.

from streamlit_folium import st_folium

# "features.4"는 폴더명이 숫자로 시작해 파이썬 패키지 경로로 import할 수 없다.
# 그래서 같은 폴더를 sys.path에 직접 넣고 파일명으로 불러온다.
_THIS_DIR = Path(__file__).resolve().parent
# service.py가 project root의 shared/ 패키지(shared.database 등)를 쓰는데,
# pip로 설치된 동명의 "shared" 패키지가 site-packages에 있으면 그게 먼저 잡힐 수 있다.
# project root를 sys.path 맨 앞에 넣어 우리 shared/ 폴더가 우선하도록 한다.
sys.path.insert(0, str(_THIS_DIR.parents[1]))  # project root (BlueTeamProject)
sys.path.insert(0, str(_THIS_DIR))             # features/4
import service       # features/4/service.py: 경보 DB 조회 + EO 지도 + 마커 색상
import detail_view   # features/4/detail_view.py: 마커 클릭 시 보여줄 상세 화면

# 마커 클릭으로 어느 경보 좌표를 눌렀는지 판별할 때 쓰는 오차 허용치(도 단위, 약 100m).
_CLICK_MATCH_TOLERANCE = 0.001


def _find_alert_by_click(lat: float, lng: float, alerts: list) -> "service.Alert | None":
    """지도에서 클릭된 좌표와 가장 가까운(오차범위 내) 경보를 찾는다."""
    for alert in alerts:
        if abs(alert.latitude - lat) <= _CLICK_MATCH_TOLERANCE and \
           abs(alert.longitude - lng) <= _CLICK_MATCH_TOLERANCE:
            return alert
    return None


def render_map_view() -> None:
    """한반도 위성사진 + 경보 마커 지도를 그린다. 마커를 누르면 상세 화면으로 전환한다."""
    st.title("지휘관 페이지")

    try:
        m = service.build_eo_map()
    except Exception as exc:
        st.error(f"위성 지도 생성 실패: {exc}")
        return

    # 경보(alert_id) 목록을 DB에서 조회해 지도에 마커로 표시.
    # 색은 경보수준(긴급/중요/특이)에 따라 다르게 찍는다.
    try:
        alerts = service.get_alerts()
    except Exception as exc:
        st.error(f"경보 조회 실패: {exc}")
        alerts = []

    for alert in alerts:
        level_label = service.marker_label(alert.alert_level)
        service.add_circle_marker(
            m, alert.latitude, alert.longitude,
            color=service.marker_color(alert.alert_level),
            tooltip=f"[{level_label}] {alert.asset_name}",
        )

    st.caption("마커 색상: 🔴 긴급 · 🟠 중요 · 🔵 특이 (마커를 누르면 상세 화면으로 이동)")

    # 상세 화면에서 돌아올 때마다 key를 바꿔 지도 컴포넌트를 새로 만든다.
    # (같은 key를 계속 쓰면 이전 클릭 좌표를 계속 기억하고 있어서, 같은 마커를
    #  다시 눌러도 "새 클릭"으로 인식하지 못하는 문제가 있었다.)
    map_key = f"alert-map-{st.session_state.get('_map_reset_token', 0)}"
    map_data = st_folium(
        m, height=650,
        use_container_width=True,
        returned_objects=["last_object_clicked"],
        key=map_key,
    )

    clicked = map_data.get("last_object_clicked") if map_data else None
    if clicked:
        matched = _find_alert_by_click(clicked["lat"], clicked["lng"], alerts)
        if matched is not None:
            st.session_state["selected_alert_id"] = matched.alert_id
            st.session_state["view"] = "detail"
            st.rerun()


# 상단 메뉴에는 노출하지 않는 숨겨진 화면 전환: 기본은 지도, 마커 클릭 시 상세로 바뀐다.
if st.session_state.get("view") == "detail":
    detail_view.render_alert_detail_page()
else:
    render_map_view()
