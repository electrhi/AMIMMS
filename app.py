from flask import Flask, render_template, request, redirect, url_for, session, send_file
from PIL import Image, ImageDraw, ImageFont
from google.oauth2 import service_account
from googleapiclient.discovery import build
import base64, io, os, json, bcrypt, socket, qrcode
from datetime import datetime

app = Flask(__name__)
app.secret_key = "kdn_secret_key"

# ==============================
# ✅ Google Sheets 연결 설정
# ==============================
GOOGLE_CREDENTIALS = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
USERS_SHEET_KEY = os.getenv("USERS_SHEET_KEY")
RECORDS_SHEET_KEY = os.getenv("RECORDS_SHEET_KEY")

def get_service():
    creds = service_account.Credentials.from_service_account_info(
        GOOGLE_CREDENTIALS, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)

# ==============================
# 로그인 페이지 (Google Sheets 연동)
# ==============================
@app.route("/", methods=["GET", "POST"])
def login():
    service = get_service()
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=USERS_SHEET_KEY, range="A2:B").execute()
    users = result.get("values", [])

    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip()
        password = request.form.get("password", "").strip()

        for row in users:
            if len(row) >= 2 and row[0] == user_id:
                hashed_pw = row[1]
                if bcrypt.checkpw(password.encode(), hashed_pw.encode()):
                    session.clear()
                    session["logged_in"] = True
                    session["user_id"] = user_id
                    return redirect(url_for("menu"))
        return render_template("login.html", error="로그인 정보가 올바르지 않습니다.")
    return render_template("login.html")

# ==============================
# 메뉴 페이지
# ==============================
@app.route("/menu")
def menu():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("menu.html", user_id=session["user_id"])

# ==============================
# 자재 다중입력 페이지
# ==============================
@app.route("/form", methods=["GET", "POST"])
def form_page():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if request.args.get("new") == "1":
        session.pop("materials", None)

    if request.method == "POST":
        materials = []
        통신방식 = request.form.getlist("통신방식")
        구분 = request.form.getlist("구분")
        신철 = request.form.getlist("신철")
        수량 = request.form.getlist("수량")
        박스번호 = request.form.getlist("박스번호")

        for i in range(len(통신방식)):
            if 수량[i].strip():
                materials.append({
                    "통신방식": 통신방식[i],
                    "구분": 구분[i],
                    "신철": 신철[i],
                    "수량": 수량[i],
                    "박스번호": 박스번호[i]
                })
        session["materials"] = materials
        return redirect(url_for("confirm"))

    return render_template("form.html", materials=session.get("materials", []))

# ==============================
# 인수증 확인 페이지
# ==============================
@app.route("/confirm", methods=["GET", "POST"])
def confirm():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    materials = session.get("materials", [])
    logged_user = session.get("user_id", "")

    if request.method == "POST":
        giver = request.form["giver"]
        receiver = request.form["receiver"]
        giver_sign = request.form["giver_sign"]
        receiver_sign = request.form["receiver_sign"]

        receipt_path = generate_receipt(materials, giver, receiver, giver_sign, receiver_sign)
        save_to_google_sheet(materials, giver, receiver)
        session.pop("materials", None)
        session["last_receipt"] = receipt_path

        return render_template("receipt_result.html", receipt_path=receipt_path)

    return render_template("confirm.html", materials=materials, logged_user=logged_user)

# ==============================
# 누적 자재 현황
# ==============================
@app.route("/summary")
def summary():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    user_id = session.get("user_id")
    service = get_service()
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=RECORDS_SHEET_KEY, range="A2:H").execute()
    rows = result.get("values", [])
    data_dict = {}

    for row in rows:
        if len(row) < 8: continue
        통신방식, 구분, 주는사람, 받는사람, 신철, 수량, 박스번호, 작성일자 = row
        if 받는사람 == user_id:
            key = (통신방식, 구분)
            if key not in data_dict:
                data_dict[key] = {"합계": 0, "박스수": 0}
            data_dict[key]["합계"] += int(수량)
            data_dict[key]["박스수"] += 1

    summary_data = sorted(
        [{"통신방식": k[0], "구분": k[1], "합계": v["합계"], "박스수": v["박스수"]} for k, v in data_dict.items()],
        key=lambda x: (x["통신방식"], x["구분"])
    )

    if not summary_data:
        return render_template("summary.html", summary_data=None, message="등록된 자재 데이터가 없습니다.")
    return render_template("summary.html", summary_data=summary_data)

