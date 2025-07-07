from flask import Flask, request, jsonify
import gspread
from google.oauth2.service_account import Credentials
import openai

app = Flask(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file("sotaygpt-fba5e9b3e6fd.json", scopes=SCOPES)
client = gspread.authorize(creds)
sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit").worksheet("CBCNV")

openai.api_key = "YOUR_OPENAI_API_KEY"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    user_msg = data.get("message", "").lower()

    if "cbcnv" in user_msg or "danh sách" in user_msg:
        records = sheet.get_all_records()
        reply_list = []

        bo_phan = None
        if "tổ" in user_msg:
            split_msg = user_msg.split("tổ")
            if len(split_msg) > 1:
                bo_phan = split_msg[1].strip().upper()

        for r in records:
            bo_phan_cell = str(r.get('Bộ phận công tác', '')).upper()
            if bo_phan:
                if bo_phan in bo_phan_cell:
                    reply_list.append(
                        f"{r.get('Họ và tên', '')} - {r.get('Ngày sinh CBCNV', '')} - {r.get('Trình độ chuyên môn', '')} - "
                        f"{r.get('Tháng năm vào ngành', '')} - {r.get('Bậc lương đang hưởng', '')} - "
                        f"{r.get('Bộ phận công tác', '')} - {r.get('Chức danh', '')}"
                    )
            else:
                reply_list.append(
                    f"{r.get('Họ và tên', '')} - {r.get('Ngày sinh CBCNV', '')} - {r.get('Trình độ chuyên môn', '')} - "
                    f"{r.get('Tháng năm vào ngành', '')} - {r.get('Bậc lương đang hưởng', '')} - "
                    f"{r.get('Bộ phận công tác', '')} - {r.get('Chức danh', '')}"
                )

        reply_text = "\n".join(reply_list) or "Không tìm thấy nhân viên nào."
        return jsonify({"reply": reply_text})

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
