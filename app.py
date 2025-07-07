from flask import Flask, request, jsonify
import gspread
from google.oauth2.service_account import Credentials
import openai

# Cấu hình Flask
app = Flask(__name__)

# Kết nối Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file("sotaygpt-fba5e9b3e6fd.json", scopes=SCOPES)
client = gspread.authorize(creds)
sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/13MqQzv3MF9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit").worksheet("CBCNV")

# Cấu hình OpenAI (nếu có, để trả lời các câu hỏi khác)
openai.api_key = "YOUR_OPENAI_API_KEY"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    user_msg = data.get("message", "").lower()

    # Kiểm tra nếu câu hỏi liên quan đến CBCNV
    if "danh sách" in user_msg or "cbcnv" in user_msg:
        records = sheet.get_all_records()
        reply_list = []
        for r in records:
            reply_list.append(
                f"{r['Họ và tên']} - {r['Ngày sinh CBCNV']} - {r['Trình độ chuyên môn']} - "
                f"{r['Tháng năm vào ngành']} - {r['Bậc lương đang hưởng']} - "
                f"{r['Bộ phận công tác']} - {r['Chức danh']}"
            )
        reply_text = "\n".join(reply_list)
        return jsonify({"reply": reply_text})

    # Nếu không phải, gửi sang GPT
    else:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Bạn là trợ lý EVN hỗ trợ mọi câu hỏi."},
                {"role": "user", "content": data.get("message", "")}
            ]
        )
        gpt_reply = response.choices[0].message.content
        return jsonify({"reply": gpt_reply})

if __name__ == '__main__':
    app.run(port=5000)
