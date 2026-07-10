"""
[경보 상세 화면]
지도(view.py)에서 마커를 클릭했을 때 보여주는 상세 페이지.
상단 메뉴에는 노출하지 않고 view.py 안에서 세션 상태(view/selected_alert_id)로만 전환한다.

3칸으로 나눈다.
  왼쪽   : 경보 정보 카드 (알림종류·경보제목·변화요약·지역) - DB 조회 결과.
  가운데 : 위성사진 3장. 10:00·12:00은 작은 썸네일 2개로, 가장 최근인 14:00은
           그 아래에 크게 보여준다 (result_image/ 폴더, 촬영 시각순 정렬).
  오른쪽 : 아군 자산 지도 (경보 지도와 같은 EO 배경 + 아군 자산 마커) + 그 아래
           마커를 클릭하면 나오는 정보 패널. 아군 자산은 DB에 관련 테이블이 아직
           없어 목업 데이터를 쓰지만, 클릭 → 정보 조회 흐름은 실제 DB 연동과 동일한
           구조로 만들어서 나중에 함수만 교체하면 된다.
"""
import base64
from pathlib import Path
from typing import Optional

import folium
import streamlit as st
from streamlit_folium import st_folium

import service  # features/4/service.py


def _render_alert_info_card(alert: service.Alert) -> None:
    """왼쪽 정보 카드: 알림종류(색)·경보제목·변화요약·지역."""
    st.subheader("경보 정보")
    level_label = service.marker_label(alert.alert_level)
    st.markdown(f":{service.marker_color(alert.alert_level)}[**[{level_label}]**]")
    st.markdown(f"**{alert.title or '(제목 없음)'}**")

    st.divider()
    st.caption("변화 요약")
    st.write(alert.summary or "변화 요약 정보가 없습니다.")

    st.caption("지역")
    st.write(alert.region or "지역 정보가 없습니다.")


# 사진(10:00/12:00/14:00)은 모두 840x840 정사각형이라, 폭을 키우면 높이도
# 똑같이 커져서 스크롤이 생긴다. 그래서 "폭은 컬럼에 꽉 채우고, 높이만 고정해서
# 잘라 보여주는"(object-fit: cover) 방식으로 그린다 - 14:00 사진이 10:00+12:00을
# 합친 너비만큼 넓어지면서도 세로 길이는 그대로 유지된다.
_THUMB_HEIGHT_PX = 150  # 10:00·12:00 작은 썸네일의 높이
_MAIN_HEIGHT_PX = 400   # 가장 최근(14:00) 큰 사진의 높이 (오른쪽 지도+정보 패널 높이만큼 채움)


def _image_data_uri(path: Path) -> str:
    """이미지 파일을 <img> 태그에 바로 쓸 수 있는 base64 data URI로 바꾼다."""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _render_image_slot(path: Optional[Path], label: str, height_px: int) -> None:
    """이미지 한 장을 컬럼 폭에 꽉 채우고, 높이는 height_px로 잘라서 보여준다."""
    st.caption(label)
    if path is not None and path.exists():
        st.markdown(
            f'<img src="{_image_data_uri(path)}" '
            f'style="width:100%;height:{height_px}px;object-fit:cover;border-radius:4px;" />',
            unsafe_allow_html=True,
        )
    else:
        st.info("이미지가 없습니다. (준비 중)")


def _render_alert_photos(alert_id: int) -> None:
    """위성사진 3장: 10:00·12:00은 작은 썸네일 2개, 가장 최근(14:00)은 아래에 전체 폭으로 크게."""
    images = service.get_alert_images(alert_id)
    default_labels = ["사진 1", "사진 2", "사진 3"]

    thumb_col1, thumb_col2 = st.columns(2)
    for i, col in enumerate((thumb_col1, thumb_col2)):
        image_path = images[i] if i < len(images) else None
        label = service.image_time_label(image_path) if image_path is not None else default_labels[i]
        with col:
            _render_image_slot(image_path, label, _THUMB_HEIGHT_PX)

    main_path = images[2] if len(images) > 2 else None
    main_label = service.image_time_label(main_path) if main_path is not None else default_labels[2]
    _render_image_slot(main_path, main_label, _MAIN_HEIGHT_PX)


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
    """오른쪽 위: 경보 지도와 같은 EO 배경 위에 아군 자산 마커를 찍은 미니 지도.
    바로 아래에는 마커를 클릭했을 때 정보를 보여주는 패널을 둔다.
    """
    st.caption("아군 자산 위치 (목업 데이터)")
    try:
        friendly_map = service.build_eo_map()
    except Exception as exc:
        st.error(f"아군 자산 지도 생성 실패: {exc}")
        return

    assets = service.get_mock_friendly_assets()
    for asset in assets:
        folium.Marker(
            location=[asset.latitude, asset.longitude],
            tooltip=f"{asset.name} ({asset.asset_type})",
            icon=folium.Icon(color=service.FRIENDLY_MARKER_COLOR, icon=service.FRIENDLY_MARKER_ICON),
        ).add_to(friendly_map)

    map_key = f"friendly-map-{st.session_state.get('_map_reset_token', 0)}"
    map_data = st_folium(
        friendly_map, width=380, height=420,
        returned_objects=["last_object_clicked"],
        key=map_key,
    )

    clicked = map_data.get("last_object_clicked") if map_data else None
    if clicked:
        matched = _find_friendly_asset_by_click(clicked["lat"], clicked["lng"], assets)
        if matched is not None:
            st.session_state["selected_friendly_asset"] = matched.name

    # 클릭해서 선택한 자산 정보를 지도 바로 아래에 보여준다 (다른 페이지로 이동하지 않음).
    st.markdown("**선택한 아군 자산 정보**")
    selected_name = st.session_state.get("selected_friendly_asset")
    selected = next((a for a in assets if a.name == selected_name), None)
    if selected is not None:
        st.write(f"이름: {selected.name}")
        st.write(f"종류: {selected.asset_type}")
        st.write(f"좌표: {selected.latitude:.4f}, {selected.longitude:.4f}")
    else:
        st.info("마커를 누르면 여기에 정보가 표시됩니다.")


def render_alert_detail_page() -> None:
    """경보 상세 페이지 전체를 그린다."""
    if st.button("← 지도로 돌아가기"):
        st.session_state["view"] = "map"
        # 지도 컴포넌트를 새로 만들도록 key를 바꿔, 이전 클릭 좌표가 남아있지 않게 한다.
        st.session_state["_map_reset_token"] = st.session_state.get("_map_reset_token", 0) + 1
        st.rerun()

    st.title("경보 상세")

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

    st.caption(f"alert_id: {alert.alert_id}")

    info_col, photo_col, map_col = st.columns([1, 1.8, 1.2])

    with info_col:
        _render_alert_info_card(alert)

    with photo_col:
        _render_alert_photos(alert.alert_id)

    with map_col:
        _render_friendly_asset_map()
