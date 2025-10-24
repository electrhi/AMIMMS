from PIL import Image, ImageDraw, ImageFont
import base64, io, datetime, os

def generate_receipt(material_name, quantity, box_count, box_number, giver, receiver, giver_sign, receiver_sign, date_str):
    width, height = 800, 600
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    title_font = ImageFont.load_default()
    text_font = ImageFont.load_default()

    draw.text((50, 30), "자재 인수증", fill="black", font=title_font)
    draw.text((50, 80), f"자재명: {material_name}", fill="black", font=text_font)
    draw.text((50, 110), f"수량: {quantity}", fill="black", font=text_font)
    draw.text((50, 140), f"박스수량: {box_count}", fill="black", font=text_font)
    draw.text((50, 170), f"박스번호: {box_number}", fill="black", font=text_font)
    draw.text((50, 200), f"날짜: {date_str}", fill="black", font=text_font)

    # 서명 이미지 디코딩
    giver_img = Image.open(io.BytesIO(base64.b64decode(giver_sign.split(",")[1]))).resize((250,100))
    receiver_img = Image.open(io.BytesIO(base64.b64decode(receiver_sign.split(",")[1]))).resize((250,100))

    draw.text((50, 330), f"주는사람: {giver}", fill="black", font=text_font)
    img.paste(giver_img, (180, 310))
    draw.text((50, 480), f"받는사람: {receiver}", fill="black", font=text_font)
    img.paste(receiver_img, (180, 460))

    filename = f"receipt_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    path = os.path.join("static", filename)
    img.save(path, "JPEG")
    return path
