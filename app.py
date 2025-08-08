# -*- coding: utf-8 -*-
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import re
import os
from pathlib import Path
import fuzzywuzzy.fuzz as fuzz
import datetime
import easyocr
import json
import speech_recognition as sr
import tempfile
import numpy as np
from cryptography.fernet import Fernet
from audio_recorder_streamlit import audio_recorder
from difflib import get_close_matches
# Thêm import mới cho biểu đồ
import seaborn as sns
from oauth2client.service_account import ServiceAccountCredentials
import io # Thêm import io từ app1.py

# Cấu hình Streamlit page để sử dụng layout rộng
st.set_page_config(layout="wide")

# Cấu hình Matplotlib để hiển thị tiếng Việt
plt.rcParams['font.family'] = 'DejaVu Sans'
plt.rcParams['font.size'] = 14
plt.rcParams['axes.labelsize'] = 14
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['xtick.labelsize'] = 14
plt.rcParams['ytick.labelsize'] = 14
plt.rcParams['figure.titlesize'] = 16

# Kết nối Google Sheets với private key đã được mã hóa
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

if "gdrive_service_account" in st.secrets:
    try:
        encryption_key_for_decryption = st.secrets["gdrive_service_account"].get("encryption_key_for_decryption")
        encrypted_private_key = st.secrets["gdrive_service_account"].get("encrypted_private_key")

        if not encryption_key_for_decryption or not encrypted_private_key:
            raise ValueError("Thiếu encryption_key hoặc encrypted_private_key trong secrets.toml")

        f = Fernet(encryption_key_for_decryption.encode())
        decrypted_private_key = f.decrypt(encrypted_private_key.encode()).decode()

        info = {
            "type": st.secrets["gdrive_service_account"]["type"],
            "project_id": st.secrets["gdrive_service_account"]["project_id"],
            "private_key_id": st.secrets["gdrive_service_account"]["private_key_id"],
            "private_key": decrypted_private_key,
            "client_email": st.secrets["gdrive_service_account"]["client_email"],
            "client_id": st.secrets["gdrive_service_account"]["client_id"],
            "auth_uri": st.secrets["gdrive_service_account"]["auth_uri"],
            "token_uri": st.secrets["gdrive_service_account"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["gdrive_service_account"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["gdrive_service_account"]["client_x509_cert_url"]
        }

        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        client = gspread.authorize(creds)
        # Đã xóa dòng hiển thị thông báo kết nối thành công
        # st.success("✅ Đã kết nối Google Sheets thành công!")

    except Exception as e:
        st.error(f"❌ Lỗi khi giải mã hoặc kết nối Google Sheets: {e}. Vui lòng kiểm tra lại cấu hình secrets.toml.")
        st.stop()
else:
    st.error("❌ Không tìm thấy 'gdrive_service_account' trong secrets. Vui lòng cấu hình.")
    st.stop()

# Lấy API key OpenAI
openai_api_key = None
if "openai_api_key" in st.secrets:
    openai_api_key = st.secrets["openai_api_key"]
    st.success("✅ Đã kết nối OpenAI API key từ Streamlit secrets.")
else:
    pass # Không hiển thị cảnh báo nữa

if openai_api_key:
    client_ai = OpenAI(api_key=openai_api_key)
else:
    client_ai = None

spreadsheet_url = "https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit"

# Hàm để tìm tên cột chính xác, sử dụng fuzzy matching
def find_column_name(df, possible_names, threshold=80):
    """
    Tìm tên cột chính xác trong DataFrame từ một danh sách các tên có thể.
    Sử dụng fuzzy matching để tìm kiếm linh hoạt hơn.
    """
    df_cols = [col.strip().lower() for col in df.columns]
    for name in possible_names:
        name_lower = name.strip().lower()
        # Dùng fuzzy search để tìm tên cột phù hợp nhất
        matches = get_close_matches(name_lower, df_cols, n=1, cutoff=threshold/100)
        if matches:
            # Lấy tên cột gốc từ DataFrame
            original_col_name = df.columns[df_cols.index(matches[0])]
            return original_col_name
    return None

# Hàm để lấy dữ liệu từ một sheet cụ thể
def get_sheet_data(sheet_name):
    try:
        sheet = client.open_by_url(spreadsheet_url).worksheet(sheet_name)
        all_values = sheet.get_all_values()
        if all_values:
            headers = all_values[0]
            # Đảm bảo tiêu đề duy nhất
            seen_headers = {}
            unique_headers = []
            for h in headers:
                original_h = h
                count = seen_headers.get(h, 0)
                while h in seen_headers and seen_headers[h] > 0:
                    h = f"{original_h}_{count}"
                    count += 1
                seen_headers[original_h] = seen_headers.get(original_h, 0) + 1
                unique_headers.append(h)

            data = all_values[1:]
            df_temp = pd.DataFrame(data, columns=unique_headers)
            return df_temp
        else:
            return pd.DataFrame() # Return empty DataFrame if no values
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Không tìm thấy sheet '{sheet_name}'. Vui lòng kiểm tra tên sheet.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ Lỗi khi mở Google Sheet '{sheet_name}': {e}. Vui lòng kiểm tra định dạng tiêu đề của sheet. Nếu có tiêu đề trùng lặp, hãy đảm bảo chúng là duy nhất.")
        return pd.DataFrame()

# Tải dữ liệu từ sheet "Hỏi-Trả lời" một lần khi ứng dụng khởi động
qa_data = get_sheet_data("Hỏi-Trả lời")
qa_df = pd.DataFrame(qa_data) if qa_data is not None else pd.DataFrame() # Ensure qa_data is not None

# Hàm lấy dữ liệu từ tất cả sheet trong file
@st.cache_data
def load_all_sheets():
    spreadsheet = client.open_by_url(spreadsheet_url)
    sheet_names = [ws.title for ws in spreadsheet.worksheets()]
    data = {}
    for name in sheet_names:
        try:
            # Use get_sheet_data to handle specific sheet types
            df = get_sheet_data(name) 
            data[name] = df
        except Exception as e: # Catch any error during DataFrame creation
            st.warning(f"⚠️ Lỗi khi tải sheet '{name}': {e}. Đang bỏ qua sheet này.")
            data[name] = pd.DataFrame() # Ensure an empty DataFrame is returned on error
    return data

all_data = load_all_sheets()

# Hàm để đọc câu hỏi từ file JSON
def load_sample_questions(file_path="sample_questions.json"):
    try:
        # Đã thay đổi: Đọc file JSON thay vì sử dụng danh sách cố định
        with open(file_path, "r", encoding="utf-8") as f:
            questions_data = json.load(f)
        return questions_data
    except FileNotFoundError:
        st.error(f"❌ Lỗi: Không tìm thấy file câu hỏi mẫu tại đường dẫn: {file_path}. Vui lòng đảm bảo file 'sample_questions.json' nằm cùng thư mục với file app.py của bạn khi triển khai.")
        return []
    except json.JSONDecodeError:
        st.error(f"❌ Lỗi: File '{file_path}' không phải là định dạng JSON hợp lệ. Vui lòng kiểm tra lại nội dung file.")
        return []
    except Exception as e:
        st.error(f"❌ Lỗi khi đọc danh sách câu hỏi mẫu từ file: {e}")
        return []

# Tải các câu hỏi mẫu khi ứng dụng khởi động
sample_questions_from_file = load_sample_questions()


# --- Bắt đầu bố cục mới: Logo ở trái, phần còn lại của chatbot căn giữa ---

# Phần header: Logo và tiêu đề, được đặt ở đầu trang và logo căn trái
header_col1, header_col2 = st.columns([1, 8]) # Tỷ lệ cho logo và tiêu đề

with header_col1:
    public_logo_url = "https://raw.githubusercontent.com/phamlong666/Chatbot/main/logo_hinh_tron.png"
    try:
        st.image(public_logo_url, width=100) # Kích thước 100px
    except Exception as e_public_url:
        st.error(f"❌ Lỗi khi hiển thị logo từ URL: {e_public_url}. Vui lòng đảm bảo URL là liên kết TRỰC TIẾP đến file ảnh (kết thúc bằng .jpg, .png, v.v.) và kiểm tra kết nối internet.")
        logo_path = Path(__file__).parent / "logo_hinh_tron.jpg"
        try:
            if logo_path.exists():
                st.image(str(logo_path), width=100)
            else:
                st.error(f"❌ Không tìm thấy file ảnh logo tại: {logo_path}. Vui lòng đảm bảo file 'logo_hinh_tron.jpg' nằm cùng thư mục với file app.py của bạn khi triển khai.")
        except Exception as e_local_file:
            st.error(f"❌ Lỗi khi hiển thị ảnh logo từ file cục bộ: {e_local_file}.")

with header_col2:
    # Đã thay đổi st.title thành st.markdown để tùy chỉnh cỡ chữ
    st.markdown("<h1 style='font-size: 30px;'>🤖 Chatbot Đội QLĐLKV Định Hóa</h1>", unsafe_allow_html=True)

# Phần nội dung chính của chatbot (ô nhập liệu, nút, kết quả) sẽ được căn giữa
# Tạo 3 cột: cột trái rỗng (để tạo khoảng trống), cột giữa chứa nội dung chatbot, cột phải rỗng
# Đã thay đổi tỷ lệ từ [1, 3, 1] sang [1, 5, 1] để mở rộng không gian chat
col_left_spacer, col_main_content, col_right_spacer = st.columns([1, 5, 1])

with col_main_content: # Tất cả nội dung chatbot sẽ nằm trong cột này
    # Khởi tạo session state để lưu trữ tin nhắn cuối cùng đã xử lý
    if 'last_processed_user_msg' not in st.session_state:
        st.session_state.last_processed_user_msg = ""
    if 'qa_results' not in st.session_state:
        st.session_state.qa_results = []
    if 'qa_index' not in st.session_state:
        st.session_state.qa_index = 0
    if 'user_input_value' not in st.session_state: # Sử dụng user_input_value làm key chính cho input
        st.session_state.user_input_value = ""
    if 'current_qa_display' not in st.session_state: # NEW: To hold the currently displayed QA answer
        st.session_state.current_qa_display = ""
    # ✅ Ghi âm nằm ngoài form, xử lý trạng thái với session_state
    if "audio_processed" not in st.session_state:
        st.session_state.audio_processed = False

    audio_bytes = audio_recorder(
        text="🎙 Nhấn để nói",
        recording_color="#e8b62c",
        neutral_color="#6aa36f",
        icon_size="2x"
    )

    if audio_bytes and not st.session_state.audio_processed:
        st.info("⏳ Đang xử lý giọng nói...")
        audio_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                f.write(audio_bytes)
                audio_path = f.name

            recognizer = sr.Recognizer()
            with sr.AudioFile(audio_path) as source:
                audio_data = recognizer.record(source)
                try:
                    text = recognizer.recognize_google(audio_data, language="vi-VN")
                    st.success(f"📝 Văn bản: {text}")
                    st.session_state.user_input_value = text # Cập nhật giá trị input từ audio
                    st.session_state.audio_processed = True  # ✅ đánh dấu đã xử lý
                    st.rerun() # Rerun để cập nhật ô nhập liệu
                except sr.UnknownValueError:
                    st.warning("⚠️ Không nhận dạng được giọng nói.")
                except sr.RequestError as e:
                    st.error(f"❌ Lỗi nhận dạng: {e}")
                finally:
                    if audio_path and os.path.exists(audio_path):
                        os.remove(audio_path)
        except Exception as e:
            st.error(f"❌ Lỗi khi xử lý file âm thanh: {e}")

    # Bổ sung form bấm gửi/xóa ở dưới
    with st.form(key='chat_buttons_form'):
        mic_col, send_button_col, clear_button_col = st.columns([9, 1, 1])
        with mic_col:
            # Đây là ô nhập liệu chính hiện tại, giá trị được lấy từ session_state.user_input_value
            # Key của text_input giờ là user_input_value để nó tự động cập nhật session_state đó
            user_msg_input_in_form = st.text_input("Nhập lệnh hoặc dùng micro để nói:", value=st.session_state.get("user_input_value", ""), key="user_input_value")
        with send_button_col:
            send_button_pressed = st.form_submit_button("Gửi")
        with clear_button_col:
            clear_button_pressed = st.form_submit_button("Xóa")

    # Đọc câu hỏi mẫu từ file JSON
    sample_questions = load_sample_questions()

    # Callback function for selectbox
    def on_sample_question_select():
        # Khi một câu hỏi mẫu được chọn, cập nhật user_input_value
        st.session_state.user_input_value = st.session_state.selected_sample_question

    st.markdown("---")
    st.markdown("#### 🤔 Hoặc chọn câu hỏi mẫu:")
    # Thêm câu hỏi mẫu vào selectbox, dùng callback để cập nhật input
    st.selectbox(
        "Chọn một câu hỏi mẫu từ danh sách",
        options=[""] + sample_questions, # Thêm option rỗng ở đầu
        key="selected_sample_question",
        on_change=on_sample_question_select
    )
    
    # =========================================================================
    # Bổ sung handler từ app1.py
    # =========================================================================

    def _get_gspread_client():
        """Khởi tạo gspread client từ st.secrets['gdrive_service_account'].
        Tự động sửa \n trong private_key.
        """
        try:
            gsa = dict(st.secrets["gdrive_service_account"])  # copy
        except KeyError:
            st.error("❌ Không tìm thấy 'gdrive_service_account' trong Streamlit Secrets.")
            return None

        # Chuẩn hoá private_key
        if "private_key" in gsa and isinstance(gsa["private_key"], str):
            gsa["private_key"] = gsa["private_key"].replace("\\n", "\n")

        scope = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        try:
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(gsa, scope)
            gc = gspread.authorize(credentials)
            return gc
        except Exception as e:
            st.error(f"❌ Lỗi khởi tạo Google Service Account: {e}")
            return None


    def _open_incident_worksheet(gc):
        """Mở worksheet 'Quản lý sự cố' bằng Sheet ID (nếu có) hoặc tên.
        Ưu tiên sử dụng st.secrets['INCIDENT_SHEET_ID'] nếu có.
        """
        if gc is None:
            return None

        sheet_id = None
        try:
            sheet_id = st.secrets.get("INCIDENT_SHEET_ID", None)
        except Exception:
            sheet_id = None

        try:
            if sheet_id:
                sh = gc.open_by_key(sheet_id)
            else:
                # Fallback: mở bằng tên – nếu app đã dùng tên workbook cố định
                # ➜ thay thế 'Dữ liệu sự cố' bằng tên file thực tế nếu cần
                sh = gc.open("Dữ liệu sự cố")
            ws = sh.worksheet("Quản lý sự cố")
            return ws
        except gspread.exceptions.SpreadsheetNotFound:
            st.error("❌ Không tìm thấy Google Sheets với ID hoặc tên đã cung cấp.")
            return None
        except gspread.exceptions.WorksheetNotFound:
            st.error("❌ Không tìm thấy worksheet 'Quản lý sự cố'.")
            return None
        except Exception as e:
            st.error(f"❌ Lỗi khi mở worksheet: {e}")
            return None


    def handle_incident_by_line_year(user_query, gc_client=None):
        """
        Handler cho câu hỏi về sự cố theo đường dây và năm.
        Mục đích: Lấy dữ liệu sự cố từ sheet "Quản lý sự cố", lọc theo năm,
        nhóm theo đường dây và vẽ biểu đồ cột.
        Trả về True nếu xử lý thành công, False nếu không khớp ý định.
        """
        if "sự cố" not in user_query.lower() or "đường dây" not in user_query.lower() or "năm" not in user_query.lower():
            return False

        match = re.search(r'năm\s+(\d{4})', user_query, re.IGNORECASE)
        if not match:
            st.warning("⚠️ Vui lòng cung cấp năm cụ thể (ví dụ: 2024) trong câu hỏi.")
            return True # Đã xử lý, không cần các handler khác

        year = match.group(1)
        st.info(f"Đang tìm kiếm thông tin sự cố theo đường dây trong năm {year}...")

        try:
            # Lấy dữ liệu từ Google Sheets
            # gc_client = _get_gspread_client()
            if gc_client is None:
                gc_client = client # Use the already authorized client from app.py
            
            ws = gc_client.open_by_url(spreadsheet_url).worksheet("Quản lý sự cố")
            records = ws.get_all_records()
            df = pd.DataFrame(records)
        except Exception as e:
            st.error(f"❌ Lỗi khi đọc dữ liệu sự cố từ Google Sheets: {e}")
            return True

        # Tìm tên cột chuẩn
        col_month_year = find_column_name(df, ["Tháng/Năm sự cố"])
        col_line = find_column_name(df, ["Đường dây"])

        if not col_month_year or not col_line:
            st.warning("❗ Không tìm thấy các cột cần thiết ('Tháng/Năm sự cố', 'Đường dây').")
            return True

        # Xử lý dữ liệu
        df[col_month_year] = df[col_month_year].astype(str)
        df['year'] = df[col_month_year].str.extract(r'(\d{4})')
        df_filtered = df[df['year'] == year]

        if df_filtered.empty:
            st.warning(f"⚠️ Không có sự cố nào được ghi nhận trong năm {year}.")
            return True

        grp = df_filtered.groupby(col_line).size().reset_index(name='Số vụ sự cố')
        grp = grp.sort_values(by='Số vụ sự cố', ascending=False)

        st.success(f"✅ Dữ liệu sự cố theo đường dây – Năm {year}")
        
        # Bảng số liệu
        st.dataframe(grp, use_container_width=True)

        # Vẽ biểu đồ cột đứng + hiển thị nhãn
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(grp[col_line], grp["Số vụ sự cố"])  # không đặt màu cụ thể
        ax.set_xlabel("Đường dây")
        ax.set_ylabel("Số vụ sự cố")
        ax.set_title(f"Số vụ sự cố theo đường dây – Năm {year}")
        ax.tick_params(axis='x', rotation=30)

        # Hiển thị nhãn số trên đầu cột
        for i, v in enumerate(grp["Số vụ sự cố"].tolist()):
            ax.text(i, v + max(grp["Số vụ sự cố"]) * 0.01, str(v), ha='center', va='bottom', fontsize=9)

        st.pyplot(fig, clear_figure=True)

        # Gợi ý câu hỏi liên quan
        with st.expander("Gợi ý câu hỏi tiếp theo"):
            st.markdown(
                f"- Lấy thông tin sự cố **tháng 7/{year}**, vẽ biểu đồ theo **loại sự cố**\n"
                f"- So sánh số vụ sự cố **năm {year}** với **{year-1}** theo đường dây\n"
                f"- Lấy danh sách sự cố của **đường dây 471-E6.22** trong năm {year}"
            )

        return True


    # =========================================================================
    # Kết thúc bổ sung handler từ app1.py
    # =========================================================================

    def handle_lanh_dao(question):
        normalized_question = normalize_text(question)
        
        # Check if the question generally asks about "lãnh đạo"
        if "lãnh đạo" in normalized_question:
            try:
                sheet_ld = all_data.get("Danh sách lãnh đạo xã, phường")
                if sheet_ld is None or sheet_ld.empty:
                    st.warning("⚠️ Không tìm thấy sheet 'Danh sách lãnh đạo xã, phường' hoặc sheet rỗng.")
                    return True

                df_ld = sheet_ld # Already a DataFrame from load_all_sheets
                
                # Find the correct column name for commune/ward
                thuoc_xa_phuong_col = find_column_name(df_ld, ['Thuộc xã/phường'])
                if not thuoc_xa_phuong_col:
                    st.warning("❗ Không tìm thấy cột 'Thuộc xã/phường' trong sheet 'Danh sách lãnh đạo xã, phường'.")
                    return True
                
                # Ensure the column is string type for .str.contains
                df_ld[thuoc_xa_phuong_col] = df_ld[thuoc_xa_phuong_col].astype(str)

                ten_xa_phuong_can_tim = None

                # 1. Try to extract commune/ward name directly using regex
                # This regex captures the word(s) immediately following "xã" or "phường"
                match_direct = re.search(r'(?:xã|phường)\s+([\w\s]+)', normalized_question)
                if match_direct:
                    ten_xa_phuong_can_tim = match_direct.group(1).strip()

                # 2. If not found by direct regex, try to match against a predefined list of communes/wards
                # This is a fallback and can also help if the user types just the name without "xã/phường"
                if not ten_xa_phuong_can_tim:
                    predefined_communes = ["định hóa", "kim phượng", "phượng tiến", "trung hội", "bình yên", "phú đình", "bình thành", "lam vỹ", "bình hòa"] # Added "bình hòa" for keyword
                    for keyword in predefined_communes:
                        if keyword in normalized_question:
                            # Try to find the original casing from the unique values in the sheet
                            # This ensures we use the exact name as in the sheet for filtering
                            for sheet_name_original in df_ld[thuoc_xa_phuong_col].unique():
                                if normalize_text(sheet_name_original) == keyword:
                                    ten_xa_phuong_can_tim = sheet_name_original
                                    break
                            if ten_xa_phuong_can_tim:
                                break

                if ten_xa_phuong_can_tim:
                    # Filter DataFrame using the found commune/ward name
                    # Use .str.contains with case=False for case-insensitive matching
                    df_loc = df_ld[df_ld[thuoc_xa_phuong_col].str.contains(ten_xa_phuong_can_tim, case=False, na=False)]
                    if df_loc.empty:
                        st.warning(f"❌ Không tìm thấy dữ liệu lãnh đạo cho xã/phường: {ten_xa_phuong_can_tim}. Vui lòng kiểm tra lại tên xã/phường hoặc dữ liệu trong sheet.")
                    else:
                        st.success(f"📋 Danh sách lãnh đạo xã/phường {ten_xa_phuong_can_tim}")
                        st.dataframe(df_loc.reset_index(drop=True))
                    return True
                else:
                    st.warning("⚠️ Tôi cần biết bạn muốn tìm lãnh đạo của xã/phường nào. Vui lòng cung cấp tên xã/phường (ví dụ: 'định hóa') trong câu hỏi.")
                    return True
            except Exception as e:
                st.error(f"❌ Lỗi trong handler lãnh đạo xã: {e}")
                return True
        return False

    def handle_qa_matching(user_query):
        # Tránh xử lý lại tin nhắn cũ
        if user_query == st.session_state.last_processed_user_msg:
            return

        user_query_normalized = normalize_text(user_query)

        # Lấy cột 'Câu hỏi' và 'Trả lời' từ qa_df
        col_question = find_column_name(qa_df, ['Câu hỏi'])
        col_answer = find_column_name(qa_df, ['Trả lời'])

        if not col_question or not col_answer or qa_df.empty:
            st.warning("⚠️ Không tìm thấy dữ liệu Hỏi-Trả lời.")
            return

        # Tìm kiếm các câu hỏi gần giống
        qa_df['match_score'] = qa_df[col_question].apply(
            lambda x: fuzz.ratio(user_query_normalized, normalize_text(x))
        )
        
        # Chọn các câu hỏi có điểm tương đồng cao
        threshold = 70 # Ngưỡng điểm tương đồng
        matched_qas = qa_df[qa_df['match_score'] >= threshold].sort_values(by='match_score', ascending=False)
        
        # Kiểm tra và xử lý kết quả
        if not matched_qas.empty:
            st.session_state.qa_results = matched_qas.to_dict('records')
            st.session_state.qa_index = 0
            st.session_state.last_processed_user_msg = user_query # Lưu lại tin nhắn đã xử lý
            display_qa_result()
            return True
        else:
            st.session_state.qa_results = []
            st.session_state.qa_index = 0
            st.session_state.last_processed_user_msg = user_query
            return False

    def handle_ai_query(user_query):
        st.info("💡 Không tìm thấy câu trả lời có sẵn, tôi sẽ dùng AI để thử giải đáp. Vui lòng chờ trong giây lát...")
        try:
            response = client_ai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Bạn là trợ lý ảo cho Đội Quản lý đường dây và khu vực Định Hóa. Hãy trả lời các câu hỏi về thông tin công việc, dữ liệu nội bộ một cách ngắn gọn, rõ ràng, tập trung vào các thông tin trong sheet. Nếu không có dữ liệu, hãy nói rõ là 'Không có thông tin này trong dữ liệu của tôi'."},
                    {"role": "user", "content": user_query}
                ]
            )
            ai_response = response.choices[0].message.content
            st.session_state.qa_results = [{'Trả lời': ai_response}]
            st.session_state.qa_index = 0
            display_qa_result()
            return True
        except Exception as e:
            st.error(f"❌ Lỗi khi gọi OpenAI API: {e}")
            return True

    def display_qa_result():
        if st.session_state.qa_results:
            current_qa = st.session_state.qa_results[st.session_state.qa_index]
            st.session_state.current_qa_display = current_qa.get('Trả lời', 'Không có câu trả lời.')
            
            # Hiển thị câu trả lời hiện tại
            st.markdown("### 💬 Trả lời:")
            st.info(st.session_state.current_qa_display)
            
            # Hiển thị nút điều hướng nếu có nhiều hơn 1 kết quả
            if len(st.session_state.qa_results) > 1:
                col1, col2, col3 = st.columns([1, 2, 1])
                with col1:
                    if st.session_state.qa_index > 0:
                        st.button("Câu trả lời trước đó", on_click=lambda: st.session_state.update(qa_index=st.session_state.qa_index-1))
                with col2:
                    st.info(f"Hiển thị câu trả lời {st.session_state.qa_index + 1}/{len(st.session_state.qa_results)}")
                with col3:
                    if st.session_state.qa_index < len(st.session_state.qa_results) - 1:
                        st.button("Câu trả lời tiếp theo", on_click=lambda: st.session_state.update(qa_index=st.session_state.qa_index+1))
            
            # Sau khi hiển thị, không cần gọi lại rerun, chỉ cần cập nhật trạng thái
            st.session_state.last_processed_user_msg = st.session_state.user_input_value
            # st.session_state.user_input_value = "" # Clear input after displaying
        else:
            st.warning("⚠️ Không tìm thấy câu trả lời phù hợp trong dữ liệu.")
            st.session_state.last_processed_user_msg = st.session_state.user_input_value
            st.session_state.user_input_value = ""

    def clear_all_state():
        st.session_state.user_input_value = ""
        st.session_state.last_processed_user_msg = ""
        st.session_state.qa_results = []
        st.session_state.qa_index = 0
        st.session_state.current_qa_display = ""
        st.session_state.audio_processed = False
    
    # Hàm xử lý logic chính của chatbot
    def chatbot_logic(user_query):
        # 1. Kiểm tra và xử lý handler từ app1.py
        handled = handle_incident_by_line_year(user_query, client)
        if handled:
            return

        # 2. Xử lý handler cũ
        handled = handle_lanh_dao(user_query)
        if handled:
            return

        # 3. Xử lý Q&A
        handled = handle_qa_matching(user_query)
        if handled:
            return

        # 4. Sử dụng AI như fallback
        if client_ai:
            handled = handle_ai_query(user_query)
            if handled:
                return

        # 5. Nếu không có gì xử lý được
        st.warning("⚠️ Tôi không thể tìm thấy thông tin phù hợp trong dữ liệu. Vui lòng thử lại với một câu hỏi khác.")

    # Main logic of the app
    if send_button_pressed and st.session_state.user_input_value:
        user_query = st.session_state.user_input_value
        if user_query != st.session_state.last_processed_user_msg:
            # Clear previous results before processing new query
            st.session_state.qa_results = []
            st.session_state.qa_index = 0
            st.session_state.current_qa_display = ""

            with st.spinner("Đang xử lý..."):
                chatbot_logic(user_query)

        st.session_state.user_input_value = "" # Clear input after sending
        # st.rerun() # Không cần rerun ở đây vì các hàm xử lý đã tự động cập nhật UI

    # Nút xóa
    if clear_button_pressed:
        clear_all_state()
        st.success("✅ Đã xóa nội dung chat.")
        st.rerun()

    # --- Phần xử lý OCR ảnh duy nhất ---
    def extract_text_from_image(image_path):
        reader = easyocr.Reader(['vi'])
        result = reader.readtext(image_path, detail=0)
        text = " ".join(result)
        return text

    st.markdown("### 📸 Hoặc tải ảnh chứa câu hỏi (nếu có)")
    uploaded_image = st.file_uploader("Tải ảnh câu hỏi", type=["jpg", "png", "jpeg"])

    if uploaded_image is not None:
        temp_image_path = Path("temp_uploaded_image.jpg")
        try:
            with open(temp_image_path, "wb") as f:
                f.write(uploaded_image.getbuffer())
            
            with st.spinner("⏳ Đang xử lý ảnh và trích xuất văn bản..."):
                extracted_text = extract_text_from_image(str(temp_image_path))
            
            if extracted_text:
                st.info("Văn bản được trích xuất từ ảnh:")
                st.code(extracted_text, language="text")
                st.session_state.user_input_value = extracted_text
                st.success("✅ Đã điền văn bản vào ô nhập liệu. Bạn có thể chỉnh sửa và nhấn 'Gửi'.")
                st.rerun()
            else:
                st.warning("⚠️ Không thể trích xuất văn bản từ ảnh. Vui lòng thử lại với ảnh rõ hơn.")
        except Exception as e:
            st.error(f"❌ Lỗi khi xử lý ảnh: {e}")
        finally:
            if temp_image_path.exists():
                os.remove(temp_image_path)
    # --- Kết thúc phần xử lý OCR ảnh duy nhất ---

    # Hiển thị kết quả QA nếu có
    if st.session_state.qa_results and not st.session_state.current_qa_display:
        display_qa_result()
    elif st.session_state.current_qa_display:
        st.markdown("### 💬 Trả lời:")
        st.info(st.session_state.current_qa_display)
        if len(st.session_state.qa_results) > 1:
            col1, col2, col3 = st.columns([1, 2, 1])
            with col1:
                if st.session_state.qa_index > 0:
                    st.button("Câu trả lời trước đó", on_click=lambda: st.session_state.update(qa_index=st.session_state.qa_index-1))
            with col2:
                st.info(f"Hiển thị câu trả lời {st.session_state.qa_index + 1}/{len(st.session_state.qa_results)}")
            with col3:
                if st.session_state.qa_index < len(st.session_state.qa_results) - 1:
                    st.button("Câu trả lời tiếp theo", on_click=lambda: st.session_state.update(qa_index=st.session_state.qa_index+1))
        
        if len(st.session_state.qa_results) and len(st.session_state.qa_results) > 1:
            st.info("Đã hiển thị tất cả các câu trả lời tương tự.")
