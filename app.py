import os
import io
import base64
import requests
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session
from google.oauth2.service_account import Credentials
from google.cloud import storage
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import json
import ssl
import certifi
import gspread
import urllib3

# =========================================================
# ✅ SSL 인증 안정화 (Render + Google API)
# =========================================================
# certifi의 최신 CA 번들을 이용해 HTTPS 통신 안정화
# urllib3 / requests / gspread 모두 동일하게 적용됨
# =========================================================

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class SSLAdapter(requests.adapters.HTTPAdapter):
    """requests용 안전한 SSLAdapter"""
    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context(cafile=certifi.where())
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

# ✅ requests 전용 세션 (Flask session과 이름 구분)
http_session = requests.Session()
http_session.mount("https://", SSLAdapter())

# =========================================================
# ✅ Flask 초기화
# =========================================================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "kdn_secret_key")

# =========================================================
# ✅ Google Sheets / GCS 연결 설정
# =========================================================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

if not GOOGLE_CREDENTIALS_JSON:
    raise RuntimeError("❌ GOOGLE_CREDENTIALS_JSON 환경 변수가 설정되지 않았습니다.")

CREDS = Credentials.from_service_account_info(json.loads(GOOGLE_CREDENTIALS_JSON), scopes=SCOPES)
gc = gspread.authorize(CREDS)

# 환경 변수로 시트 키 및 버킷 이름 로드
USERS_SHEET_KEY = os.getenv("GOOGLE_USERS_SHEET_KEY")
RECORDS_SHEET_KEY = os.getenv("GOOGLE_RECORDS_SHEET_KEY")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "amimms-receipts")

# 구글 시트 객체 초기화
users_sheet = gc.open_by_key(USERS_SHEET_KEY).sheet1
records_sheet = gc.open_by_key(RECORDS_SHEET_KEY).sheet1


# =========================================================
# ✅ 로그인
# =========================================================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_id = request.form["user_id"]
        password = request.form["password"]

        df = pd.DataFrame(users_sheet.get_all_records())

        user = df.loc[df["ID"] == user_id]

        if not user.empty and user.iloc[0]["PASSWORD"] == password:
            # ✅ 로그인 성공 시 세션에 ID, 권한 저장
            session["logged_in"] = True
            session["user_id"] = user_id
            session["authority"] = user.iloc[0]["AUTHORITY"]  # ← 중요!!

            return redirect(url_for("menu"))
        else:
            return render_template("login.html", error="아이디 또는 비밀번호가 잘못되었습니다.")
    return render_template("login.html")


# =========================================================
# ✅ 메뉴 (로그인 사용자 표시 포함)
# =========================================================
@app.route("/menu")
def menu():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    
    # ✅ 권한 값 전달 (authority를 템플릿으로 넘김)
    return render_template(
        "menu.html",
        user_id=session.get("user_id"),
        authority=session.get("authority")
    )

# =========================================================
# ✅ 자재 입력
# =========================================================
@app.route("/form", methods=["GET", "POST"])
def form():
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

# =========================================================
# ✅ 확인 페이지
# =========================================================
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

        # ✅ 인수증 이미지 생성 및 업로드
        receipt_link = generate_receipt(materials, giver, receiver, giver_sign, receiver_sign)

        # ✅ 세션에 저장해 /download_receipt에서 활용 가능
        session["last_receipt"] = receipt_link

        # ✅ result.html에 링크만 전달
        return render_template(
            "result.html",
            receipt_link=receipt_link
        )


    return render_template("confirm.html", materials=materials, logged_user=logged_user)


# =========================================================
# ✅ 누적 자재 현황
# =========================================================
@app.route("/summary")
def summary():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    user_id = session.get("user_id", "")
    df = pd.DataFrame(records_sheet.get_all_records())

    if df.empty or "받는사람" not in df.columns:
        return render_template("summary.html", summary_data=None, message="등록된 자재 데이터가 없습니다.")

    df = df[df["받는사람"] == user_id]
    if df.empty:
        return render_template("summary.html", summary_data=None, message="등록된 자재 데이터가 없습니다.")

    summary = df.groupby(["통신방식", "구분"], as_index=False).agg({"수량": "sum", "박스번호": "count"})
    summary.rename(columns={"수량": "합계", "박스번호": "박스수"}, inplace=True)
    summary.sort_values(["통신방식", "구분"], inplace=True)

    return render_template("summary.html", summary_data=summary.to_dict("records"))


# =========================================================
# ✅ 관리자용 종합관리표
# =========================================================
@app.route("/admin_summary")
def admin_summary():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if session.get("authority") != "y":
        return "❌ 접근 권한이 없습니다.", 403

    user_id = session.get("user_id", "")
    df = pd.DataFrame(records_sheet.get_all_records())

    if df.empty:
        return render_template("admin_summary.html", message="등록된 자재 데이터가 없습니다.", user_id=user_id)

    df = df[df["주는사람"] == user_id]
    if df.empty:
        return render_template("admin_summary.html", message="해당 사용자의 기록이 없습니다.", user_id=user_id)

    pivot = pd.pivot_table(df, index="받는사람", columns="구분", values="수량", aggfunc="sum", fill_value=0)
    pivot.loc["합계"] = pivot.sum(numeric_only=True)
    table_html = pivot.to_html(classes="table-auto border text-center", border=1)

    return render_template("admin_summary.html", table_html=table_html, user_id=user_id)


