import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import re

# Hiển thị logo
st.image("/mnt/data/logo_hinh_tron.png", width=150)

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
    st.error("❌ Không tìm thấy google_service_account trong secrets. Vui lòng cấu hình.")
    st.stop()

openai_api_key_direct = "sk-proj-..."

if openai_api_key_direct:
    client_ai = OpenAI(api_key=openai_api_key_direct)
    st.success("✅ Đã kết nối OpenAI API key.")
else:
    client_ai = None
    st.warning("⚠️ Chưa cấu hình API key OpenAI. Vui lòng thêm vào st.secrets.")

def get_sheet_data(sheet_name):
    try:
        spreadsheet_url = "https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit"
        sheet = client.open_by_url(spreadsheet_url).worksheet(sheet_name)
        return sheet.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Không tìm thấy sheet '{sheet_name}'. Vui lòng kiểm tra tên sheet.")
        return None
    except Exception as e:
        st.error(f"❌ Lỗi khi mở Google Sheet '{sheet_name}': {e}")
        return None

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
                    st.success(f"✅ Đã hiển thị dữ liệu từ sheet '{sheet_name_from_query}'.")
                else:
                    st.warning(f"⚠️ Sheet '{sheet_name_from_query}' không có dữ liệu.")
        else:
            st.warning("⚠️ Vui lòng cung cấp tên sheet rõ ràng.")

    elif any(k in user_msg_lower for k in ["lãnh đạo xã", "lãnh đạo phường", "lãnh đạo định hóa", "danh sách lãnh đạo"]):
        records = get_sheet_data("Danh sách lãnh đạo xã, phường")
        if records:
            df_lanhdao = pd.DataFrame(records)
            location_name = None
            match_xa_phuong = re.search(r"(xã|phường)\s+([a-zA-Z0-9\s]+)", user_msg_lower)
            if match_xa_phuong:
                location_name = match_xa_phuong.group(2).strip()
            elif "định hóa" in user_msg_lower:
                location_name = "định hóa"

            filtered_df_lanhdao = df_lanhdao
            if location_name and 'Thuộc xã/phường' in df_lanhdao.columns:
                filtered_df_lanhdao = df_lanhdao[df_lanhdao['Thuộc xã/phường'].astype(str).str.lower().str.contains(location_name.lower(), na=False)]

                if filtered_df_lanhdao.empty:
                    st.warning(f"⚠️ Không tìm thấy lãnh đạo nào cho '{location_name.title()}'.")
                    st.dataframe(df_lanhdao)

            if not filtered_df_lanhdao.empty:
                st.subheader(f"Dữ liệu từ sheet 'Danh sách lãnh đạo xã, phường' {'cho ' + location_name.title() if location_name else ''}:")
                st.dataframe(filtered_df_lanhdao)
            else:
                st.warning("⚠️ Dữ liệu từ sheet 'Danh sách lãnh đạo xã, phường' rỗng.")
        else:
            st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet 'Danh sách lãnh đạo xã, phường'.")

    elif "tba" in user_msg_lower or "thông tin tba" in user_msg_lower:
        records = get_sheet_data("Tên các TBA")
        if records:
            df_tba = pd.DataFrame(records)
            line_name = None
            line_match = re.search(r"đường dây\s+([a-zA-Z0-9\.]+)", user_msg_lower)
            if line_match:
                line_name = line_match.group(1).upper()

            filtered_df_tba = df_tba
            if line_name and 'Tên đường dây' in df_tba.columns:
                filtered_df_tba = df_tba[df_tba['Tên đường dây'].astype(str).str.upper() == line_name]

                if filtered_df_tba.empty:
                    st.warning(f"⚠️ Không tìm thấy TBA nào cho đường dây '{line_name}'.")
                    st.dataframe(df_tba)

            if not filtered_df_tba.empty:
                st.subheader(f"Dữ liệu từ sheet 'Tên các TBA' {'cho đường dây ' + line_name if line_name else ''}:")
                st.dataframe(filtered_df_tba)
            else:
                st.warning("⚠️ Dữ liệu từ sheet 'Tên các TBA' rỗng.")
        else:
            st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet 'Tên các TBA'.")

    else:
        if client_ai:
            try:
                response = client_ai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "Bạn là trợ lý ảo hỗ trợ Đội QLĐLKV Định Hóa."},
                        {"role": "user", "content": user_msg}
                    ]
                )
                st.write(response.choices[0].message.content)
            except Exception as e:
                st.error(f"❌ Lỗi khi gọi OpenAI: {e}.")
        else:
            st.warning("⚠️ Không có API key OpenAI.")
