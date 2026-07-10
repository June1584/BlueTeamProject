"""
[경보 상세 화면]
지도(view.py)에서 마커를 클릭했을 때 보여주는 상세 페이지.
상단 메뉴에는 노출하지 않고 view.py 안에서 세션 상태(view/selected_alert_id)로만 전환한다.

전체를 3:4:3 비율의 3칸으로 나눈다.
  왼쪽(3)   : 적군 자산 정보 카드. 경보수준·제목·변화요약·지역 + 탐지된 적군
              장비(equipment 테이블: 종류·위협도·설명) - 전부 DB 조회 결과.
  가운데(4) : 위성사진. [H-4]/[H-2]/[H-Hour] 버튼으로 시간을 고르면 그 사진
              한 장이 (result_image/ 폴더, 촬영 시각순 정렬) 컬럼 폭을 꽉 채운
              정사각형(원본 840x840과 동일 비율)으로 보인다.
  오른쪽(3) : 아군 자산 지도 (경보 지도와 같은 EO 배경 + 아군 자산 마커) + 그 아래
              마커를 클릭하면 나오는 정보 패널. 아군 자산은 strike_asset 테이블에서
              조회한다.
"""
import base64
from pathlib import Path
from typing import Optional

import streamlit as st
from streamlit_folium import st_folium

import service  # features/4/service.py


def _render_enemy_asset_card(alert: service.Alert) -> None:
    """왼쪽(3): 경보정보(레벨·제목·변화요약·지역) + 탐지된 적군 자산 정보를 세로로 보여준다."""
    level_label = service.marker_label(alert.alert_level)
    st.markdown(
        "  \n".join([
            f":{service.marker_color(alert.alert_level)}[**[{level_label}]**]",
            f"**{alert.title or '(제목 없음)'}**",
        ])
    )

    st.caption("변화 요약")
    st.write(alert.summary or "변화 요약 정보가 없습니다.")

    st.caption("지역")
    st.write(alert.region or "지역 정보가 없습니다.")

    st.markdown("<hr style='margin:4px 0 10px 0;' />", unsafe_allow_html=True)

    st.markdown("**적군 자산 정보**")
    asset_lines = [f"장비: {alert.asset_name or '정보 없음'}"]
    if alert.asset_category:
        asset_lines.append(f"종류: {alert.asset_category}")
    if alert.asset_threat_level is not None:
        asset_lines.append(f"위협도: {alert.asset_threat_level}")
    st.markdown("  \n".join(asset_lines))
    if alert.asset_description:
        st.caption(alert.asset_description)


def _image_data_uri(path: Path) -> str:
    """이미지 파일을 <img> 태그에 바로 쓸 수 있는 base64 data URI로 바꾼다."""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


# 사진 박스와 오른쪽 지도(st_folium)의 높이를 똑같은 값으로 맞춰서, 두 박스의
# 위/아래 끝이 나란히 정렬되도록 한다 (오른쪽 지도의 height=도 이 값을 그대로 쓴다).
_PHOTO_MAP_HEIGHT_PX = 480


