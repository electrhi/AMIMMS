from flask import Flask, render_template, request, redirect, url_for, session
from datetime import datetime, timedelta
from io import BytesIO
import base64, os, json, requests, pandas as pd
from PIL import Image, ImageDraw, ImageFont
from google.oauth2.service_account import Credentials
from google.cloud import storage
from google.auth.transport.requests import Request

# ---------------------- Flask 초기화 ----------------------
app = Flask(__name__)
app.secret_key = "kdn_secret_key"

# ---------------------- ✅ 공통 설정 ----------------------
GOOGLE_CREDENTIALS = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON", "{}"))
USERS_SHEET_KEY = os.getenv("GOOGLE_USERS_SHEET_KEY")
RECORDS_SHEET_KEY = os.getenv("GOOGLE_RECORDS_SHEET_KEY")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "amimms-receipts")

# ---------------------- ✅ Google Sheets 데이터 가져오기 ----------------------
def get_google_sheet_data(sheet_key, sheet_name):
    """Google Sheets API 호출 (Render SSL 문제 대응)"""
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=SCOPES)

    # ✅ Refresh token 처리
    if not creds.valid or not creds.token:
        creds.refresh(Request())
    access_token = creds.token

    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_key}/values/{sheet_name}"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = requests.get(url, headers=headers, verify=False, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("values", [])
        if not data or len(data) < 2:
            return pd.DataFrame()
        headers = data[0]
        records = data[1:]
        return pd.DataFrame(records, columns=headers)
    except Exception as e:
        print(f"❌ Google Sheets 데이터 불러오기 실패: {e}")
        return pd.DataFrame()

# ---------------------- ✅ Google Sheets에 데이터 저장 ----------------------
def save_to_sheets(materials, giver, receiver):
    """인수증 데이터를 Google Sheets에 저장"""
    try:
        SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=SCOPES)

        if not creds.valid or not creds.token:
            creds.refresh(Request())
        access_token = creds.token

        url = f"https://sheets.googleapis.com/v4/spreadsheets/{RECORDS_SHEET_KEY}/values/시트1:append?valueInputOption=USER_ENTERED"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

        rows = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for m in materials:
            # ✅ 시트 컬럼 순서에 맞게 수정됨
            rows.append([
                m.get("통신방식", ""),
                m.get("구분", ""),
                giver,
                receiver,
                m.get("신철", ""),
                m.get("수량", ""),
                m.get("박스번호", ""),
                timestamp,
            ])

        payload = {"values": rows}
        resp = requests.post(url, headers=headers, data=json.dumps(payload), verify=False, timeout=10)
        resp.raise_for_status()
        print(f"✅ Google Sheets에 데이터 저장 완료 ({len(rows)}행)")
    except Exception as e:
        print(f"❌ Google Sheets 저장 실패: {e}")

# ---------------------- 로그인 ----------------------
@app.route("/", methods=["GET", "POST"])
def login():
    df = get_google_sheet_data(USERS_SHEET_KEY, "시트1")
    if df.empty:
        return "❌ 사용자 정보를 불러올 수 없습니다. (Google Sheets 연결 실패)"

    users = {row["ID"]: row["PASSWORD"] for _, row in df.iterrows()}

    if request.method == "POST":
        user_id = request.form["user_id"].strip()
        pw = request.form["password"].strip()
        if user_id in users and users[user_id] == pw:
            session["logged_in"] = True
            session["user_id"] = user_id
            session["authority"] = df.loc[df["ID"] == user_id, "AUTHORITY"].values[0] if "AUTHORITY" in df.columns else "n"
            return redirect(url_for("menu"))
        return render_template("login.html", error="로그인 정보가 올바르지 않습니다.")
    return render_template("login.html")

# ---------------------- 메뉴 ----------------------
@app.route("/menu")
def menu():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("menu.html", user_id=session["user_id"], authority=session.get("authority", "n"))

# ---------------------- 자재 입력 ----------------------
@app.route("/form", methods=["GET", "POST"])
def form_page():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if request.args.get("new") == "1":
        session.pop("materials", None)

    if request.method == "POST":
        materials = []
        for i in range(len(request.form.getlist("통신방식"))):
            materials.append({
                "통신방식": request.form.getlist("통신방식")[i],
                "구분": request.form.getlist("구분")[i],
                "신철": request.form.getlist("신철")[i],
                "수량": request.form.getlist("수량")[i],
                "박스번호": request.form.getlist("박스번호")[i],
            })
        session["materials"] = materials
        return redirect(url_for("confirm"))
    return render_template("form.html", materials=session.get("materials", []))

# ---------------------- 확인 ----------------------
@app.route("/confirm", methods=["GET", "POST"])
def confirm():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    materials = session.get("materials", [])
    logged_user = session.get("user_id")

    if request.method == "POST":
        giver = request.form["giver"]
        receiver = request.form["receiver"]
        giver_sign = request.form["giver_sign"]
        receiver_sign = request.form["receiver_sign"]

        receipt_link = generate_receipt(materials, giver, receiver, giver_sign, receiver_sign)
        save_to_sheets(materials, giver, receiver)  # ✅ 누락 함수 복구 완료
        session["last_receipt"] = receipt_link
        session.pop("materials", None)
        return render_template("receipt_result.html", receipt_url=receipt_link)

    return render_template("confirm.html", materials=materials, logged_user=logged_user)

