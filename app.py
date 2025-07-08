import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI

# Kết nối Google Sheets bằng secrets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

if "google_service_account" in st.secrets:
    info = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
else:
    st.error("Không tìm thấy google_service_account trong secrets. Vui lòng kiểm tra lại.")

# Gán trực tiếp API key OpenAI từ key mà anh đưa
openai_api_key_direct = "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"

client_ai = OpenAI(api_key=openai_api_key_direct)
st.success("✅ Đã kết nối OpenAI API key trực tiếp.")

try:
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit").worksheet("CBCNV")
except Exception as e:
    st.error(f"Không mở được Google Sheet: {e}")

st.title("🤖 Trợ lý Điện lực Định Hóa")

user_msg = st.text_input("Bạn muốn hỏi gì?")

if st.button("Gửi"):
    if "cbcnv" in user_msg.lower() or "danh sách" in user_msg.lower() or "tổ" in user_msg.lower() or "phòng" in user_msg.lower() or "đội" in user_msg.lower():
        records = sheet.get_all_records()
        reply_list = []

        # Lấy bộ phận được nhắc trong câu hỏi (nếu có)
        bo_phan = None
        for keyword in ["tổ ", "phòng ", "đội "]:
            if keyword in user_msg.lower():
                parts = user_msg.lower().split(keyword)
                if len(parts) > 1:
                    bo_phan = parts[1].strip()
                    break

        for r in records:
            try:
                if bo_phan and bo_phan not in r['Bộ phận công tác'].lower():
                    continue
                reply_list.append(
                    f"{r['Họ và tên']} - {r['Ngày sinh CBCNV']} - {r['Trình độ chuyên môn']} - "
                    f"{r['Tháng năm vào ngành']} - {r['Bộ phận công tác']} - {r['Chức danh']}"
                )
            except KeyError:
                continue

        if reply_list:
            reply_text = "\n".join(reply_list)
            st.text_area("Kết quả", value=reply_text, height=300)
        else:
            st.warning("⚠️ Không tìm thấy dữ liệu phù hợp.")
    else:
        if client_ai:
            try:
                response = client_ai.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "Bạn là trợ lý EVN hỗ trợ trả lời mọi câu hỏi kỹ thuật, nghiệp vụ, đoàn thể và cộng đồng."},
                        {"role": "user", "content": user_msg}
                    ]
                )
                st.write(response.choices[0].message.content)
            except Exception as e:
                st.error(f"Lỗi khi gọi OpenAI: {e}")
        else:
            st.warning("⚠️ Không có API key OpenAI. Vui lòng thêm để trả lời các câu hỏi tự do.")