def _render_image_slot(path: Optional[Path], height_px: int = _PHOTO_MAP_HEIGHT_PX) -> None:
    """이미지 한 장을 컬럼 폭에 꽉 채운 고정 높이 박스로 보여준다 (풀 스크린샷 느낌).

    높이를 오른쪽 지도와 같은 고정값(_PHOTO_MAP_HEIGHT_PX)으로 맞춰서 두 박스의
    세로 길이·아래쪽 끝이 서로 맞도록 했다. 사진이 840x840 정사각형이라 폭:높이
    비율이 박스와 정확히 같지 않을 수 있지만, object-fit: cover로 폭을 꽉 채운다.
    """
    if path is not None and path.exists():
        st.markdown(
            f'<div style="width:100%;height:{height_px}px;border-radius:4px;overflow:hidden;">'
            f'<img src="{_image_data_uri(path)}" '
            f'style="width:100%;height:100%;object-fit:cover;display:block;" />'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("이미지가 없습니다. (준비 중)")


# @st.fragment로 감싸서, 시간 버튼을 눌렀을 때 이 사진 영역만 다시 그리고
# 오른쪽 아군 자산 지도(전체 페이지 rerun 시 다시 로딩되던 부분)는 건드리지 않게 한다.
@st.fragment
def _render_alert_photos(alert_id: int) -> None:
    """[H-4]/[H-2]/[H-Hour] 중에서 고른 사진 한 장을 3분할이던 영역만큼 크게 보여준다."""
    images = service.get_alert_images(alert_id)
    labels = ["[H-4]", "[H-2]", "[H-Hour]"]

    state_key = f"photo_time_label_{alert_id}"
    if state_key not in st.session_state:
        st.session_state[state_key] = labels[0]

    # segmented_control은 선택 상태를 위젯 자체가 직접 관리해서, 버튼 방식처럼
    # "한 번 눌러야 상태만 바뀌고 색은 다음 클릭에야 반영되는" 딜레이가 없다.
    selected_label = st.segmented_control(
        "촬영 시각", labels, key=state_key,
    )
    selected_idx = labels.index(selected_label) if selected_label in labels else 0

    image_path = images[selected_idx] if selected_idx < len(images) else None
    _render_image_slot(image_path)


# 아군 자산 마커 클릭 좌표를 자산과 매칭할 때 쓰는 오차 허용치(도 단위, 약 100m).
_FRIENDLY_CLICK_TOLERANCE = 0.001


def _find_friendly_asset_by_click(lat: float, lng: float, assets: list) -> Optional["service.FriendlyAsset"]:
    """지도에서 클릭한 좌표와 가장 가까운(오차범위 내) 아군 자산을 찾는다."""
    for asset in assets:
        if abs(asset.latitude - lat) <= _FRIENDLY_CLICK_TOLERANCE and \
           abs(asset.longitude - lng) <= _FRIENDLY_CLICK_TOLERANCE:
            return asset
    return None


def _render_friendly_asset_map() -> None:
    """오른쪽 위: 경보 지도와 같은 EO 배경 위에 아군 타격 자산 마커를 찍은 미니 지도.
    바로 아래에는 마커를 클릭했을 때 정보를 보여주는 패널을 둔다. (strike_asset 테이블 조회)
    """
    st.caption("아군 자산 위치")
    # 왼쪽 사진 컬럼은 "촬영 시각" 라벨 + 시간 선택 버튼줄이 캡션 위에 하나 더 있어서,
    # 지도가 캡션 바로 아래에서 시작하면 사진 박스보다 위쪽 끝이 더 높아 보인다.
    # 버튼줄 높이만큼 빈 여백을 넣어서 사진 박스와 지도 박스의 위쪽 끝을 맞춘다.
    st.markdown("<div style='height:44px;'></div>", unsafe_allow_html=True)

    try:
        friendly_map = service.build_eo_map()
    except Exception as exc:
        st.error(f"아군 자산 지도 생성 실패: {exc}")
        return

    try:
        assets = service.get_strike_assets()
    except Exception as exc:
        st.error(f"아군 자산 조회 실패: {exc}")
        return

    for asset in assets:
        service.add_circle_marker(
            friendly_map, asset.latitude, asset.longitude,
            color=service.FRIENDLY_MARKER_COLOR,
            tooltip=f"{asset.asset_name} ({asset.name})",
        )

    # 왼쪽 사진 박스와 높이를 똑같이 맞춰서 아래쪽 끝도 나란히 정렬한다.
    map_key = f"friendly-map-{st.session_state.get('_map_reset_token', 0)}"
    map_data = st_folium(
        friendly_map, height=_PHOTO_MAP_HEIGHT_PX,
        use_container_width=True,
        returned_objects=["last_object_clicked"],
        key=map_key,
    )

    clicked = map_data.get("last_object_clicked") if map_data else None
    if clicked:
        matched = _find_friendly_asset_by_click(clicked["lat"], clicked["lng"], assets)
        if matched is not None:
            st.session_state["selected_friendly_asset"] = matched.asset_name

    # 클릭해서 선택한 자산 정보를 지도 바로 아래에 보여준다 (다른 페이지로 이동하지 않음).
    # st.write를 여러 번 쓰면 줄마다 여백이 붙어 세로로 길어지길래, 한 번의 markdown으로 합쳐서
    # 줄바꿈만 넣는 방식으로 줄였다 (스크롤 방지).
    selected_name = st.session_state.get("selected_friendly_asset")
    selected = next((a for a in assets if a.asset_name == selected_name), None)
    if selected is not None:
        info_lines = [
            "**선택한 아군 자산 정보**",
            f"부대: {selected.asset_name}",
            f"자산: {selected.name} ({selected.category})",
            f"사거리: {selected.range_km:.0f}km · 대응시간: {selected.response_time_min}분",
        ]
        if selected.location_name:
            info_lines.append(f"위치: {selected.location_name}")
        st.markdown("  \n".join(info_lines))
    else:
        st.markdown("**선택한 아군 자산 정보**")
        st.info("마커를 누르면 여기에 정보가 표시됩니다.")


def render_alert_detail_page() -> None:
    """경보 상세 페이지 전체를 그린다."""
    # 페이지 상단 여백을 줄여서 전체 내용을 위로 올린다 (제목을 없앤 만큼 빈 공간이 남지 않도록).
    # 너무 줄이면 Streamlit 상단 툴바에 "지도로 돌아가기" 버튼이 가려져서 3rem으로 둔다.
    st.markdown("<style>div.block-container{padding-top:3rem;}</style>", unsafe_allow_html=True)

    if st.button("← 지도로 돌아가기"):
        st.session_state["view"] = "map"
        # 지도 컴포넌트를 새로 만들도록 key를 바꿔, 이전 클릭 좌표가 남아있지 않게 한다.
        st.session_state["_map_reset_token"] = st.session_state.get("_map_reset_token", 0) + 1
        st.rerun()

    alert_id = st.session_state.get("selected_alert_id")
    alert = None
    if alert_id is not None:
        try:
            alert = service.get_alert_by_id(alert_id)
        except Exception as exc:
            st.error(f"경보 조회 실패: {exc}")
            return

    if alert is None:
        st.warning("선택된 경보가 없습니다. 지도에서 마커를 눌러주세요.")
        return

    enemy_col, photo_col, friendly_col = st.columns([3, 4, 3])

    with enemy_col:
        _render_enemy_asset_card(alert)

    with photo_col:
        _render_alert_photos(alert.alert_id)

    with friendly_col:
        _render_friendly_asset_map()
