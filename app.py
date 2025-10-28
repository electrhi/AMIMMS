from flask import Flask, render_template, request, redirect, url_for, session
from datetime import datetime, timedelta
from io import BytesIO
import base64, os, qrcode, socket, gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import json
from googleapiclient.discovery import build
from google.cloud import storage

# ✅ Pillow Import 안정화
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    from PIL import Image, ImageDraw, ImageFont

import ssl
import requests
ssl._create_default_https_context = ssl._create_unverified_context  # ✅ SSL 검증 우회 (Google API만)
requests.adapters.DEFAULT_RETRIES = 5


# ---------------------- Flask 초기화 ----------------------
app = Flask(__name__)
app.secret_key = "kdn_secret_key"

# ---------------------- Google Sheets 연결 ----------------------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDS = Credentials.from_service_account_info(
    json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON")), scopes=SCOPES
)
gc = gspread.authorize(CREDS)

USERS_SHEET_KEY = os.getenv("GOOGLE_USERS_SHEET_KEY")
RECORDS_SHEET_KEY = os.getenv("GOOGLE_RECORDS_SHEET_KEY")

users_sheet = gc.open_by_key(USERS_SHEET_KEY).sheet1
records_sheet = gc.open_by_key(RECORDS_SHEET_KEY).sheet1

# ---------------------- 로그인 ----------------------
@app.route("/", methods=["GET", "POST"])
def login():
    df = pd.DataFrame(users_sheet.get_all_records())

    # AUTHORITY 열이 없을 경우 기본 n으로 채움
    if "AUTHORITY" not in df.columns:
        df["AUTHORITY"] = "n"

    # 사용자 정보 딕셔너리 생성
    users = {
        row["ID"]: {"pw": row["PASSWORD"], "auth": row["AUTHORITY"]}
        for _, row in df.iterrows()
    }

    if request.method == "POST":
        user_id = request.form["user_id"].strip()
        pw = request.form["password"].strip()

        if user_id in users and users[user_id]["pw"] == pw:
            session["logged_in"] = True
            session["user_id"] = user_id
            session["authority"] = users[user_id]["auth"]  # ✅ 권한 저장
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

        save_to_sheets(materials, giver, receiver)
        session.pop("materials", None)
        return render_template("receipt_result.html", giver=giver, receiver=receiver)
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

# ---------------------- ✅ 종합관리표 (관리자 전용) ----------------------
@app.route("/admin_summary")
def admin_summary():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    # 권한 검사
    if session.get("authority") != "y":
        return render_template("menu.html", user_id=session["user_id"], error="접근 권한이 없습니다.")

    df = pd.DataFrame(records_sheet.get_all_records())
    if df.empty:
        return render_template("admin_summary.html", table_html=None, message="데이터가 없습니다.")

    df["수량"] = pd.to_numeric(df["수량"], errors="coerce").fillna(0).astype(int)

    # 주는사람 기준, 받는사람/구분별 합계표 생성
    pivot = df.pivot_table(
        index="주는사람",
        columns=["받는사람", "구분"],
        values="수량",
        aggfunc="sum",
        fill_value=0,
    )
    pivot["합계"] = pivot.sum(axis=1)
    total_row = pivot.sum(axis=0)
    total_row.name = "합계"
    pivot = pd.concat([pivot, total_row.to_frame().T])

    table_html = pivot.to_html(classes="table table-bordered table-striped", border=0)
    return render_template("admin_summary.html", table_html=table_html)

# ---------------------- 구글시트 저장 ----------------------
def save_to_sheets(materials, giver, receiver):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for m in materials:
        records_sheet.append_row([
            m["통신방식"], m["구분"], giver, receiver,
            m["신철"], m["수량"], m["박스번호"], now
        ])

# ---------------------- 로그아웃 ----------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------------- 서버 실행 ----------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

