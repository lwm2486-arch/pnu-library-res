import os
# 빌드 시 서버에 크롬 브라우저가 없으면 자동으로 강제 설치하는 코드
if not os.path.exists("/home/adminuser/.cache/ms-playwright"):
    os.system("playwright install chromium")
import streamlit as st
import requests
import time
import random
import json
from urllib.parse import unquote
from playwright.sync_api import sync_playwright

# =========================
# 웹사이트 기본 설정
# =========================
st.set_page_config(page_title="도서관 자리 자동 예약", page_icon="📚")
RESERVE_API_URL = "https://lib.pusan.ac.kr/pyxis-api/1/api/seat-charges"

# 접속 비밀번호 설정
SECRET_PASSWORD = "ourpnu123"

# =========================
# 기능 함수 모음
# =========================
def get_auto_login_session(student_id, password):
    """Playwright를 이용해 화면 없이 자동으로 로그인하고 쿠키와 토큰을 추출합니다."""
    with sync_playwright() as p:
        # 클라우드 서버에서 돌아가야 하므로 headless=True로 실행
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        try:
            # 1. 도서관 로그인 페이지로 이동 (좌석 예약 페이지로 가면 보통 로그인 창으로 튕김)
            page.goto("https://lib.pusan.ac.kr/facility/seat/reading-rooms-for-reservation/69", wait_until="domcontentloaded")
            
            # =====================================================================
            # 🚨 [매우 중요] 실제 부산대 로그인 페이지에 맞게 아래 CSS 선택자를 수정해야 합니다!
            # =====================================================================
            # 예시: 아이디 입력칸이 <input name="userid"> 이고, 비번이 <input name="password"> 인 경우
            page.fill("input[name='userId']", student_id)       # 학번 입력
            page.fill("input[name='password']", password)   # 비밀번호 입력
            page.click("button[type='submit']")                  # 로그인 버튼 클릭
            # =====================================================================
            
            # 로그인이 처리되고 페이지가 넘어갈 때까지 대기
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            
            # 2. 쿠키 수집
            cookies = context.cookies("https://lib.pusan.ac.kr")
            cookie_dict = {c["name"]: c["value"] for c in cookies}
            
            # 3. 토큰 추출
            pyxis_cookie = cookie_dict.get("PUSAN_PYXIS3")
            token = None
            if pyxis_cookie:
                decoded = unquote(pyxis_cookie)
                token = json.loads(decoded).get("accessToken")
                
            return cookie_dict, token
            
        except Exception as e:
            st.error(f"로그인 자동화 중 오류 발생: {e}")
            return None, None
        finally:
            browser.close()

def make_requests_session(cookie_dict, token):
    """추출한 쿠키와 토큰으로 API 통신용 세션을 만듭니다."""
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko",
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Pyxis-Auth-Token": token,
    })
    for name, value in cookie_dict.items():
        session.cookies.set(name, value, domain="lib.pusan.ac.kr")
    return session

def check_seats(session, room_id, target_seats_list):
    """특정 열람실의 빈자리를 확인합니다."""
    api_url = f"https://lib.pusan.ac.kr/pyxis-api/1/api/rooms/{room_id}/seats"
    response = session.get(api_url, timeout=10)
    
    if response.status_code != 200:
        return []
        
    data = response.json()
    if not data.get("success"):
        return []
        
    seat_list = data["data"]["list"]
    empty_seats = []
    
    for seat in seat_list:
        code = seat["code"]
        seat_id = seat["id"]
        if seat["isActive"] and not seat["isOccupied"]:
            if not target_seats_list or code in target_seats_list:
                empty_seats.append({"code": code, "id": seat_id})
                
    return empty_seats

def reserve_seat(session, seat_info):
    """선택된 자리에 예약 확정 신호를 보냅니다."""
    payload = {
        "seatId": seat_info["id"],
        "smufMethodCode": "PC"
    }
    try:
        response = session.post(RESERVE_API_URL, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                return True, "예약 성공"
            else:
                return False, result.get("message", "이유를 알 수 없음")
    except Exception as e:
        return False, str(e)
    return False, "서버 응답 오류"

# =========================
# 웹사이트 화면(UI) 구성
# =========================
st.title("📚 도서관 자리 자동 예약기")

# 1. 비밀번호 인증
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.warning("이용하려면 비밀번호를 입력하세요.")
    pwd_input = st.text_input("비밀번호", type="password")
    if st.button("입력"):
        if pwd_input == SECRET_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 틀렸습니다.")
else:
    st.success("인증 완료! 환영합니다.")
    
    # 2. 정보 입력 창 (쿠키 대신 학번/비번으로 변경)
    with st.expander("📝 예약 정보 설정 (필수)", expanded=True):
        student_id = st.text_input("학번")
        student_pw = st.text_input("도서관 비밀번호", type="password")
        room_input = st.text_input("열람실 번호 (예: 69)", value="69")
        target_input = st.text_input("노리는 좌석 번호 (쉼표로 구분, 빈칸이면 아무 자리나)", placeholder="001, 002, 108")
    
    # 세션 상태로 실행 여부 관리
    if "is_running" not in st.session_state:
        st.session_state.is_running = False

    col1, col2 = st.columns(2)
    with col1:
        start_btn = st.button("🚀 자동 로그인 및 감시 시작", use_container_width=True)
    with col2:
        stop_btn = st.button("🛑 감시 중지", use_container_width=True)

    if start_btn:
        if not student_id or not student_pw:
            st.error("학번과 비밀번호를 반드시 입력해야 합니다!")
        else:
            st.session_state.is_running = True

    if stop_btn:
        st.session_state.is_running = False
        st.info("감시가 중지되었습니다.")

    # 3. 감시 루프 실행
    if st.session_state.is_running:
        st.write("---")
        status_text = st.empty()
        log_box = st.empty()
        
        status_text.info("🔐 백그라운드에서 자동 로그인을 시도 중입니다. 잠시만 기다려주세요...")
        cookie_dict, token = get_auto_login_session(student_id, student_pw)
        
        if not cookie_dict or not token:
            st.error("❌ 로그인에 실패했거나 토큰을 찾을 수 없습니다. 아이디/비밀번호를 확인하거나 사이트 구조를 확인하세요.")
            st.session_state.is_running = False
        else:
            target_list = [s.strip() for s in target_input.split(",")] if target_input.strip() else []
            session = make_requests_session(cookie_dict, token)
            
            while st.session_state.is_running:
                now = time.strftime("%H:%M:%S")
                status_text.info(f"👀 [{now}] {room_input}번 열람실 빈자리 감시 중...")
                
                empty_seats = check_seats(session, room_input, target_list)
                
                if empty_seats:
                    target_seat = empty_seats[0]
                    seat_code = target_seat["code"]
                    log_box.warning(f"[{now}] 🎯 {seat_code}번 빈자리 발견! 예약 시도 중...")
                    
                    is_success, msg = reserve_seat(session, target_seat)
                    
                    if is_success:
                        st.success(f"🎉 성공! {seat_code}번 좌석 예약이 완료되었습니다. 15분 내에 확정하세요!")
                        st.balloons()
                        st.session_state.is_running = False
                        break
                    else:
                        log_box.error(f"❌ {seat_code}번 예약 실패 ({msg}). 2초 후 다시 시도합니다...")
                        time.sleep(2 + random.uniform(0.1, 0.5))
                else:
                    time.sleep(2 + random.uniform(0.1, 0.5))
