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
        
        # Sửa đổi logic để xử lý sheet KPI dựa trên cấu trúc mới
        if sheet_name == "KPI":
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

    # Bổ sung form bấm gửi/xóa ở dưới cùng
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

    # Hàm để xử lý câu hỏi lấy thông tin lãnh đạo
    def handle_lanh_dao(question):
        # Kiểm tra nếu câu hỏi có chứa từ khóa "lãnh đạo"
        if "lãnh đạo" in question.lower():
            try:
                st.success("📄 Danh sách lãnh đạo xã, phường")
                df_lanh_dao = pd.DataFrame(get_sheet_data("Danh sách lãnh đạo xã, phường"))
                # Loại bỏ các hàng hoàn toàn trống
                df_lanh_dao = df_lanh_dao.dropna(how='all')
                
                if not df_lanh_dao.empty:
                    st.dataframe(df_lanh_dao)
                else:
                    st.warning("❌ Không tìm thấy dữ liệu lãnh đạo.")
                return True
            except Exception as e:
                st.error(f"Lỗi khi lấy dữ liệu lãnh đạo: {e}")
                return True
        return False

    # Hàm để xử lý câu hỏi về TBA (trạm biến áp)
    def handle_tba(question):
        if "tba" in question.lower():
            try:
                st.info("⏳ Đang tìm kiếm TBA...")
                df_tba = pd.DataFrame(get_sheet_data("Danh sách TBA"))
                # Loại bỏ các hàng hoàn toàn trống
                df_tba = df_tba.dropna(how='all')
                
                if df_tba.empty:
                    st.warning("❌ Không tìm thấy dữ liệu TBA.")
                    return True
                
                # Tìm mã đường dây có dạng 3 chữ số E6.22
                match = re.search(r'(\d{3}E6\.22)', question.upper())
                if match:
                    dd = match.group(1)
                    # Tìm tên cột chứa mã đường dây, sử dụng fuzzy matching
                    dd_col_name = find_column_name(df_tba, ['STT đường dây', 'STT duong day'])
                    
                    if dd_col_name:
                        df_dd = df_tba[df_tba[dd_col_name].astype(str).str.contains(dd)]
                        if not df_dd.empty:
                            st.success(f"📄 Danh sách TBA trên đường dây {dd}")
                            st.dataframe(df_dd.reset_index(drop=True))
                        else:
                            st.warning(f"❌ Không tìm thấy TBA trên đường dây {dd}")
                    else:
                        st.error("❌ Không tìm thấy cột 'STT đường dây' trong sheet 'Danh sách TBA'.")
                    return True
                else:
                    st.info("💡 Để tìm TBA, vui lòng cung cấp mã đường dây có dạng 'xxxE6.22'.")
                return True
            except Exception as e:
                st.error(f"Lỗi khi lấy dữ liệu TBA: {e}")
                return True
        return False
    
    # Hàm mới để xử lý câu hỏi về KPI
    def handle_kpi_query(question):
        if "kpi" in question.lower():
            try:
                st.info("⏳ Đang xử lý câu hỏi về KPI...")
                
                # Lấy dữ liệu KPI
                kpi_data = get_sheet_data("KPI")
                if not kpi_data:
                    st.warning("⚠️ Không có dữ liệu KPI để phân tích.")
                    return True
                
                kpi_df = pd.DataFrame(kpi_data)
                
                # Loại bỏ các hàng hoàn toàn trống
                kpi_df = kpi_df.dropna(how='all')
                
                # Tìm tên các cột cần thiết với fuzzy matching
                unit_col_name = find_column_name(kpi_df, ['Tên đơn vị', 'Ten don vi'])
                kpi_value_col_name = find_column_name(kpi_df, ['Lũy kế', 'Luy ke', 'Thực hiện', 'Thuc hien'])
                date_col_name = find_column_name(kpi_df, ['Tháng/Năm', 'Thang/Nam'])
                
                if not unit_col_name or not kpi_value_col_name or not date_col_name:
                    st.error("❌ Không tìm thấy đủ các cột cần thiết (Tên đơn vị, Lũy kế/Thực hiện, Tháng/Năm) trong sheet 'KPI'.")
                    return True
                
                # Lọc dữ liệu theo tháng/năm hoặc lũy kế
                match_month_year = re.search(r'tháng\s*(\d+)\s*năm\s*(\d{4})', normalize_text(question))
                match_year = re.search(r'năm\s*(\d{4})', normalize_text(question))
                
                filtered_kpi_df = pd.DataFrame()
                
                if match_month_year:
                    month = match_month_year.group(1)
                    year = match_month_year.group(2)
                    target_date = f"{month}/{year}"
                    filtered_kpi_df = kpi_df[kpi_df[date_col_name].astype(str).str.strip() == target_date]
                    if not filtered_kpi_df.empty:
                        st.success(f"📄 Thông tin KPI của các đơn vị tháng {month} năm {year}")
                elif match_year and "lũy kế" in normalize_text(question):
                    year = match_year.group(1)
                    # Giả sử "Lũy kế" sẽ là cột chứa dữ liệu cả năm
                    # Cần tìm dòng có chứa "Lũy kế năm XXXX" hoặc tương tự
                    # Dữ liệu "KPI" của bạn có thể có nhiều dòng "Lũy kế". Tôi sẽ tìm dòng có "Lũy kế" và năm tương ứng
                    
                    # Cần tìm một cột chứa thông tin lũy kế
                    luy_ke_col = find_column_name(kpi_df, ['Lũy kế', 'Luy ke'])
                    if luy_ke_col:
                        # Tìm dòng mà cột đó có giá trị
                        filtered_kpi_df = kpi_df[kpi_df[date_col_name].str.contains(f"Lũy kế {year}", case=False, na=False)]
                        if not filtered_kpi_df.empty:
                            st.success(f"📄 Thông tin KPI lũy kế năm {year}")
                    else:
                        st.warning("⚠️ Không tìm thấy cột 'Lũy kế' để xử lý yêu cầu này.")
                else:
                    st.warning("💡 Vui lòng cung cấp năm hoặc tháng/năm cụ thể trong câu hỏi, ví dụ: 'tháng 6 năm 2025' hoặc 'lũy kế năm 2025'.")
                    return True

                if not filtered_kpi_df.empty:
                    # Chuyển đổi cột KPI sang dạng số
                    try:
                        filtered_kpi_df[kpi_value_col_name] = pd.to_numeric(filtered_kpi_df[kpi_value_col_name], errors='coerce')
                    except Exception as e:
                        st.error(f"❌ Lỗi khi chuyển đổi cột '{kpi_value_col_name}' sang dạng số: {e}. Vui lòng đảm bảo dữ liệu trong cột này là số.")
                        return True

                    # Sắp xếp theo thứ tự giảm dần
                    sorted_kpi_df = filtered_kpi_df.sort_values(by=kpi_value_col_name, ascending=False).reset_index(drop=True)
                    
                    # Hiển thị dataframe
                    st.dataframe(sorted_kpi_df)
                    
                    # Vẽ biểu đồ
                    st.markdown("### 📈 Biểu đồ KPI của các đơn vị")
                    fig, ax = plt.subplots(figsize=(12, 6))
                    sns.barplot(
                        x=sorted_kpi_df[unit_col_name],
                        y=sorted_kpi_df[kpi_value_col_name],
                        ax=ax,
                        palette="coolwarm"
                    )
                    plt.xticks(rotation=45, ha='right')
                    plt.xlabel("Tên đơn vị")
                    plt.ylabel(f"{kpi_value_col_name}")
                    plt.title(f"KPI của các đơn vị ({date_col_name})")
                    plt.tight_layout()
                    st.pyplot(fig)
                    
                else:
                    st.warning("⚠️ Không có dữ liệu nào khớp với yêu cầu của bạn.")
                
                return True
            except Exception as e:
                st.error(f"Lỗi khi xử lý yêu cầu KPI: {e}")
                return True
        return False


    # Logic xử lý chính cho câu hỏi
    if send_button_pressed and st.session_state.user_input_value:
        question = st.session_state.user_input_value
        st.session_state.last_processed_user_msg = question
        st.session_state.audio_processed = False # Reset flag sau khi xử lý câu hỏi
        
        # Xử lý các câu hỏi cụ thể trước
        if handle_lanh_dao(question) or handle_tba(question) or handle_kpi_query(question):
            pass # Đã xử lý, không cần làm gì thêm
        else:
            # Xử lý các câu hỏi chung từ sheet "Hỏi-Trả lời"
            normalized_question = normalize_text(question)
            
            if not qa_df.empty:
                # Tạo một danh sách các câu hỏi đã chuẩn hóa để so sánh
                qa_df['normalized_question'] = qa_df['Câu hỏi'].apply(normalize_text)
                
                # Sử dụng fuzzy matching để tìm câu hỏi gần đúng
                matches = get_close_matches(normalized_question, qa_df['normalized_question'].tolist(), n=3, cutoff=0.6)
                
                if matches:
                    st.session_state.qa_results = []
                    # Lấy các câu trả lời tương ứng với các câu hỏi gần đúng
                    for match in matches:
                        match_row = qa_df[qa_df['normalized_question'] == match].iloc[0]
                        st.session_state.qa_results.append({
                            "question": match_row['Câu hỏi'],
                            "answer": match_row['Câu trả lời']
                        })
                    st.session_state.qa_index = 0
                else:
                    # Nếu không tìm thấy, thử tìm câu hỏi mẫu gần nhất
                    fallback_matches = get_close_matches(question, sample_questions_from_file, n=1, cutoff=0.6)
                    if fallback_matches:
                        st.info(f"❔ Câu hỏi gần giống: '{fallback_matches[0]}'.")
                    else:
                        st.warning("⚠️ Không tìm thấy câu trả lời phù hợp trong dữ liệu.")
                    st.session_state.qa_results = []
                    st.session_state.qa_index = 0
        
        # Rerun để hiển thị kết quả mới
        st.rerun()

    # Hiển thị kết quả từ `st.session_state.qa_results`
    if st.session_state.qa_results:
        qa = st.session_state.qa_results[st.session_state.qa_index]
        st.markdown(f"**Trả lời:** {qa['answer']}")
        if len(st.session_state.qa_results) > 1:
            st.markdown("---")
            nav_cols = st.columns([1, 10, 1])
            with nav_cols[0]:
                if st.button("⬅️ Trước", disabled=(st.session_state.qa_index == 0)):
                    st.session_state.qa_index -= 1
                    st.rerun()
            with nav_cols[1]:
                st.info(f"Hiển thị câu trả lời {st.session_state.qa_index + 1} của {len(st.session_state.qa_results)} câu")
            with nav_cols[2]:
                if st.button("Sau ➡️", disabled=(st.session_state.qa_index == len(st.session_state.qa_results) - 1)):
                    st.session_state.qa_index += 1
                    st.rerun()
    elif send_button_pressed and not st.session_state.qa_results and not st.session_state.current_qa_display:
        pass # Tránh hiển thị thông báo "Không tìm thấy" khi đã có câu trả lời từ handle_lanh_dao hoặc handle_tba


    if clear_button_pressed:
        st.session_state.user_input_value = ""
        st.session_state.qa_results = []
        st.session_state.qa_index = 0
        st.session_state.audio_processed = False
        st.session_state.last_processed_user_msg = ""
        st.rerun()

    # --- Bắt đầu phần mới: Phân tích và biểu đồ ---
    st.markdown("---")
    st.markdown("## 📊 **Phân tích và Biểu đồ Dữ liệu Sự cố**")

    # Hàm để load dữ liệu báo cáo sự cố (tạo một cache riêng)
    @st.cache_data
    def load_incident_data(sheet_name):
        try:
            sheet = client.open_by_url(spreadsheet_url).worksheet(sheet_name)
            df = pd.DataFrame(sheet.get_all_records())
            # Loại bỏ các hàng hoàn toàn trống
            df = df.dropna(how='all')
            return df
        except gspread.exceptions.WorksheetNotFound:
            st.error(f"❌ Không tìm thấy sheet '{sheet_name}'. Vui lòng kiểm tra lại tên sheet.")
            return pd.DataFrame()
        except Exception as e:
            st.error(f"❌ Lỗi khi tải dữ liệu từ sheet '{sheet_name}': {e}")
            return pd.DataFrame()

    # Tạo một selectbox để chọn sheet báo cáo sự cố
    sheet_options = [ws.title for ws in client.open_by_url(spreadsheet_url).worksheets()]
    report_sheet_name = st.selectbox(
        "Chọn sheet chứa dữ liệu báo cáo sự cố:",
        options=sheet_options,
        index=sheet_options.index("Báo cáo sự cố") if "Báo cáo sự cố" in sheet_options else 0
    )

    incident_df = load_incident_data(report_sheet_name)

    if not incident_df.empty:
        # Tìm tên cột dựa trên tên gợi ý của người dùng
        col_map = {
            'Cấp điện áp': find_column_name(incident_df, ['Cấp điện áp', 'Cap dien ap']),
            'Vị trí và thiết bị bị sự cố': find_column_name(incident_df, ['Vị trí và thiết bị bị sự cố', 'Vi tri va thiet bi bi su co']),
            'Tóm tắt nguyên nhân sự cố': find_column_name(incident_df, ['Tóm tắt nguyên nhân sự cố', 'Tom tat nguyen nhan su co']),
            'Loại sự cố': find_column_name(incident_df, ['Loại sự cố', 'Loai su co']),
            'Tính chất': find_column_name(incident_df, ['Tính chất', 'Tinh chat']),
            'Đường dây': find_column_name(incident_df, ['Đường dây', 'Duong day']),
            'Tháng/Năm sự cố': find_column_name(incident_df, ['Tháng/Năm sự cố', 'Thang/Nam su co'])
        }

        # Lọc các cột không tìm thấy
        valid_cols = {key: value for key, value in col_map.items() if value is not None}
        
        # Tạo giao diện lọc
        st.markdown("### ⚙️ Lọc dữ liệu")
        filter_cols = st.columns(3)
        
        with filter_cols[0]:
            if valid_cols.get('Loại sự cố'):
                loai_su_co_options = [''] + list(incident_df[valid_cols['Loại sự cố']].dropna().unique())
                loai_su_co_filter = st.multiselect("Chọn Loại sự cố:", loai_su_co_options)
            else:
                loai_su_co_filter = []
        
        with filter_cols[1]:
            if valid_cols.get('Đường dây'):
                duong_day_options = [''] + list(incident_df[valid_cols['Đường dây']].dropna().unique())
                duong_day_filter = st.multiselect("Chọn Đường dây:", duong_day_options)
            else:
                duong_day_filter = []

        with filter_cols[2]:
            if valid_cols.get('Cấp điện áp'):
                cap_dien_ap_options = [''] + list(incident_df[valid_cols['Cấp điện áp']].dropna().unique())
                cap_dien_ap_filter = st.multiselect("Chọn Cấp điện áp:", cap_dien_ap_options)
            else:
                cap_dien_ap_filter = []
        
        # Nút để bắt đầu xử lý và hiển thị
        if st.button("Tải dữ liệu và Vẽ biểu đồ", type="primary"):
            st.session_state.run_analysis = True
        
        # Logic xử lý và hiển thị
        if st.session_state.get("run_analysis", False):
            with st.spinner("⏳ Đang xử lý dữ liệu..."):
                filtered_df = incident_df.copy()

                # Lọc theo các điều kiện
                if loai_su_co_filter:
                    filtered_df = filtered_df[filtered_df[valid_cols['Loại sự cố']].isin(loai_su_co_filter)]
                if duong_day_filter:
                    filtered_df = filtered_df[filtered_df[valid_cols['Đường dây']].isin(duong_day_filter)]
                if cap_dien_ap_filter:
                    filtered_df = filtered_df[filtered_df[valid_cols['Cấp điện áp']].isin(cap_dien_ap_filter)]

                if filtered_df.empty:
                    st.warning("⚠️ Không có dữ liệu nào khớp với các điều kiện lọc.")
                else:
                    # Chuyển đổi cột Tháng/Năm để vẽ biểu đồ
                    if valid_cols.get('Tháng/Năm sự cố'):
                        try:
                            # Chuyển đổi chuỗi "tháng/năm" sang định dạng datetime
                            filtered_df['Thời gian'] = pd.to_datetime(filtered_df[valid_cols['Tháng/Năm sự cố']], format='%m/%Y')
                            
                            # Nhóm dữ liệu theo Tháng/Năm và đếm số lượng
                            incidents_by_month = filtered_df.groupby('Thời gian').size().reset_index(name='Số lượng sự cố')
                            
                            # Sắp xếp theo thứ tự thời gian
                            incidents_by_month = incidents_by_month.sort_values(by='Thời gian')

                            # Vẽ biểu đồ
                            st.markdown("### 📈 Biểu đồ số lượng sự cố theo tháng/năm")
                            fig, ax = plt.subplots(figsize=(12, 6))
                            sns.barplot(x=incidents_by_month['Thời gian'].dt.strftime('%m/%Y'), y='Số lượng sự cố', data=incidents_by_month, ax=ax, palette="viridis")
                            plt.xticks(rotation=45, ha='right')
                            plt.xlabel("Tháng/Năm")
                            plt.ylabel("Số lượng sự cố")
                            plt.title("Số lượng sự cố theo tháng/năm")
                            plt.tight_layout()
                            st.pyplot(fig)

                        except Exception as e:
                            st.error(f"❌ Lỗi khi xử lý cột 'Tháng/Năm sự cố': {e}. Vui lòng đảm bảo dữ liệu trong cột có định dạng MM/YYYY.")
                    else:
                        st.warning("⚠️ Không tìm thấy cột 'Tháng/Năm sự cố' để vẽ biểu đồ.")

                    # Hiển thị bảng dữ liệu đã lọc
                    st.markdown("### 📄 Bảng dữ liệu đã lọc")
                    st.dataframe(filtered_df.reset_index(drop=True))

            st.session_state.run_analysis = False
    else:
        st.warning("⚠️ Dữ liệu báo cáo không tồn tại hoặc không thể tải.")
    # --- Kết thúc phần mới ---

