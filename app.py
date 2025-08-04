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
import numpy as np # Thêm import numpy
from cryptography.fernet import Fernet
from audio_recorder_streamlit import audio_recorder
from difflib import get_close_matches
# Thêm import mới cho biểu đồ
import seaborn as sns
from oauth2client.service_account import ServiceAccountCredentials


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
        st.success("✅ Đã kết nối Google Sheets thành công!")

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

# Hàm để tìm tên cột chính xác, không phân biệt hoa thường và dấu cách
def find_column_name(df, possible_names):
    """
    Tìm tên cột chính xác trong DataFrame từ một danh sách các tên có thể.
    """
    df_cols = [c.strip().lower() for c in df.columns]
    for name in possible_names:
        if name.strip().lower() in df_cols:
            # Trả về tên cột gốc từ DataFrame
            return df.columns[df_cols.index(name.strip().lower())]
    return None

# Hàm để lấy dữ liệu từ một sheet cụ thể
def get_sheet_data(sheet_name):
    try:
        sheet = client.open_by_url(spreadsheet_url).worksheet(sheet_name)
        
        if sheet_name == "KPI":
            all_values = sheet.get_all_values()
            if all_values:
                # Đảm bảo tiêu đề là duy nhất trước khi tạo DataFrame
                headers = all_values[0]
                # Tạo danh sách tiêu đề duy nhất bằng cách thêm số nếu có trùng lặp
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
                return df_temp.to_dict('records') # Return as list of dictionaries
            else:
                return [] # Return empty list if no values
        else:
            return sheet.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Không tìm thấy sheet '{sheet_name}'. Vui lòng kiểm tra tên sheet.")
        return None
    except Exception as e:
        st.error(f"❌ Lỗi khi mở Google Sheet '{sheet_name}': {e}. Vui lòng kiểm tra định dạng tiêu đề của sheet. Nếu có tiêu đề trùng lặp, hãy đảm bảo chúng là duy nhất.")
        return None

# Hàm chuẩn hóa chuỗi để so sánh chính xác hơn (loại bỏ dấu cách thừa, chuyển về chữ thường)
def normalize_text(text):
    if isinstance(text, str):
        # Chuyển về chữ thường, loại bỏ dấu cách thừa ở đầu/cuối và thay thế nhiều dấu cách bằng một dấu cách
        return re.sub(r'\s+', ' ', text).strip().lower()
    return ""

# Tải dữ liệu từ sheet "Hỏi-Trả lời" một lần khi ứng dụng khởi động
qa_data = get_sheet_data("Hỏi-Trả lời")
qa_df = pd.DataFrame(qa_data) if qa_data else pd.DataFrame()

# Hàm lấy dữ liệu từ tất cả sheet trong file
@st.cache_data
def load_all_sheets():
    spreadsheet = client.open_by_url(spreadsheet_url)
    sheet_names = [ws.title for ws in spreadsheet.worksheets()]
    data = {}
    for name in sheet_names:
        try:
            records = spreadsheet.worksheet(name).get_all_records()
            data[name] = pd.DataFrame(records)
        except:
            data[name] = pd.DataFrame()
    return data

all_data = load_all_sheets()

# Hàm để đọc câu hỏi từ file JSON
def load_sample_questions(file_path="sample_questions.json"):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            questions_data = json.load(f)
        # Nếu định dạng là list of strings
        if isinstance(questions_data, list) and all(isinstance(q, str) for q in questions_data):
            return questions_data
        # Nếu định dạng là list of dictionaries (nếu sau này bạn muốn thêm id hoặc mô tả)
        elif isinstance(questions_data, list) and all(isinstance(q, dict) and "text" in q for q in questions_data):
            return [q["text"] for q in questions_data]
        else:
            st.error("Định dạng file sample_questions.json không hợp lệ. Vui lòng đảm bảo nó là một danh sách các chuỗi hoặc đối tượng có khóa 'text'.")
            return []
    except FileNotFoundError:
        st.warning(f"⚠️ Không tìm thấy file: {file_path}. Vui lòng tạo file chứa các câu hỏi mẫu để sử dụng chức năng này.")
        return []
    except json.JSONDecodeError:
        st.error(f"❌ Lỗi đọc file JSON: {file_path}. Vui lòng kiểm tra cú pháp JSON của file.")
        return []

