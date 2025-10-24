from flask import Flask, render_template, request, redirect, url_for, session, send_file
from PIL import Image, ImageDraw, ImageFont
import base64
from io import BytesIO
from datetime import datetime
import os
import pandas as pd
from openpyxl import Workbook, load_workbook
import bcrypt

app = Flask(__name__)
app.secret_key = "kdn_secret_key"

# -------------------------------
# 로그인 페이지 (bcrypt + 엑셀 연동)
# -------------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    user_file = "static/data/users.xlsx"
    os.makedirs("static/data", exist_ok=True)

    if not os.path.exists(user_file):
        password_hash = bcrypt.hashpw("1234".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        df = pd.DataFrame([{"ID": "admin", "PASSWORD": password_hash}])
        df.to_excel(user_file, index=False)

    df = pd.read_excel(user_file)
    users = {str(row["ID"]).strip(): str(row["PASSWORD"]).strip() for _, row in df.iterrows()}

    if request.method == "POST":
        user_id = request.form.get("user_id", "").strip()
        password = request.form.get("password", "").strip()

        if user_id in users and bcrypt.checkpw(password.encode("utf-8"), users[user_id].encode("utf-8")):
            session.clear()
            session["logged_in"] = True
            session["user_id"] = user_id
            return redirect(url_for("menu"))
        else:
            return render_template("login.html", error="아이디 또는 비밀번호가 올바르지 않습니다.")
    return render_template("login.html")

# -------------------------------
@app.route("/menu")
def menu():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    user_id = session.get("user_id", "Unknown")
    return render_template("menu.html", user_id=user_id)

# -------------------------------
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
            if not 수량[i].strip():
                continue
            materials.append({
                "통신방식": 통신방식[i],
                "구분": 구분[i],
                "신철": 신철[i],
                "수량": 수량[i],
                "박스번호": 박스번호[i]
            })
        session["materials"] = materials
        return redirect(url_for("confirm"))
    materials = session.get("materials", [])
    return render_template("form.html", materials=materials)

# -------------------------------
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
        save_to_excel(materials, giver, receiver)
        session.pop("materials", None)
        return render_template("receipt_result.html", receipt_path=receipt_path)
    return render_template("confirm.html", materials=materials, logged_user=logged_user)

# -------------------------------
@app.route("/summary")
def summary():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    file_path = "static/data/material_records.xlsx"
    summary_data = {}
    if os.path.exists(file_path):
        wb = load_workbook(file_path)
        ws = wb.active
        for row in ws.iter_rows(min_row=2, values_only=True):
            통신방식, 구분, 주는사람, 받는사람, 신철, 수량, 박스번호, 작성일자 = row
            key = f"{통신방식} / {구분}"
            if 받는사람 == session.get("user_id"):
                if key not in summary_data:
                    summary_data[key] = {"합계": 0, "박스수": 0}
                summary_data[key]["합계"] += int(수량)
                summary_data[key]["박스수"] += 1
    return render_template("summary.html", summary_data=summary_data)

# -------------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------------------------------
def generate_receipt(materials, giver, receiver, giver_sign, receiver_sign):
    width, height = 1240, 1754
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if not os.name == "nt" else "C:/Windows/Fonts/malgun.ttf"
    title_font = ImageFont.truetype(font_path, 60)
    bold_font = ImageFont.truetype(font_path, 34)
    small_font = ImageFont.truetype(font_path, 22)
    logo_path = "static/kdn_logo.png"
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).resize((220, 100))
        img.paste(logo, (80, 70))
    title_text = "자재 인수증"
    title_w = draw.textlength(title_text, font=title_font)
    draw.text(((width - title_w) / 2, 100), title_text, font=title_font, fill="black")
    draw.text((80, 220), f"작성일자: {datetime.now().strftime('%Y-%m-%d %H:%M')}", font=bold_font, fill="black")
    y = 300
    headers = ["통신방식", "구분", "신/철", "수량", "박스번호"]
    positions = [100, 400, 600, 800, 1000]
    draw.rectangle((80, y, 1160, y + 55), outline="black", fill="#E8F0FE")
    for i, h in enumerate(headers):
        draw.text((positions[i], y + 10), h, font=bold_font, fill="black")
    y += 70
    for m in materials:
        draw.text((positions[0], y), m["통신방식"], font=bold_font, fill="black")
        draw.text((positions[1], y), m["구분"], font=bold_font, fill="black")
        draw.text((positions[2], y), m["신철"], font=bold_font, fill="black")
        draw.text((positions[3], y), str(m["수량"]), font=bold_font, fill="black")
        draw.text((positions[4], y), str(m["박스번호"]), font=bold_font, fill="black")
        y += 50
    draw.rectangle((80, 300, 1160, y), outline="black")

    def decode_signature(sign_data):
        if not sign_data:
            return None
        sign_data = sign_data.split(",")[1]
        sign_img = Image.open(BytesIO(base64.b64decode(sign_data))).convert("RGBA")
        return sign_img

    giver_img = decode_signature(giver_sign)
    receiver_img = decode_signature(receiver_sign)
    footer_y = height - 150
    draw.text((200, footer_y - 40), f"주는 사람: {giver} (인)", font=bold_font, fill="black")
    draw.text((800, footer_y - 40), f"받는 사람: {receiver} (인)", font=bold_font, fill="black")
    if giver_img:
        giver_img = giver_img.resize((260, 120))
        img.paste(giver_img, (240, footer_y - 190), giver_img)
    if receiver_img:
        receiver_img = receiver_img.resize((260, 120))
        img.paste(receiver_img, (840, footer_y - 190), receiver_img)
    draw.text((width // 2 - 250, height - 80), "한전KDN 주식회사 | AMI 자재관리시스템", font=small_font, fill="gray")
    filename = f"static/receipts/AMI인수증_{receiver}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    img.save(filename, "JPEG", quality=95)
    return filename

# -------------------------------
def save_to_excel(materials, giver, receiver):
    os.makedirs("static/data", exist_ok=True)
    file_path = "static/data/material_records.xlsx"
    if os.path.exists(file_path):
        wb = load_workbook(file_path)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.append(["통신방식", "구분", "주는사람", "받는사람", "신/철", "수량", "박스번호", "작성일자"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for m in materials:
        ws.append([m["통신방식"], m["구분"], giver, receiver, m["신철"], m["수량"], m["박스번호"], now])
    wb.save(file_path)

# -------------------------------
@app.route("/download_receipt")
def download_receipt():
    folder = "static/receipts"
    if not os.path.exists(folder):
        return "인수증 파일이 존재하지 않습니다.", 404
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".jpg")]
    if not files:
        return "인수증 파일이 존재하지 않습니다.", 404
    latest_file = max(files, key=os.path.getctime)
    return send_file(latest_file, as_attachment=True)

# -------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