# ---------------------- 누적 현황 ----------------------
@app.route("/summary")
def summary():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    user_id = session["user_id"]
    df = get_google_sheet_data(RECORDS_SHEET_KEY, "시트1")

    if df.empty or user_id not in df["받는사람"].values:
        return render_template("summary.html", summary_data=None, message="등록된 자재 데이터가 없습니다.")

    # ✅ 숫자 변환
    df["수량"] = pd.to_numeric(df["수량"], errors="coerce").fillna(0).astype(int)

    df = df[df["받는사람"] == user_id]
    summary = df.groupby(["통신방식", "구분"], as_index=False).agg({"수량": "sum", "박스번호": "count"})
    summary.rename(columns={"수량": "합계", "박스번호": "박스수"}, inplace=True)
    summary.sort_values(["통신방식", "구분"], inplace=True)
    return render_template("summary.html", summary_data=summary.to_dict("records"))

# ---------------------- ✅ 관리자 종합관리표 ----------------------
@app.route("/admin_summary")
def admin_summary():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    user_id = session["user_id"]
    authority = session.get("authority", "n")
    if authority != "y":
        return render_template("no_permission.html")

    df = get_google_sheet_data(RECORDS_SHEET_KEY, "시트1")
    if df.empty:
        return render_template("admin_summary.html", table_html=None, message="등록된 데이터가 없습니다.")

    # ✅ 문자열 수량 → 숫자 변환
    df["수량"] = pd.to_numeric(df["수량"], errors="coerce").fillna(0).astype(int)

    pivot = df.pivot_table(
        index="주는사람",
        columns=["받는사람", "구분"],
        values="수량",
        aggfunc="sum",
        fill_value=0,
    )
    pivot.loc["합계"] = pivot.sum(axis=0)
    html_table = pivot.to_html(
        classes="min-w-full border-collapse border text-center bg-white shadow rounded-lg",
        justify="center"
    )

    return render_template("admin_summary.html", table_html=html_table, user_id=user_id)

# ---------------------- ✅ 인수증 이미지 생성 및 GCS 업로드 ----------------------
def generate_receipt(materials, giver, receiver, giver_sign, receiver_sign):
    """자재 인수증 이미지 생성 (디자인 개선 버전)"""
    width, height = 1240, 1754
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # ✅ 폰트 설정
    font_path_bold = "AMIMMS/static/fonts/NotoSansKR-Bold.otf"
    font_path_regular = "AMIMMS/static/fonts/NotoSansKR-Regular.otf"
    try:
        title_font = ImageFont.truetype(font_path_bold, 60)
        bold_font = ImageFont.truetype(font_path_bold, 36)
        text_font = ImageFont.truetype(font_path_regular, 32)
        small_font = ImageFont.truetype(font_path_regular, 26)
    except:
        title_font = bold_font = text_font = small_font = ImageFont.load_default()

    # ✅ 상단 로고 및 제목
    logo_path = "AMIMMS/static/kdn_logo.png"
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA").resize((220, 220))
        img.paste(logo, (100, 60), logo)

    draw.text((460, 120), "자재 인수증", font=title_font, fill="black")

    # ✅ 작성일자
    draw.text((100, 300), f"작성일자: {datetime.now().strftime('%Y-%m-%d %H:%M')}", font=text_font, fill="black")

    # ✅ 표 그리기
    start_y = 400
    headers = ["통신방식", "구분", "신/철", "수량", "박스번호"]
    positions = [100, 400, 700, 900, 1100]
    col_widths = [300, 300, 200, 200, 200]
    header_height = 60
    row_height = 50

    # 표 헤더 영역
    draw.rectangle((80, start_y, 1160, start_y + header_height), outline="black", fill="#E3ECFC")
    for i, h in enumerate(headers):
        draw.text((positions[i] + 10, start_y + 10), h, font=bold_font, fill="black")

    # 표 내용
    y = start_y + header_height
    for m in materials:
        draw.rectangle((80, y, 1160, y + row_height), outline="black", fill="white")
        draw.text((positions[0] + 10, y + 10), str(m.get("통신방식", "")), font=text_font, fill="black")
        draw.text((positions[1] + 10, y + 10), str(m.get("구분", "")), font=text_font, fill="black")
        draw.text((positions[2] + 10, y + 10), str(m.get("신철", "")), font=text_font, fill="black")
        draw.text((positions[3] + 10, y + 10), str(m.get("수량", "")), font=text_font, fill="black")
        draw.text((positions[4] + 10, y + 10), str(m.get("박스번호", "")), font=text_font, fill="black")
        y += row_height

    draw.rectangle((80, start_y, 1160, y), outline="black")

    # ✅ 서명 처리 (반전 유지)
    def decode_sign(s):
        try:
            s = s.split(",")[1] if "," in s else s
            if not s:
                return None
            img = Image.open(BytesIO(base64.b64decode(s))).convert("L")
            img = Image.eval(img, lambda p: 255 - p)
            return img.convert("RGBA")
        except Exception:
            return None

    giver_img = decode_sign(giver_sign)
    receiver_img = decode_sign(receiver_sign)

    # ✅ 서명 위치
    footer_y = y + 200
    draw.text((200, footer_y), f"주는 사람: {giver} (인)", font=bold_font, fill="black")
    draw.text((800, footer_y), f"받는 사람: {receiver} (인)", font=bold_font, fill="black")

    if giver_img:
        img.paste(giver_img.resize((250, 100)), (240, footer_y - 120))
    if receiver_img:
        img.paste(receiver_img.resize((250, 100)), (840, footer_y - 120))

    # ✅ 하단 회사 정보
    footer_text = "한전KDN 주식회사 | AMI 자재관리시스템"
    draw.text((width/2 - 280, height - 100), footer_text, font=small_font, fill="gray")

    # ✅ 저장
    tmp_filename = f"/tmp/receipt_{receiver}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    img.save(tmp_filename, "JPEG", quality=95)
    return upload_to_gcs(tmp_filename, os.path.basename(tmp_filename), GCS_BUCKET_NAME)


# ---------------------- 로그아웃 ----------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------------- 서버 실행 ----------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

