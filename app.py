import os
import io
import base64
import requests
import pandas as pd
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, session, url_for
from PIL import Image, ImageDraw, ImageFont, ImageOps
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request
from google.cloud import storage

# ✅ HTTPS 인증 경고 방지
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "kdn_secret_key")

# ===============================
# 환경 변수 및 기본 설정
# ===============================
USERS_SHEET_KEY = os.environ.get("USERS_SHEET_KEY")
RECORDS_SHEET_KEY = os.environ.get("RECORDS_SHEET_KEY")
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")
GOOGLE_CREDENTIALS = eval(os.environ.get("GOOGLE_CREDENTIALS_JSON", "{}"))

# ===============================
# ✅ GCS 업로드 함수
# ===============================
def upload_to_gcs(file_path, file_name, bucket_name):
    try:
        creds = Credentials.from_service_account_info(GOOGLE_CREDENTIALS)
        client = storage.Client(credentials=creds)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(file_name)
        blob.upload_from_filename(file_path, content_type="image/jpeg")
        url = blob.generate_signed_url(expiration=timedelta(days=365), method="GET")
        print(f"✅ GCS 업로드 성공: {url}")
        return url
    except Exception as e:
        print(f"❌ GCS 업로드 실패: {e}")
        return None

# ===============================
# ✅ 구글 시트 데이터 가져오기
# ===============================
def get_google_sheet_data(sheet_key, sheet_name):
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=SCOPES)
    if not creds.valid or not creds.token:
        creds.refresh(Request())

    if not sheet_key:
        print("❌ 시트 키 누락됨 (환경변수 확인 필요)")
        return pd.DataFrame()

    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_key}/values/{sheet_name}"
    headers = {"Authorization": f"Bearer {creds.token}"}

    try:
        resp = requests.get(url, headers=headers, verify=False, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("values", [])
        if not data or len(data) < 2:
            return pd.DataFrame()

        headers_row = data[0]
        records = data[1:]
        df = pd.DataFrame(records, columns=headers_row)
        df.columns = df.columns.str.replace(" ", "").str.replace("/", "").str.strip()
        return df
    except Exception as e:
        print(f"❌ Google Sheets 데이터 불러오기 실패: {e}")
        return pd.DataFrame()

# ===============================
# 자재 인수증 이미지 생성
# ===============================
def generate_receipt(materials, giver, receiver, giver_sign, receiver_sign):
    width, height = 1240, 1754
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    font_path = os.path.join(os.path.dirname(__file__), "static/fonts/NotoSansKR-Bold.otf")
    title_font = ImageFont.truetype(font_path, 60)
    bold_font = ImageFont.truetype(font_path, 36)
    text_font = ImageFont.truetype(font_path, 30)
    small_font = ImageFont.truetype(font_path, 24)

    base_dir = os.path.dirname(__file__)
    logo_path = os.path.join(base_dir, "static", "kdn_logo.png")
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA").resize((200, 200))
        img.paste(logo, (100, 60), logo)

    draw.text((460, 120), "자재 인수증", font=title_font, fill="black")
    draw.text((100, 300), f"작성일자: {datetime.now().strftime('%Y-%m-%d')}", font=text_font, fill="black")

    start_y = 400
    headers = ["통신방식", "구분", "신철", "수량", "박스번호"]
    positions = [100, 400, 700, 900, 1100]
    header_height = 60
    row_height = 50

    draw.rectangle((80, start_y, 1160, start_y + header_height), outline="black", fill="#E3ECFC")
    for i, h in enumerate(headers):
        draw.text((positions[i], start_y + 10), h, font=bold_font, fill="black")

    y = start_y + header_height
    for m in materials:
        draw.rectangle((80, y, 1160, y + row_height), outline="black", fill="white")
        draw.text((positions[0], y + 10), str(m.get("통신방식", "")), font=text_font, fill="black")
        draw.text((positions[1], y + 10), str(m.get("구분", "")), font=text_font, fill="black")
        draw.text((positions[2], y + 10), str(m.get("신철", "")), font=text_font, fill="black")
        draw.text((positions[3], y + 10), str(m.get("수량", "")), font=text_font, fill="black")
        draw.text((positions[4], y + 10), str(m.get("박스번호", "")), font=text_font, fill="black")
        y += row_height

    draw.rectangle((80, start_y, 1160, y), outline="black")

    def decode_sign(encoded_sign):
        try:
            encoded_clean = encoded_sign.split(",")[1] if "," in encoded_sign else encoded_sign
            if not encoded_clean:
                return None
            sign_img = Image.open(io.BytesIO(base64.b64decode(encoded_clean))).convert("L")
            inverted = Image.eval(sign_img, lambda p: 255 - p)
            return inverted.convert("RGBA")
        except Exception:
            return None

    giver_img = decode_sign(giver_sign)
    receiver_img = decode_sign(receiver_sign)

    footer_y = y + 200
    draw.text((200, footer_y), f"주는 사람: {giver} (인)", font=bold_font, fill="black")
    draw.text((800, footer_y), f"받는 사람: {receiver} (인)", font=bold_font, fill="black")

    if giver_img:
        img.paste(giver_img.resize((250, 100)), (240, footer_y - 120))
    if receiver_img:
        img.paste(receiver_img.resize((250, 100)), (840, footer_y - 120))

    draw.text((width / 2 - 280, height - 100),
              "한전KDN 주식회사 | AMI 자재관리시스템",
              font=small_font, fill="gray")

    tmp_filename = f"/tmp/receipt_{receiver}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    img.save(tmp_filename, "JPEG", quality=95)
    return upload_to_gcs(tmp_filename, os.path.basename(tmp_filename), GCS_BUCKET_NAME)

# ===============================
# Flask Routes (변경 없음)
# ===============================
@app.route("/")
def login():
    df = get_google_sheet_data(USERS_SHEET_KEY, "시트1")
    users = df["ID"].tolist() if "ID" in df.columns else []
    return render_template("login.html", users=users)

@app.route("/", methods=["POST"])
def login_post():
    user_id = request.form.get("user_id")
    session["user_id"] = user_id
    return redirect("/menu")

@app.route("/menu")
def menu():
    return render_template("menu.html")

@app.route("/form")
def form():
    return render_template("form.html")

@app.route("/confirm", methods=["GET", "POST"])
def confirm():
    if request.method == "POST":
        giver = request.form.get("giver")
        receiver = request.form.get("receiver")
        giver_sign = request.form.get("giver_sign")
        receiver_sign = request.form.get("receiver_sign")

        materials = [{
            "통신방식": request.form.get("type"),
            "구분": request.form.get("category"),
            "신철": request.form.get("material"),
            "수량": request.form.get("qty"),
            "박스번호": request.form.get("box"),
        }]

        receipt_link = generate_receipt(materials, giver, receiver, giver_sign, receiver_sign)
        save_to_sheets(materials, giver, receiver)

        return render_template("result.html", receipt_link=receipt_link)
    return redirect("/form")

def save_to_sheets(materials, giver, receiver):
    try:
        SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=SCOPES)
        if not creds.valid or not creds.token:
            creds.refresh(Request())

        import gspread
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(RECORDS_SHEET_KEY)
        ws = sh.sheet1

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for m in materials:
            ws.append_row([
                m.get("통신방식", ""), m.get("구분", ""), giver, receiver,
                m.get("신철", ""), m.get("수량", ""), m.get("박스번호", ""), now
            ], value_input_option="USER_ENTERED")
        print("✅ Google Sheets 저장 완료")

    except Exception as e:
        print(f"❌ 시트 저장 실패: {e}")

@app.route("/summary")
def summary():
    user_id = session.get("user_id", "")
    df = get_google_sheet_data(RECORDS_SHEET_KEY, "시트1")
    if df.empty:
        return render_template("summary.html", data=[])
    df = df[df["받는사람"] == user_id]
    return render_template("summary.html", data=df.to_dict("records"))

@app.route("/admin_summary")
def admin_summary():
    df = get_google_sheet_data(RECORDS_SHEET_KEY, "시트1")
    if df.empty:
        return render_template("admin_summary.html", data=[], total={})

    df["수량"] = pd.to_numeric(df["수량"], errors="coerce").fillna(0)
    pivot = df.pivot_table(index=["받는사람"], columns=["통신방식"], values="수량", aggfunc="sum", fill_value=0)
    pivot.loc["합계"] = pivot.select_dtypes(include=["number"]).sum(axis=0)

    return render_template("admin_summary.html", tables=[pivot.to_html(classes="data")])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
