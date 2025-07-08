import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import openai

# Cấu hình Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file("sotaygpt-fba5e9b3e6fd.json", scopes=SCOPES)
client = gspread.authorize(creds)
sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit").worksheet("CBCNV")

# Cấu hình OpenAI
openai.api_key = st.secrets["OPENAI_API_KEY"]

st.title("🤖 EVN Assistant Chatbot")

user_input = st.text_input("Nhập câu hỏi hoặc yêu cầu:", "Danh sách CBCNV Tổ QLVH")

if st.button("Gửi"):
    if "danh sách" in user_input.lower() or "cbcnv" in user_input.lower():
        records = sheet.get_all_records()
        filtered = [r for r in records if "QLVH" in r['Bộ phận công tác']]
        if filtered:
            for r in filtered:
                st.write(f"**{r['Họ và tên']}** | {r['Ngày sinh CBCNV']} | {r['Trình độ chuyên môn']} | {r['Bộ phận công tác']} | {r['Chức danh']}")
        else:
            st.write("Không tìm thấy nhân viên phù hợp.")
    else:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Bạn là trợ lý EVN hỗ trợ kỹ thuật, quản trị và đoàn thể."},
                {"role": "user", "content": user_input}
            ]
        )
        st.write(response.choices[0].message.content)