# ==============================
# 로그아웃
# ==============================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ==============================
# 인수증 다운로드
# ==============================
@app.route("/download_receipt")
def download_receipt():
    folder = "static/receipts"
    last_receipt = session.get("last_receipt")
    if last_receipt and os.path.exists(last_receipt):
        return send_file(last_receipt, as_attachment=True)
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".jpg")]
    if not files:
        return "인수증 파일이 없습니다.", 404
    latest_file = max(files, key=os.path.getctime)
    return send_file(latest_file, as_attachment=True)

# ==============================
# Google Sheets 저장 함수
# ==============================
def save_to_google_sheet(materials, giver, receiver):
    service = get_service()
    sheet = service.spreadsheets()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values = [[
        m["통신방식"], m["구분"], giver, receiver,
        m["신철"], m["수량"], m["박스번호"], now
    ] for m in materials]
    body = {"values": values}
    sheet.values().append(
        spreadsheetId=RECORDS_SHEET_KEY, range="A2",
        valueInputOption="RAW", body=body
    ).execute()

# ==============================
# 인수증 이미지 생성
# ==============================
def generate_receipt(materials, giver, receiver, giver_sign, receiver_sign):
    width, height = 1240, 1754
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font_path = "C:/Windows/Fonts/malgun.ttf"
    title_font = ImageFont.truetype(font_path, 60)
    bold_font = ImageFont.truetype(font_path, 34)
    small_font = ImageFont.truetype(font_path, 22)

    logo_path = "static/kdn_logo.png"
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).resize((220, 100))
        img.paste(logo, (80, 70))

    title = "자재 인수증"
    w = draw.textlength(title, font=title_font)
    draw.text(((width - w) / 2, 100), title, font=title_font, fill="black")
    draw.text((80, 220), f"작성일자: {datetime.now().strftime('%Y-%m-%d %H:%M')}", font=bold_font, fill="black")

    headers = ["통신방식", "구분", "신/철", "수량", "박스번호"]
    pos = [100, 400, 600, 800, 1000]
    y = 300
    draw.rectangle((80, y, 1160, y + 55), outline="black", fill="#E8F0FE")
    for i, h in enumerate(headers):
        draw.text((pos[i], y + 10), h, font=bold_font, fill="black")

    y += 70
    for m in materials:
        draw.text((pos[0], y), m["통신방식"], font=bold_font, fill="black")
        draw.text((pos[1], y), m["구분"], font=bold_font, fill="black")
        draw.text((pos[2], y), m["신철"], font=bold_font, fill="black")
        draw.text((pos[3], y), str(m["수량"]), font=bold_font, fill="black")
        draw.text((pos[4], y), str(m["박스번호"]), font=bold_font, fill="black")
        y += 50

    draw.rectangle((80, 300, 1160, y), outline="black")

    def decode_signature(data):
        if not data: return None
        data = data.split(",")[1]
        return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGBA")

    giver_img = decode_signature(giver_sign)
    receiver_img = decode_signature(receiver_sign)
    footer_y = height - 150
    draw.text((200, footer_y - 40), f"주는 사람: {giver} (인)", font=bold_font, fill="black")
    draw.text((800, footer_y - 40), f"받는 사람: {receiver} (인)", font=bold_font, fill="black")

    if giver_img: img.paste(giver_img.resize((260, 120)), (240, footer_y - 190), giver_img)
    if receiver_img: img.paste(receiver_img.resize((260, 120)), (840, footer_y - 190), receiver_img)

    draw.text((width // 2 - 250, height - 80), "한전KDN 주식회사 | AMI 자재관리시스템", font=small_font, fill="gray")

    os.makedirs("static/receipts", exist_ok=True)
    filename = f"static/receipts/AMI인수증_{receiver}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    img.save(filename, "JPEG", quality=95)
    return filename

# ==============================
# 서버 실행
# ==============================
if __name__ == "__main__":
    local_ip = socket.gethostbyname(socket.gethostname())
    port = 5000
    url = f"http://{local_ip}:{port}"
    qr = qrcode.make(url)
    os.makedirs("static", exist_ok=True)
    qr.save("static/server_qr.png")
    print(f"✅ 서버 실행 중: {url}")
    app.run(host="0.0.0.0", port=port, debug=True)
