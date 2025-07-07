
from flask import Flask, request, jsonify
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

# Kết nối Google Sheets
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file("sotaygpt-fba5e9b3e6fd.json", scopes=scopes)
client = gspread.authorize(creds)
spreadsheet = client.open_by_url("https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit")

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    user_msg = data.get("message", "").lower()

    try:
        sheet = spreadsheet.worksheet("CBCNV")
        records = sheet.get_all_records()
    except Exception as e:
        return jsonify({"reply": f"Lỗi: Không thể mở sheet CBCNV. Chi tiết: {e}"})

    # Tìm nhân viên nếu tên trong câu hỏi
    matched_records = []
    for r in records:
        name = r.get("Họ và tên", "").lower()
        if name and name in user_msg:
            matched_records.append(r)

    if matched_records:
        reply_list = []
        for r in matched_records:
            reply_list.append(
                f"{r.get('Họ và tên', '')} | Ngày sinh: {r.get('Ngày sinh CBCNV', '')} | Trình độ: {r.get('Trình độ chuyên môn', '')} | "
                f"Năm công tác: {r.get('Năm bắt đầu công tác', '')} | Bậc lương: {r.get('Bậc lương đang hưởng', '')} | Bộ phận: {r.get('Bộ phận công tác', '')} | "
                f"Chức danh: {r.get('Chức danh', '')}"
            )
        reply_text = "\n\n".join(reply_list)
        return jsonify({"reply": reply_text})
    else:
        # Nếu không tìm thấy, giả lập gọi GPT (ở đây trả câu mặc định demo)
        gpt_reply = "Câu hỏi của anh chưa có trong dữ liệu CBCNV. Đây là câu trả lời từ GPT: Anh vui lòng cung cấp thêm thông tin chi tiết nhé!"
        return jsonify({"reply": gpt_reply})

if __name__ == '__main__':
    app.run(port=5000)
