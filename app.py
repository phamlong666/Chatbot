import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import re
import os
from PIL import Image

plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['font.size'] = 10
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['xtick.labelsize'] = 10
plt.rcParams['ytick.labelsize'] = 10
plt.rcParams['figure.titlesize'] = 16

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

if "google_service_account" in st.secrets:
    info = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
else:
    st.error("(Error) Không tìm thấy google_service_account trong secrets. Vui lòng cấu hình.")
    st.stop()

openai_api_key_direct = st.secrets.get("openai_api_key")

if openai_api_key_direct:
    client_ai = OpenAI(api_key=openai_api_key_direct)
    st.success("(Success) Đã kết nối OpenAI API key.")
else:
    client_ai = None
    st.warning("(Warning) Chưa cấu hình API key OpenAI. Vui lòng thêm vào st.secrets.")

def get_sheet_data(sheet_name):
    try:
        spreadsheet_url = "https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit"
        sheet = client.open_by_url(spreadsheet_url).worksheet(sheet_name)
        return sheet.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"(Error) Không tìm thấy sheet '{sheet_name}'. Vui lòng kiểm tra tên sheet.")
        return None
    except Exception as e:
        st.error(f"(Error) Lỗi khi mở Google Sheet '{sheet_name}': {e}")
        return None

logo_path = "logo_hinh_tron.jpg"

uploaded_logo = st.sidebar.file_uploader("Tải logo (jpg/png)", type=["jpg", "png"])
if uploaded_logo:
    st.sidebar.image(uploaded_logo, width=75)
    with open(logo_path, "wb") as f:
        f.write(uploaded_logo.read())
elif os.path.exists(logo_path):
    with open(logo_path, "rb") as f:
        st.sidebar.image(f.read(), width=75)
else:
    st.sidebar.warning(f"(Warning) Không tìm thấy file logo tại đường dẫn: {logo_path}. Vui lòng tải lên.")

st.title("🤖 Chatbot Đội QLĐLKV Định Hóa")

user_msg = st.text_input("Bạn muốn hỏi gì?")

if st.button("Gửi"):
    user_msg_lower = user_msg.lower()

    if "lấy dữ liệu sheet" in user_msg_lower:
        match = re.search(r"lấy dữ liệu sheet\s+['\"]?([^'\"]+)['\"]?", user_msg_lower)
        if match:
            sheet_name_from_query = match.group(1).strip()
            st.info(f"Đang cố gắng lấy dữ liệu từ sheet: **{sheet_name_from_query}**")
            records = get_sheet_data(sheet_name_from_query)
            if records:
                df_any_sheet = pd.DataFrame(records)
                if not df_any_sheet.empty:
                    st.subheader(f"Dữ liệu từ sheet '{sheet_name_from_query}':")
                    st.dataframe(df_any_sheet)
                    st.success(f"(Success) Đã hiển thị dữ liệu từ sheet '{sheet_name_from_query}'.")
                else:
                    st.warning(f"(Warning) Sheet '{sheet_name_from_query}' không có dữ liệu.")
        else:
            st.warning("(Warning) Vui lòng cung cấp tên sheet rõ ràng. Ví dụ: 'lấy dữ liệu sheet DoanhThu'.")

    else:
        if client_ai:
            try:
                response = client_ai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "Bạn là trợ lý ảo của Đội QLĐLKV Định Hóa."},
                        {"role": "user", "content": user_msg}
                    ]
                )
                st.write(response.choices[0].message.content)
            except Exception as e:
                st.error(f"(Error) Lỗi khi gọi OpenAI: {e}. Vui lòng kiểm tra API key hoặc quyền truy cập mô hình.")
        else:
            st.warning("(Warning) Không có API key OpenAI. Vui lòng thêm vào st.secrets.")