# Tải các câu hỏi mẫu khi ứng dụng khởi động (giữ lại hàm, nhưng sẽ dùng options cứng cho selectbox)
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

    # Đọc câu hỏi mẫu từ file sample_questions
    try:
        with open("sample_questions.json", "r", encoding="utf-8") as f:
            sample_questions = json.load(f)
    except Exception as e:
        st.warning(f"Không thể đọc file câu hỏi mẫu: {e}")
        sample_questions = []

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

    # Hàm để xử lý câu hỏi về lãnh đạo xã
    def handle_lanh_dao(question):
        if "lãnh đạo" in normalize_text(question) and any(xa in normalize_text(question) for xa in ["định hóa", "kim phượng", "phượng tiến", "trung hội", "bình yên", "phú đình", "bình thành", "lam vỹ"]):
            try:
                sheet_ld = all_data.get("Danh sách lãnh đạo xã, phường")
                if sheet_ld is not None and not sheet_ld.empty:
                    xa_match = re.search(r'xã|phường ([\w\s]+)', normalize_text(question))
                    if xa_match:
                        ten_xa = xa_match.group(1).strip().upper()
                    else:
                        ten_xa = None
                        for row in sheet_ld['Thuộc xã/phường'].unique():
                            if normalize_text(row) in normalize_text(question):
                                ten_xa = row.upper()
                                break
                    
                    if ten_xa:
                        df_loc = sheet_ld[sheet_ld['Thuộc xã/phường'].str.upper().str.contains(ten_xa, na=False)]
                        if df_loc.empty:
                            st.warning(f"❌ Không tìm thấy dữ liệu lãnh đạo cho xã/phường: {ten_xa}")
                        else:
                            st.success(f"📋 Danh sách lãnh đạo xã/phường {ten_xa}")
                            st.dataframe(df_loc.reset_index(drop=True))
                        return True
                    else:
                        st.warning("❗ Không xác định được tên xã/phường trong câu hỏi.")
                        return True
                else:
                    st.warning("⚠️ Không tìm thấy sheet 'Danh sách lãnh đạo xã, phường' hoặc sheet rỗng.")
                    return True
            except Exception as e:
                st.error(f"Lỗi khi xử lý dữ liệu lãnh đạo xã: {e}")
                return True
        return False

    # Hàm để xử lý câu hỏi về TBA theo đường dây
    def handle_tba(question):
        if "tba" in normalize_text(question) and "đường dây" in normalize_text(question):
            try:
                sheet_tba = all_data.get("Tên các TBA")
                if sheet_tba is not None and not sheet_tba.empty:
                    match = re.search(r'(\d{3}E6\.22)', question.upper())
                    if match:
                        dd = match.group(1)
                        df_dd = sheet_tba[sheet_tba['STT đường dây'].astype(str).str.contains(dd)]
                        if not df_dd.empty:
                            st.success(f"📄 Danh sách TBA trên đường dây {dd}")
                            st.dataframe(df_dd.reset_index(drop=True))
                        else:
                            st.warning(f"❌ Không tìm thấy TBA trên đường dây {dd}")
                        return True
                    else:
                        st.warning("❗ Vui lòng cung cấp mã đường dây có định dạng XXXE6.22.")
                        return True
                else:
                    st.warning("⚠️ Không tìm thấy sheet 'Tên các TBA' hoặc sheet rỗng.")
                    return True
            except Exception as e:
                st.error(f"Lỗi khi lấy dữ liệu TBA: {e}")
                return True
        return False
    
    # Xử lý khi người dùng nhấn nút "Gửi"
    if send_button_pressed:
        user_msg = st.session_state.user_input_value
        if user_msg and user_msg != st.session_state.last_processed_user_msg:
            st.session_state.last_processed_user_msg = user_msg # Cập nhật tin nhắn đã xử lý cuối cùng
            
            is_handled = False
            normalized_user_msg = normalize_text(user_msg)

            # --- Bắt đầu phần mã đã được sửa lỗi ---
            if "lấy thông tin kpi của các đơn vị lũy kế năm 2025 và sắp xếp theo thứ tự giảm dần" in normalized_user_msg:
                sheet = client.open_by_url(spreadsheet_url).worksheet("KPI")
                all_values = sheet.get_all_values()
                if all_values:
                    headers = [h.strip() for h in all_values[0]]
                    df = pd.DataFrame(all_values[1:], columns=headers)

                    kpi_col = find_column_name(df, ['kpi', 'chỉ tiêu'])
                    nam_col = find_column_name(df, ['năm', 'nam'])
                    donvi_col = find_column_name(df, ['đơn vị', 'don vi'])
                    loai_col = find_column_name(df, ['loại', 'loai'])

                    if kpi_col and nam_col and donvi_col and loai_col:
                        df[kpi_col] = pd.to_numeric(df[kpi_col], errors='coerce')
                        df[nam_col] = pd.to_numeric(df[nam_col], errors='coerce')
                        df_filtered = df[(df[loai_col] == 'Lũy kế') & (df[nam_col] == 2025)]

                        df_sorted = df_filtered.sort_values(by=kpi_col, ascending=False)
                        st.subheader("📊 Bảng KPI lũy kế năm 2025")
                        st.dataframe(df_sorted)

                        plt.figure(figsize=(10, 6))
                        sns.barplot(data=df_sorted, x=kpi_col, y=donvi_col, palette="viridis")
                        plt.title("Biểu đồ KPI lũy kế năm 2025")
                        plt.xlabel(kpi_col)
                        plt.ylabel(donvi_col)
                        st.pyplot(plt)
                    else:
                        st.warning("Không tìm thấy các cột cần thiết (KPI, Năm, Đơn vị, Loại) trong dữ liệu. Vui lòng kiểm tra tên cột trong Google Sheet.")
                else:
                    st.warning("Dữ liệu KPI rỗng.")
                is_handled = True

            elif "lấy thông tin kpi năm 2025 của định hóa so sánh với các năm trước" in normalized_user_msg:
                sheet = client.open_by_url(spreadsheet_url).worksheet("KPI")
                all_values = sheet.get_all_values()
                if all_values:
                    headers = [h.strip() for h in all_values[0]]
                    df = pd.DataFrame(all_values[1:], columns=headers)

                    kpi_col = find_column_name(df, ['kpi', 'chỉ tiêu'])
                    nam_col = find_column_name(df, ['năm', 'nam'])
                    donvi_col = find_column_name(df, ['đơn vị', 'don vi'])

                    if kpi_col and nam_col and donvi_col:
                        df[kpi_col] = pd.to_numeric(df[kpi_col], errors='coerce')
                        df[nam_col] = pd.to_numeric(df[nam_col], errors='coerce')
                        df_filtered = df[df[donvi_col].astype(str).str.lower().str.strip() == 'định hóa']

                        df_grouped = df_filtered.groupby(nam_col)[kpi_col].mean().reset_index()

                        st.subheader("📊 KPI của Định Hóa theo năm")
                        st.dataframe(df_grouped)

                        plt.figure(figsize=(8, 5))
                        sns.lineplot(data=df_grouped, x=nam_col, y=kpi_col, marker='o')
                        plt.title("KPI Định Hóa các năm")
                        plt.xlabel(nam_col)
                        plt.ylabel(kpi_col)
                        st.pyplot(plt)
                    else:
                        st.warning("Không tìm thấy các cột cần thiết (KPI, Năm, Đơn vị) trong dữ liệu. Vui lòng kiểm tra tên cột trong Google Sheet.")
                else:
                    st.warning("Dữ liệu KPI rỗng.")
                is_handled = True

            elif "lấy thông tin sự cố tháng 7 năm 2025 so sánh với cùng kỳ, vẽ biểu đồ theo loại sự cố" in normalized_user_msg:
                sheet = client.open_by_url(spreadsheet_url).worksheet("Sự cố")
                df = pd.DataFrame(sheet.get_all_records())
                
                thang_col = find_column_name(df, ['tháng', 'thang'])
                nam_col = find_column_name(df, ['năm', 'nam'])
                loai_suco_col = find_column_name(df, ['loại sự cố', 'loai su co'])
                
                if thang_col and nam_col and loai_suco_col:
                    df[thang_col] = pd.to_numeric(df[thang_col], errors='coerce')
                    df[nam_col] = pd.to_numeric(df[nam_col], errors='coerce')
                    df_filtered = df[df[thang_col] == 7]
                    
                    df_grouped = df_filtered.groupby([nam_col, loai_suco_col]).size().reset_index(name='Số sự cố')

                    st.subheader("📊 Biểu đồ loại sự cố trong tháng 7 các năm")
                    st.dataframe(df_grouped)

                    plt.figure(figsize=(10, 6))
                    sns.barplot(data=df_grouped, x=loai_suco_col, y='Số sự cố', hue=nam_col)
                    plt.title("So sánh loại sự cố tháng 7 theo năm")
                    plt.xlabel(loai_suco_col)
                    plt.ylabel("Số sự cố")
                    st.pyplot(plt)
                else:
                    st.warning("Không tìm thấy các cột cần thiết ('Tháng', 'Năm', 'Loại sự cố') trong dữ liệu. Vui lòng kiểm tra tên cột trong Google Sheet.")
                is_handled = True
            
            elif "lấy thông tin lãnh đạo xã định hóa" in normalized_user_msg:
                try:
                    sheet = client.open_by_url(spreadsheet_url).worksheet("Lãnh đạo xã")
                    df = pd.DataFrame(sheet.get_all_records())
                    
                    xa_col = find_column_name(df, ['xã', 'xa'])
                    if xa_col:
                        df_filtered = df[df[xa_col].fillna('').str.strip().str.lower() == 'định hóa']
                        st.subheader("👨‍💼 Thông tin lãnh đạo xã Định Hóa")
                        st.dataframe(df_filtered)
                    else:
                        st.warning("Không tìm thấy cột 'Xã' trong dữ liệu. Vui lòng kiểm tra tên cột trong Google Sheet.")
                except Exception as e:
                    st.error(f"Lỗi khi xử lý dữ liệu lãnh đạo xã: {e}")
                is_handled = True

            # --- Kết thúc phần mã đã được sửa lỗi ---


            # --- Xử lý các câu hỏi chung về Sự cố, KPI ---
            if not is_handled:
                if "sự cố" in normalized_user_msg:
                    with st.spinner("⏳ Đang tạo biểu đồ sự cố..."):
                        suco_data = get_sheet_data("Sự cố")
                        if suco_data:
                            df = pd.DataFrame(suco_data)
                            st.subheader("📊 Biểu đồ Sự cố")
                            
                            ngay_col = find_column_name(df, ['ngày', 'ngay'])
                            loai_suco_col = find_column_name(df, ['loại sự cố', 'loai su co'])
                            
                            if ngay_col and loai_suco_col:
                                df[ngay_col] = pd.to_datetime(df[ngay_col], format='%d/%m/%Y', errors='coerce')
                                df = df.sort_values(by=ngay_col)
                                
                                # Tạo biểu đồ tổng hợp
                                fig, ax = plt.subplots(figsize=(10, 6))
                                sns.countplot(data=df, x=loai_suco_col, ax=ax)
                                ax.set_title("Số lượng sự cố theo loại")
                                ax.set_xlabel("Loại sự cố")
                                ax.set_ylabel("Số lượng")
                                st.pyplot(fig)
                            else:
                                st.warning("⚠️ Dữ liệu Sự cố thiếu một trong các cột cần thiết: 'Ngày', 'Loại sự cố'.")
                        else:
                            st.info("⚠️ Không có dữ liệu sự cố để tạo biểu đồ.")
                    is_handled = True

                elif "kpi" in normalized_user_msg:
                    with st.spinner("⏳ Đang tạo biểu đồ KPI..."):
                        kpi_data = get_sheet_data("KPI")
                        if kpi_data:
                            df = pd.DataFrame(kpi_data)
                            st.subheader("📈 Biểu đồ KPI")
                            
                            ngay_col = find_column_name(df, ['ngày', 'ngay'])
                            sovu_col = find_column_name(df, ['số vụ', 'so vu'])
                            sotien_col = find_column_name(df, ['số tiền', 'so tien'])
                            
                            if ngay_col and sovu_col and sotien_col:
                                df[ngay_col] = pd.to_datetime(df[ngay_col], format='%d/%m/%Y', errors='coerce')
                                df = df.sort_values(by=ngay_col)
                                
                                for col in [sovu_col, sotien_col]:
                                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce')
                                
                                chart_col1, chart_col2 = st.columns(2)
                                
                                with chart_col1:
                                    fig_vu, ax_vu = plt.subplots(figsize=(10, 6))
                                    ax_vu.bar(df[ngay_col], df[sovu_col], color='skyblue')
                                    ax_vu.set_title(f"{sovu_col} theo ngày")
                                    ax_vu.set_xlabel("Ngày")
                                    ax_vu.set_ylabel(sovu_col)
                                    ax_vu.tick_params(axis='x', rotation=45)
                                    ax_vu.grid(axis='y', linestyle='--', alpha=0.7)
                                    st.pyplot(fig_vu)
                                
                                with chart_col2:
                                    fig_tien, ax_tien = plt.subplots(figsize=(10, 6))
                                    colors = cm.viridis(np.linspace(0, 1, len(df[sotien_col])))
                                    ax_tien.bar(df[ngay_col], df[sotien_col], color=colors)
                                    ax_tien.set_title(f"Tổng {sotien_col} theo ngày")
                                    ax_tien.set_xlabel("Ngày")
                                    ax_tien.set_ylabel(f"{sotien_col} (triệu đồng)")
                                    ax_tien.tick_params(axis='x', rotation=45)
                                    ax_tien.grid(axis='y', linestyle='--', alpha=0.7)
                                    ax_tien.get_yaxis().set_major_formatter(
                                        plt.FuncFormatter(lambda x, p: format(int(x), ','))
                                    )
                                    st.pyplot(fig_tien)
                            else:
                                st.warning("⚠️ Dữ liệu KPI thiếu một trong các cột cần thiết: 'Ngày', 'Số vụ', 'Số tiền'.")
                        else:
                            st.info("⚠️ Không có dữ liệu KPI để tạo biểu đồ.")
                    is_handled = True

                elif "lãnh đạo" in normalized_user_msg:
                    is_handled = handle_lanh_dao(user_msg)
                elif "tba" in normalized_user_msg:
                    is_handled = handle_tba(user_msg)
                
                # --- Nếu vẫn chưa được xử lý, dùng fuzzy search hoặc gọi AI ---
                if not is_handled:
                    with st.spinner('⏳ Đang tìm kiếm câu trả lời...'):
                        best_match = None
                        highest_score = 0
                        
                        for index, row in qa_df.iterrows():
                            question_in_sheet = normalize_text(str(row.get('Câu hỏi', '')))
                            score = fuzz.ratio(normalized_user_msg, question_in_sheet)
                            
                            if score > highest_score:
                                highest_score = score
                                best_match = row

                        if highest_score >= 80:
                            st.session_state.qa_results = []
                            
                            for index, row in qa_df.iterrows():
                                question_in_sheet = normalize_text(str(row.get('Câu hỏi', '')))
                                score = fuzz.ratio(normalized_user_msg, question_in_sheet)
                                
                                if score == highest_score:
                                    st.session_state.qa_results.append(row['Câu trả lời'])
                            
                            st.session_state.qa_index = 0
                            st.session_state.current_qa_display = st.session_state.qa_results[st.session_state.qa_index]
                            st.session_state.qa_index += 1
                        
                            st.rerun()
                        else:
                            if client_ai:
                                with st.spinner("⏳ Không tìm thấy câu trả lời trong Sổ tay, đang hỏi AI..."):
                                    try:
                                        prompt = f"Dựa trên câu hỏi sau, hãy trả lời một cách ngắn gọn, súc tích và chỉ tập trung vào thông tin cần thiết: '{user_msg}'"
                                        response = client_ai.chat.completions.create(
                                            model="gpt-3.5-turbo",
                                            messages=[{"role": "user", "content": prompt}]
                                        )
                                        if response.choices and len(response.choices) > 0:
                                            ai_answer = response.choices[0].message.content
                                            st.info("Câu trả lời từ AI:")
                                            st.write(ai_answer)
                                        else:
                                            st.warning("⚠️ AI không đưa ra được câu trả lời.")
                                    except Exception as ai_e:
                                        st.error(f"❌ Lỗi khi kết nối đến OpenAI: {ai_e}. Vui lòng kiểm tra lại API key hoặc kết nối internet.")
                            else:
                                st.warning("⚠️ Không tìm thấy câu trả lời tương tự và OpenAI API key chưa được cấu hình. Vui lòng thêm API key để sử dụng tính năng AI.")


    if clear_button_pressed:
        st.session_state.user_input_value = ""
        st.session_state.qa_results = []
        st.session_state.qa_index = 0
        st.session_state.current_qa_display = ""
        st.session_state.audio_processed = False
        st.rerun()

    if st.session_state.current_qa_display:
        st.info("Câu trả lời:")
        st.write(st.session_state.current_qa_display)

    if st.session_state.qa_results and st.session_state.qa_index < len(st.session_state.qa_results):
        if st.button("Tìm tiếp"):
            st.session_state.current_qa_display = st.session_state.qa_results[st.session_state.qa_index]
            st.session_state.qa_index += 1
            st.rerun()
    elif st.session_state.qa_results and st.session_state.qa_index >= len(st.session_state.qa_results) and len(st.session_state.qa_results) > 1:
        st.info("Đã hiển thị tất cả các câu trả lời tương tự.")


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
                st.warning("⚠️ Không thể trích xuất văn bản từ ảnh. Vui lòng thử lại với ảnh khác rõ hơn.")
        except Exception as e:
            st.error(f"❌ Lỗi khi xử lý ảnh: {e}")
        finally:
            if temp_image_path.exists():
                os.remove(temp_image_path)