# =========================================================
# ✅ 관리자 종합관리표 엑셀 다운로드
# =========================================================
@app.route("/download_admin_summary")
def download_admin_summary():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if session.get("authority") != "y":
        return "❌ 접근 권한이 없습니다.", 403

    user_id = session.get("user_id", "")
    df = pd.DataFrame(records_sheet.get_all_records())

    if df.empty:
        return "❌ 다운로드할 데이터가 없습니다.", 404

    df = df[df["주는사람"] == user_id]
    if df.empty:
        return "❌ 해당 사용자의 데이터가 없습니다.", 404

    pivot = pd.pivot_table(df, index="받는사람", columns="구분", values="수량", aggfunc="sum", fill_value=0)
    pivot.loc["합계"] = pivot.sum(numeric_only=True)
    pivot.reset_index(inplace=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "종합관리표"

    for col_idx, col_name in enumerate(pivot.columns, start=1):
        ws.cell(row=1, column=col_idx, value=col_name)
    for row_idx, row in enumerate(pivot.values.tolist(), start=2):
        for col_idx, val in enumerate(row, start=1):
            ws.cell(row=row_idx, column=col_idx, value=val)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"admin_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# =========================================================
# ✅ GCS 업로드 함수
# =========================================================
from datetime import timedelta

def upload_to_gcs(file_path, file_name, bucket_name):
    try:
        creds = Credentials.from_service_account_info(json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"]))
        client = storage.Client(credentials=creds)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        blob.upload_from_filename(file_path, content_type="image/jpeg")

        # ✅ URL 유효기간 1년으로 정확히 지정
        url = blob.generate_signed_url(expiration=timedelta(days=365), method="GET")
        return url
    except Exception as e:
        print(f"❌ GCS 업로드 실패: {e}")
        return None



# =========================================================
# ✅ 인수증 이미지 생성 (로고 + 한글 폰트)
# =========================================================
def generate_receipt(materials, giver, receiver, giver_sign, receiver_sign):
    width, height = 1240, 1754
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # ✅ 폰트 설정
    font_path = os.path.join(os.path.dirname(__file__), "static/fonts/NotoSansKR-Bold.otf")
    title_font = ImageFont.truetype(font_path, 64)
    bold_font = ImageFont.truetype(font_path, 36)
    small_font = ImageFont.truetype(font_path, 26)

    # ✅ 로고 (크기 줄이기 + 예쁜 위치)
    base_dir = os.path.dirname(__file__)
    logo_path = os.path.join(base_dir, "static", "kdn_logo.png")

    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((140, 140))  # 🔹 높이 줄임 (이전 200 → 140)
        img.paste(logo, (width - 240, 80), logo)  # 🔹 위치도 살짝 조정

    # ✅ 제목 & 날짜
    draw.text((width // 2 - 150, 100), "자재 인수증", font=title_font, fill="black")
    draw.text((100, 230), f"작성일자: {datetime.now().strftime('%Y-%m-%d')}", font=bold_font, fill="black")

    # ✅ 표 헤더
    y = 360
    headers = ["통신방식", "구분", "신철", "수량", "박스번호"]
    positions = [100, 400, 600, 800, 1000]
    row_height = 60

    draw.rectangle((80, y, 1160, y + row_height), outline="black", fill="#E8F0FE")
    for i, h in enumerate(headers):
        draw.text((positions[i], y + 10), h, font=bold_font, fill="black")

    y += row_height
    for m in materials:
        draw.rectangle((80, y, 1160, y + row_height), outline="black", fill="white")
        for i, key in enumerate(headers):
            draw.text((positions[i], y + 10), str(m.get(key, "")), font=bold_font, fill="black")
        y += row_height

    draw.rectangle((80, 360, 1160, y), outline="black")

    # ✅ 서명 디코드
    def decode_sign(s):
        try:
            s = s.split(",")[1] if "," in s else s
            img = Image.open(BytesIO(base64.b64decode(s)))
            return img.convert("RGBA")
        except Exception:
            return None

    giver_img, receiver_img = decode_sign(giver_sign), decode_sign(receiver_sign)

    # ✅ 서명 위치
    footer_y = height - 200
    draw.text((200, footer_y + 40), f"주는 사람: {giver} (인)", font=bold_font, fill="black")
    draw.text((800, footer_y + 40), f"받는 사람: {receiver} (인)", font=bold_font, fill="black")

    # ✅ 서명이 글자 위에 겹치도록 조정 (겹침효과)
    if giver_img:
        giver_resized = giver_img.resize((220, 100))
        img.paste(giver_resized, (320, footer_y - 10), giver_resized)  # 👈 글자보다 위로 올림

    if receiver_img:
        receiver_resized = receiver_img.resize((220, 100))
        img.paste(receiver_resized, (920, footer_y - 10), receiver_resized)

    img = img.convert("RGB")

    # ✅ 저장 및 업로드
    tmp_filename = f"/tmp/receipt_{receiver}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    img.save(tmp_filename, "JPEG", quality=95)

    BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "amimms-receipts")
    gcs_link = upload_to_gcs(tmp_filename, os.path.basename(tmp_filename), BUCKET_NAME)

    return gcs_link or "GCS 업로드 실패"

# =========================================================
# ✅ Google Sheets 저장
# =========================================================
def save_to_sheets(materials, giver, receiver):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for m in materials:
        records_sheet.append_row([
            m["통신방식"], m["구분"], giver, receiver,
            m["신철"], m["수량"], m["박스번호"], now
        ])


# =========================================================
# ✅ 인수증 다운로드
# =========================================================
@app.route("/download_receipt")
def download_receipt():
    receipt_path = session.get("last_receipt")
    if receipt_path:
        return redirect(receipt_path)
    return "❌ 인수증 파일을 찾을 수 없습니다.", 404


# =========================================================
# ✅ 로그아웃
# =========================================================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================================================
# ✅ 서버 실행
# =========================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)














