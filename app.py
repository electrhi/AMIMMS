from flask import Flask, render_template, request, redirect, url_for, session, send_file
from datetime import datetime
from io import BytesIO
import base64, os, qrcode, socket, gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


# ✅ Pillow Import 안정화 (Render + Python 3.13 대응)
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    import subprocess
    subprocess.run(["pip", "install", "--no-cache-dir", "--upgrade", "Pillow==11.0.0"])
    from PIL import Image, ImageDraw, ImageFont
    
import requests
requests.adapters.DEFAULT_RETRIES = 5  # SSL 일시 끊김 대비 자동 재시도


# ---------------------- Flask 초기화 ----------------------
app = Flask(__name__)
app.secret_key = "kdn_secret_key"

# ---------------------- Google Sheets 연결 ----------------------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Render 환경변수에서 credentials.json 읽기
CREDS = Credentials.from_service_account_info(
    json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON")), scopes=SCOPES
)
gc = gspread.authorize(CREDS)

# 🔹 환경변수로 시트 키 가져오기 (Render 설정에서 등록)
USERS_SHEET_KEY = os.getenv("GOOGLE_USERS_SHEET_KEY")
RECORDS_SHEET_KEY = os.getenv("GOOGLE_RECORDS_SHEET_KEY")

users_sheet = gc.open_by_key(USERS_SHEET_KEY).sheet1
records_sheet = gc.open_by_key(RECORDS_SHEET_KEY).sheet1


# ---------------------- 로그인 ----------------------
@app.route("/", methods=["GET", "POST"])
def login():
    df = pd.DataFrame(users_sheet.get_all_records())
    users = {row["ID"]: row["PASSWORD"] for _, row in df.iterrows()}

    if request.method == "POST":
        user_id = request.form["user_id"].strip()
        pw = request.form["password"].strip()
        if user_id in users and users[user_id] == pw:
            session["logged_in"] = True
            session["user_id"] = user_id
            return redirect(url_for("menu"))
        return render_template("login.html", error="로그인 정보가 올바르지 않습니다.")
    return render_template("login.html")


# ---------------------- 메뉴 ----------------------
@app.route("/menu")
def menu():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("menu.html", user_id=session["user_id"])


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

        receipt_path = generate_receipt(materials, giver, receiver, giver_sign, receiver_sign)
        save_to_sheets(materials, giver, receiver)

        session.pop("materials", None)
        session["last_receipt"] = receipt_path
        return render_template("receipt_result.html", receipt_path=receipt_path)
    return render_template("confirm.html", materials=materials, logged_user=logged_user)


# ---------------------- 누적 현황 ----------------------
@app.route("/summary")
def summary():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    user_id = session["user_id"]
    df = pd.DataFrame(records_sheet.get_all_records())

    if df.empty or user_id not in df["받는사람"].values:
        return render_template("summary.html", summary_data=None, message="등록된 자재 데이터가 없습니다.")

    df = df[df["받는사람"] == user_id]
    summary = df.groupby(["통신방식", "구분"], as_index=False).agg({"수량": "sum", "박스번호": "count"})
    summary.rename(columns={"수량": "합계", "박스번호": "박스수"}, inplace=True)
    summary.sort_values(["통신방식", "구분"], inplace=True)
    return render_template("summary.html", summary_data=summary.to_dict("records"))

# ---------------------- Google Drive 업로드 함수 ----------------------
def upload_to_drive(file_path, file_name, folder_id):
    """
    생성된 이미지 파일을 Google Drive 지정 폴더에 업로드하고
    공개 공유 링크(URL)를 반환합니다.
    """
    try:
        creds = Credentials.from_service_account_info(
            json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
        )
        service = build("drive", "v3", credentials=creds)

        # 🔹 업로드할 메타데이터
        file_metadata = {
            "name": file_name,
            "parents": [folder_id]
        }
        media = MediaFileUpload(file_path, mimetype="image/jpeg")

        # 🔹 파일 업로드
        uploaded = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id"
        ).execute()

        # 🔹 모든 사용자가 열람 가능하도록 권한 부여
        service.permissions().create(
            fileId=uploaded["id"],
            body={"type": "anyone", "role": "reader"}
        ).execute()

        # 🔹 공유 링크 반환
        return f"https://drive.google.com/file/d/{uploaded['id']}/view?usp=sharing"

    except Exception as e:
        print(f"❌ Google Drive 업로드 실패: {e}")
        return None

