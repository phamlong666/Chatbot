import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import openai
import json

# Kết nối Google Sheets bằng secrets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
info = st.secrets["google_service_account"]  # Đọc từ secrets của Streamlit
creds = Credentials.from_service_account_info(info, scopes=SCOPES)
client = gspread.authorize(creds)

# Mở sheet
sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit").worksheet("CBCNV")

# Config OpenAI
openai.api_key = st.secrets["openai_api_key"]

st.title("🤖 Trợ lý Điện lực Định Hóa")

user_msg = st.text_input("Bạn muốn hỏi gì?")

if st.button("Gửi"):
    if "cbcnv" in user_msg.lower() or "danh sách" in user_msg.lower():
        records = sheet.get_all_records()
        reply_list = []
        for r in records:
            try:
                reply_list.append(
                    f"{r['Họ và tên']} - {r['Ngày sinh CBCNV']} - {r['Trình độ chuyên môn']} - "
                    f"{r['Tháng năm vào ngành']} - {r['Bộ phận công tác']} - {r['Chức danh']}"
                )
            except KeyError:
                continue
        reply_text = "\n".join(reply_list)
        st.text_area("Kết quả", value=reply_text, height=300)
    else:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Bạn là trợ lý EVN hỗ trợ mọi câu hỏi."},
                {"role": "user", "content": user_msg}
            ]
        )
        st.write(response.choices[0].message.content)
