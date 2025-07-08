import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI

# Kết nối Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

if "google_service_account" in st.secrets:
    info = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
else:
    st.error("❌ Không tìm thấy google_service_account trong secrets.")

# Lấy API key OpenAI từ secrets
openai_api_key_direct = st.secrets.get("openai_api_key", "")

if openai_api_key_direct:
    try:
        client_ai = OpenAI(api_key=openai_api_key_direct)
        st.success("✅ Đã kết nối OpenAI API key.")
    except Exception as e:
        client_ai = None
        st.error(f"❌ Lỗi khi khởi tạo OpenAI: {e}")
else:
    client_ai = None
    st.warning("⚠️ Chưa cấu hình API key OpenAI. Vui lòng thêm vào st.secrets.")

# Hàm chọn sheet động
def get_sheet_name(msg):
    msg_lower = msg.lower()
    if "tổn thất" in msg_lower:
        return "TonThat"
    elif "sự cố" in msg_lower:
        return "SuCo"
    elif "công đoàn" in msg_lower:
        return "CongDoan"
    elif "atvsv" in msg_lower:
        return "ATVSV"
    elif "kinh doanh" in msg_lower:
        return "KinhDoanh"
    else:
        return "CBCNV"

st.title("🤖 Trợ lý Điện lực Định Hóa")

user_msg = st.text_input("Bạn muốn hỏi gì?")

if st.button("Gửi") and user_msg:
    sheet_name = get_sheet_name(user_msg)

    try:
        sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit").worksheet(sheet_name)
        records = sheet.get_all_records()

        reply_list = []
        bo_phan = None

        for keyword in ["tổ ", "phòng ", "đội "]:
            if keyword in user_msg.lower():
                bo_phan = user_msg.lower().split(keyword, 1)[1].strip()
                break

        for r in records:
            if bo_phan and bo_phan not in r.get('Bộ phận công tác', '').lower():
                continue
            reply_list.append(
                f"{r.get('Họ và tên', '')} - {r.get('Ngày sinh CBCNV', '')} - {r.get('Trình độ chuyên môn', '')} - "
                f"{r.get('Tháng năm vào ngành', '')} - {r.get('Bộ phận công tác', '')} - {r.get('Chức danh', '')}"
            )

        if reply_list:
            reply_text = "\n".join(reply_list)
            st.text_area("Kết quả", value=reply_text, height=300)
        else:
            st.warning("⚠️ Không tìm thấy dữ liệu phù hợp. Kiểm tra tên bộ phận hoặc từ khóa.")

    except Exception as e:
        st.error(f"❌ Lỗi khi truy cập sheet '{sheet_name}': {e}")

    if client_ai and (not reply_list):
        try:
            response = client_ai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Bạn là trợ lý EVN hỗ trợ trả lời các câu hỏi kỹ thuật, nghiệp vụ, đoàn thể và cộng đồng."},
                    {"role": "user", "content": user_msg}
                ]
            )
            st.write(response.choices[0].message.content)
        except Exception as e:
            st.error(f"❌ Lỗi khi gọi OpenAI: {e}")
    elif not client_ai:
        st.warning("⚠️ Không có API key OpenAI. Vui lòng thêm vào st.secrets để sử dụng chatbot.")