# ---------------------- 인수증 생성 ----------------------
def generate_receipt(materials, giver, receiver, giver_sign, receiver_sign):
    from PIL import Image, ImageDraw, ImageFont
    from io import BytesIO
    import base64, os
    from datetime import datetime

    width, height = 1240, 1754
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    title_font = ImageFont.truetype(font_path, 60)
    bold_font = ImageFont.truetype(font_path, 34)
    small_font = ImageFont.truetype(font_path, 22)

    draw.text((480, 100), "자재 인수증", font=title_font, fill="black")
    draw.text((100, 200), f"작성일자: {datetime.now().strftime('%Y-%m-%d %H:%M')}", font=bold_font, fill="black")

    y = 300
    headers = ["통신방식", "구분", "신철", "수량", "박스번호"]
    positions = [100, 400, 600, 800, 1000]
    draw.rectangle((80, y, 1160, y + 55), outline="black", fill="#E8F0FE")

    for i, h in enumerate(headers):
        draw.text((positions[i], y + 10), h, font=bold_font, fill="black")

    y += 70
    for m in materials:
        for i, key in enumerate(headers):
            val = m.get(key, "")
            draw.text((positions[i], y), str(val), font=bold_font, fill="black")
        y += 50

    draw.rectangle((80, 300, 1160, y), outline="black")

    # ---------------------- ✅ 서명 이미지 처리 ----------------------
    def decode_sign(s):
        """Base64 → RGBA 이미지 변환"""
        try:
            s = s.split(",")[1] if "," in s else s
            if not s:
                return None
            img = Image.open(BytesIO(base64.b64decode(s)))
            return img.convert("RGBA")  # RGBA 모드로 통일
        except Exception:
            return None

    giver_img = decode_sign(giver_sign)
    receiver_img = decode_sign(receiver_sign)

    footer_y = height - 150
    draw.text((200, footer_y - 40), f"주는 사람: {giver} (인)", font=bold_font, fill="black")
    draw.text((800, footer_y - 40), f"받는 사람: {receiver} (인)", font=bold_font, fill="black")

    # ---------------------- ✅ RGBA 병합 ----------------------
    if giver_img:
        giver_resized = giver_img.resize((260, 120))
        temp_giver = Image.new("RGBA", img.size, (255, 255, 255, 0))
        temp_giver.paste(giver_resized, (240, footer_y - 190), giver_resized)
        img = Image.alpha_composite(img.convert("RGBA"), temp_giver)

    if receiver_img:
        receiver_resized = receiver_img.resize((260, 120))
        temp_receiver = Image.new("RGBA", img.size, (255, 255, 255, 0))
        temp_receiver.paste(receiver_resized, (840, footer_y - 190), receiver_resized)
        img = Image.alpha_composite(img.convert("RGBA"), temp_receiver)

    # ---------------------- ✅ Google Drive 업로드 ----------------------
    tmp_filename = f"/tmp/receipt_{receiver}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    img = img.convert("RGB")
    img.save(tmp_filename, "JPEG", quality=95)

    # 🔹 Google Drive 폴더 ID (직접 입력)
    DRIVE_FOLDER_ID = "1pTwc4KQ4FylM-7vG8cYGOICNUzOHbj9N"  # 예: '1a2B3C4D5E6F7G8H9'

    # 🔹 업로드 실행
    drive_link = upload_to_drive(tmp_filename, os.path.basename(tmp_filename), DRIVE_FOLDER_ID)

    # ---------------------- ✅ 링크 반환 ----------------------
    return drive_link or "구글 드라이브 업로드 실패"


# ---------------------- 로그아웃 ----------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))



# ---------------------- 구글시트 저장 ----------------------
def save_to_sheets(materials, giver, receiver):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for m in materials:
        records_sheet.append_row([
            m["통신방식"], m["구분"], giver, receiver,
            m["신철"], m["수량"], m["박스번호"], now
        ])


# ---------------------- 서버 실행 ----------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)





