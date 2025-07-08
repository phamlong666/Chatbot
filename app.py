import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import openai

# Kết nối Google Sheets bằng secrets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

st.write("Available secrets keys:", list(st.secrets.keys()))

if "google_service_account" in st.secrets:
    info = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
else:
    st.error("Không tìm thấy google_service_account trong secrets. Vui lòng kiểm tra lại.")

if "openai_api_key" in st.secrets:
    client_ai = openai.OpenAI(api_key=st.secrets["openai_api_key"])
else:
    st.warning("Chưa cấu hình openai_api_key. Chỉ chạy chức năng Google Sheets.")
    client_ai = None

try:
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit").worksheet("CBCNV")
except Exception as e:
    st.error(f"Không mở được Google Sheet: {e}")

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
        if client_ai:
            response = client_ai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Bạn là trợ lý EVN hỗ trợ mọi câu hỏi."},
                    {"role": "user", "content": user_msg}
                ]
            )
            st.write(response.choices[0].message.content)
        else:
            st.warning("Không có API key OpenAI. Vui lòng thêm để sử dụng chức năng chat.")
