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
    
    # Hàm để xử lý câu hỏi về CBCNV
    def handle_cbcnv(question):
        if "cbcnv" in normalize_text(question) or "cán bộ công nhân viên" in normalize_text(question):
            try:
                sheet_cbcnv = all_data.get("CBCNV")
                if sheet_cbcnv is not None and not sheet_cbcnv.empty:
                    st.subheader("👨‍👩‍👧‍👦 Danh sách Cán bộ Công nhân viên")
                    st.dataframe(sheet_cbcnv.reset_index(drop=True))
                return True
            except Exception as e:
                st.error(f"Lỗi khi xử lý dữ liệu CBCNV: {e}")
                return True
        return False

    # Xử lý khi người dùng nhấn nút "Gửi"
    if send_button_pressed:
        user_msg = st.session_state.user_input_value
        if user_msg and user_msg != st.session_state.last_processed_user_msg:
            st.session_state.last_processed_user_msg = user_msg
            is_handled = False
            normalized_user_msg = normalize_text(user_msg)
            
            # --- ĐOẠN MÃ XỬ LÝ CÂU HỎI TỪ app1.py ---
            # Câu hỏi: Lấy thông tin KPI của các đơn vị tháng 6 năm 2025 và sắp xếp theo thứ tự giảm dần
            if "lấy thông tin kpi của các đơn vị tháng 6 năm 2025 và sắp xếp theo thứ tự giảm dần" in normalized_user_msg:
                sheet_name = "KPI"
                sheet_data = get_sheet_data(sheet_name)
                if sheet_data:
                    df = pd.DataFrame(sheet_data)
                    kpi_col = find_column_name(df, ['Điểm KPI', 'KPI'])
                    nam_col = find_column_name(df, ['Năm'])
                    thang_col = find_column_name(df, ['Tháng'])
                    donvi_col = find_column_name(df, ['Đơn vị'])

                    if kpi_col and nam_col and thang_col and donvi_col:
                        df[kpi_col] = pd.to_numeric(df[kpi_col], errors='coerce')
                        df[nam_col] = pd.to_numeric(df[nam_col], errors='coerce')
                        df[thang_col] = pd.to_numeric(df[thang_col], errors='coerce')

                        # Lọc dữ liệu
                        df_filtered = df[(df[nam_col] == 2025) & (df[thang_col] == 6)]
                        donvi_can_vẽ = ["Định Hóa", "Đồng Hỷ", "Đại Từ", "Phú Bình", "Phú Lương", "Phổ Yên", "Sông Công", "Thái Nguyên", "Võ Nhai"]
                        df_filtered = df_filtered[df_filtered[donvi_col].isin(donvi_can_vẽ)]

                        # Sắp xếp và hiển thị
                        df_sorted = df_filtered.sort_values(by=kpi_col, ascending=False)
                        st.subheader("📊 KPI các đơn vị tháng 6 năm 2025")
                        st.dataframe(df_sorted.reset_index(drop=True))

                        plt.figure(figsize=(10, 6))
                        sns.barplot(data=df_sorted, x=kpi_col, y=donvi_col, palette="crest")
                        plt.title("KPI tháng 6/2025 theo đơn vị")
                        plt.xlabel("Điểm KPI")
                        plt.ylabel("Đơn vị")
                        plt.tight_layout()
                        st.pyplot(plt)
                        plt.close()
                    else:
                        st.warning(f"❗ Không tìm thấy đầy đủ cột (Năm, Tháng, Đơn vị, Điểm KPI) trong sheet {sheet_name}.")
                else:
                    st.warning(f"❗ Sheet '{sheet_name}' không có dữ liệu hoặc không thể đọc được.")
                is_handled = True

            # --- CBCNV: Biểu đồ theo chuyên môn ---
            if "cbcnv" in normalized_user_msg and "trình độ chuyên môn" in normalized_user_msg:
                sheet_name = "CBCNV"
                sheet_data = get_sheet_data(sheet_name)
                if sheet_data:
                    df = pd.DataFrame(sheet_data)
                    chuyen_mon_col = find_column_name(df, ['Trình độ chuyên môn', 'Trình độ', 'Chuyên môn', 'P'])
                    
                    if chuyen_mon_col:
                        df_grouped = df[chuyen_mon_col].value_counts().reset_index()
                        df_grouped.columns = ['Trình độ chuyên môn', 'Số lượng']
                        
                        st.subheader("📊 Phân bố CBCNV theo trình độ chuyên môn")
                        st.dataframe(df_grouped)
                        
                        plt.figure(figsize=(10, 6))
                        sns.barplot(data=df_grouped, x='Số lượng', y='Trình độ chuyên môn', palette='viridis')
                        plt.title("Phân bố CBCNV theo trình độ chuyên môn")
                        plt.xlabel("Số lượng")
                        plt.ylabel("Trình độ chuyên môn")
                        plt.tight_layout()
                        st.pyplot(plt)
                        plt.close()
                    else:
                        st.warning("❗ Không tìm thấy cột 'Trình độ chuyên môn' trong sheet CBCNV")
                else:
                    st.warning("❗ Sheet 'CBCNV' không có dữ liệu hoặc không thể đọc được.")
                is_handled = True

            # --- CBCNV: Biểu đồ theo độ tuổi ---
            if "cbcnv" in normalized_user_msg and "độ tuổi" in normalized_user_msg:
                sheet_name = "CBCNV"
                sheet_data = get_sheet_data(sheet_name)
                if sheet_data:
                    df = pd.DataFrame(sheet_data)
                    tuoi_col = find_column_name(df, ['Độ tuổi', 'Tuổi', 'Q'])

                    if tuoi_col:
                        df[tuoi_col] = pd.to_numeric(df[tuoi_col], errors='coerce')
                        bins = [0, 30, 40, 50, 100]
                        labels = ['<30', '30-39', '40-49', '≥50']
                        df['Nhóm tuổi'] = pd.cut(df[tuoi_col], bins=bins, labels=labels, right=False)
                        df_grouped = df['Nhóm tuổi'].value_counts().sort_index().reset_index()
                        df_grouped.columns = ['Nhóm tuổi', 'Số lượng']

                        st.subheader("📊 Phân bố CBCNV theo độ tuổi")
                        st.dataframe(df_grouped)

                        plt.figure(figsize=(10, 6))
                        sns.barplot(data=df_grouped, x='Nhóm tuổi', y='Số lượng', palette='magma')
                        plt.title("Phân bố CBCNV theo độ tuổi")
                        plt.xlabel("Nhóm tuổi")
                        plt.ylabel("Số lượng")
                        plt.tight_layout()
                        st.pyplot(plt)
                        plt.close()
                    else:
                        st.warning("❗ Không tìm thấy cột 'Độ tuổi' trong sheet CBCNV")
                else:
                    st.warning("❗ Sheet 'CBCNV' không có dữ liệu hoặc không thể đọc được.")
                is_handled = True

            # --- ĐOẠN MÃ XỬ LÝ CÁC CÂU HỎI KHÁC ---
            if not is_handled:
                if handle_lanh_dao(user_msg):
                    is_handled = True
                elif handle_tba(user_msg):
                    is_handled = True
                elif handle_cbcnv(user_msg):
                    is_handled = True
                elif not qa_df.empty:
                    # Kiểm tra và lấy câu trả lời từ Google Sheets
                    qa_df['normalized_question'] = qa_df['Câu hỏi'].apply(normalize_text)
                    qa_df['similarity'] = qa_df['normalized_question'].apply(lambda x: fuzz.ratio(normalized_user_msg, x))
                    
                    matches = qa_df[qa_df['similarity'] > 80].sort_values(by='similarity', ascending=False)

                    if not matches.empty:
                        st.session_state.qa_results = matches.to_dict('records')
                        st.session_state.qa_index = 0
                        
                        # Hiển thị câu trả lời đầu tiên
                        first_match = st.session_state.qa_results[0]
                        st.session_state.current_qa_display = first_match['Câu trả lời']
                        st.success(f"✅ Tìm thấy câu trả lời phù hợp (Độ tương tự: {first_match['similarity']}%):")
                        st.markdown(st.session_state.current_qa_display)
                        
                        is_handled = True
                    else:
                        st.warning("⚠️ Không tìm thấy câu trả lời phù hợp trong cơ sở dữ liệu. Vui lòng nhập lại câu hỏi hoặc thử câu hỏi khác.")
                
            if not is_handled:
                # Xử lý khi không có câu hỏi nào được khớp
                # Kiểm tra xem có OpenAI API key không trước khi gọi API
                if client_ai:
                    with st.spinner("Đang tìm câu trả lời bằng AI..."):
                        try:
                            prompt_text = f"Người dùng hỏi: \"{user_msg}\". Hãy trả lời một cách lịch sự, thân thiện và ngắn gọn rằng bạn chỉ có thể trả lời các câu hỏi liên quan đến dữ liệu đã được cung cấp. Nếu câu hỏi không có trong dữ liệu, hãy đề xuất người dùng nhập lại hoặc sử dụng một câu hỏi mẫu khác."
                            
                            response = client_ai.chat.completions.create(
                                model="gpt-3.5-turbo",
                                messages=[
                                    {"role": "system", "content": "Bạn là một trợ lý ảo của Đội QLĐLKV Định Hóa. Bạn chỉ trả lời các câu hỏi dựa trên các dữ liệu đã được cung cấp. Hãy trả lời một cách chuyên nghiệp, lịch sự, ngắn gọn và hữu ích. Nếu câu hỏi không liên quan đến dữ liệu, hãy từ chối trả lời một cách khéo léo."},
                                    {"role": "user", "content": prompt_text}
                                ],
                                max_tokens=150
                            )
                            st.info("💡 Trả lời từ AI:")
                            st.markdown(response.choices[0].message.content)
                        except Exception as e:
                            st.error(f"❌ Lỗi khi gọi OpenAI API: {e}. Vui lòng kiểm tra lại API key hoặc kết nối mạng.")
                else:
                    st.warning("⚠️ Không tìm thấy câu trả lời phù hợp trong cơ sở dữ liệu và không có OpenAI API key được cấu hình để sử dụng AI. Vui lòng nhập lại câu hỏi hoặc thử câu hỏi khác.")

        elif clear_button_pressed:
            st.session_state.user_input_value = "" # Đặt lại ô nhập liệu
            st.session_state.last_processed_user_msg = ""
            st.session_state.qa_results = []
            st.session_state.qa_index = 0
            st.session_state.current_qa_display = ""
            st.session_state.audio_processed = False
            st.rerun()

    # Điều hướng giữa các câu trả lời
    if st.session_state.qa_results:
        st.markdown("---")
        qa_col1, qa_col2, qa_col3 = st.columns([1, 1, 1])

        with qa_col1:
            if st.button("Câu trả lời trước đó"):
                st.session_state.qa_index = max(0, st.session_state.qa_index - 1)
                st.session_state.current_qa_display = st.session_state.qa_results[st.session_state.qa_index]['Câu trả lời']
                st.rerun()

        with qa_col2:
            st.markdown(f"<p style='text-align: center;'>{st.session_state.qa_index + 1}/{len(st.session_state.qa_results)}</p>", unsafe_allow_html=True)
        
        with qa_col3:
            if st.button("Câu trả lời tiếp theo"):
                st.session_state.qa_index = min(len(st.session_state.qa_results) - 1, st.session_state.qa_index + 1)
                st.session_state.current_qa_display = st.session_state.qa_results[st.session_state.qa_index]['Câu trả lời']
                st.rerun()
        
        # Hiển thị câu trả lời hiện tại sau khi đã điều hướng
        if st.session_state.current_qa_display:
            st.success(f"✅ Câu trả lời (Độ tương tự: {st.session_state.qa_results[st.session_state.qa_index]['similarity']}%):")
            st.markdown(st.session_state.current_qa_display)
        
        if len(st.session_state.qa_results) and len(st.session_state.qa_results) > 1:
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
        finally:
            if temp_image_path.exists():
                os.remove(temp_image_path)
