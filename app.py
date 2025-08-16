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

# Hàm chuẩn hóa chuỗi để so sánh chính xác hơn (loại bỏ dấu cách thừa, chuyển về chữ thường)
def normalize_text(text):
    if isinstance(text, str):
        # Chuyển về chữ thường, loại bỏ dấu cách thừa ở đầu/cuối và thay thế nhiều dấu cách bằng một dấu cách
        return re.sub(r'\s+', ' ', text).strip().lower()
    return ""

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

# --- Handler tổng quát: KPI các đơn vị tháng mm/năm yyyy (giảm dần) ---
def handle_kpi_monthly(question: str) -> bool:
    # Bắt câu: 'Lấy thông tin KPI của các đơn vị tháng mm năm yyyy và sắp xếp theo thứ tự giảm dần'.
    # Trả về True nếu đã xử lý (kể cả khi không có dữ liệu), False nếu không khớp.
    try:
        normalized = normalize_text(question)
        # Cho phép có/không cụm 'và sắp xếp theo thứ tự giảm dần'
        pattern = r"lấy thông tin kpi của các đơn vị tháng\s*(\d{1,2})\s*năm\s*(\d{4})(?:.*?sắp xếp theo thứ tự giảm dần|.*?)$"
        m = re.search(pattern, normalized)
        if not m:
            return False

        month = int(m.group(1))
        year = int(m.group(2))
        if month < 1 or month > 12:
            st.warning("❗ Tháng không hợp lệ. Vui lòng nhập tháng từ 1–12.")
            return True

        sheet_name = "KPI"
        sheet_data = all_data.get(sheet_name)
        if sheet_data is None or sheet_data.empty:
            st.warning(f"⚠️ Sheet '{sheet_name}' không có dữ liệu hoặc không thể đọc được.")
            return True

        df = sheet_data.copy()

        # Tìm tên cột linh hoạt
        kpi_col   = find_column_name(df, ['Điểm KPI', 'KPI'])
        nam_col   = find_column_name(df, ['Năm'])
        thang_col = find_column_name(df, ['Tháng'])
        donvi_col = find_column_name(df, ['Đơn vị', 'Đơn vị/Địa bàn'])

        if not all([kpi_col, nam_col, thang_col, donvi_col]):
            st.warning(f"❗ Không tìm thấy đầy đủ cột (Năm, Tháng, Đơn vị, Điểm KPI) trong sheet {sheet_name}.")
            return True

        # Chuẩn hóa số
        df[kpi_col]   = df[kpi_col].astype(str).str.replace(',', '.', regex=False)
        df[kpi_col]   = pd.to_numeric(df[kpi_col], errors='coerce')
        df[nam_col]   = pd.to_numeric(df[nam_col], errors='coerce')
        df[thang_col] = pd.to_numeric(df[thang_col], errors='coerce')

        # Lọc dữ liệu tháng/năm
        df_filtered = df[(df[nam_col] == year) & (df[thang_col] == month)].copy()

        if df_filtered.empty:
            st.warning(f"⚠️ Không có dữ liệu KPI cho tháng {month:02d}/{year}.")
            return True

        # Sắp xếp giảm dần theo KPI
        df_sorted = df_filtered.sort_values(by=kpi_col, ascending=False)

        st.subheader(f"📊 KPI các đơn vị tháng {month:02d}/{year} (sắp xếp giảm dần)")
        st.dataframe(df_sorted[[donvi_col, thang_col, nam_col, kpi_col]].reset_index(drop=True))

        # Vẽ biểu đồ theo đúng thứ tự đã sắp
        plt.figure(figsize=(12, 7))
        import seaborn as sns  # đảm bảo có sns trong phạm vi hàm
        ax = sns.barplot(
            data=df_sorted,
            x=donvi_col,
            y=kpi_col,
            order=df_sorted[donvi_col].tolist(),
            palette="tab10"
        )
        plt.title(f"KPI tháng {month:02d}/{year} theo đơn vị (giảm dần)")
        plt.xlabel("Đơn vị")
        plt.ylabel("Điểm KPI")
        plt.xticks(rotation=45, ha='right')

        # Ghi nhãn giá trị trên cột
        for p in ax.patches:
            height = p.get_height()
            ax.annotate(f'{height:.2f}',
                        (p.get_x() + p.get_width()/2., height),
                        ha='center', va='center',
                        xytext=(0, 10), textcoords='offset points',
                        fontsize=10, fontweight='bold')

        plt.tight_layout()
        st.pyplot(plt)
        plt.close()

        return True
    except Exception as e:
        st.error(f"❌ Lỗi khi xử lý KPI tháng mm/năm yyyy: {e}")
        return True




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
    
    # Hàm để xử lý câu hỏi về lãnh đạo xã
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
                #    This is a fallback and can also help if the user types just the name without "xã/phường"
                if not ten_xa_phuong_can_tim:
                    predefined_communes = ["định hóa", "kim phượng", "phượng tiến", "trung hội", "bình yên", "phú đình", "bình thành", "lam vỹ", "bình hòa"] # Added "bình hòa"
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
                    st.warning("❗ Không xác định được tên xã/phường trong câu hỏi. Vui lòng cung cấp tên xã/phường cụ thể (ví dụ: 'lãnh đạo xã Bình Yên').")
                    return True
            except Exception as e:
                st.error(f"Lỗi khi xử lý dữ liệu lãnh đạo xã: {e}")
                return True
        return False
    
    # Hàm để xử lý câu hỏi về TBA theo đường dây
    def handle_tba(question):
        if "tba" in normalize_text(question) and "đường dây" in normalize_text(question):
            try:
                sheet_tba_df = all_data.get("Tên các TBA") # Get the DataFrame directly
                if sheet_tba_df is None or sheet_tba_df.empty:
                    st.warning("⚠️ Không tìm thấy sheet 'Tên các TBA' hoặc sheet rỗng.")
                    return True

                # Tìm cột 'Tên đường dây' để lọc dữ liệu
                ten_duong_day_col = find_column_name(sheet_tba_df, ['Tên đường dây', 'Đường dây', 'C'])
                
                if not ten_duong_day_col:
                    st.warning("❗ Không tìm thấy cột 'Tên đường dây' trong sheet 'Tên các TBA'. Vui lòng kiểm tra lại tên cột.")
                    return True

                match = re.search(r'(\d{3}E6\.22)', question.upper())
                if match:
                    dd = match.group(1)
                    
                    # Lọc dữ liệu dựa trên cột 'Tên đường dây'
                    df_filtered_by_dd = sheet_tba_df[sheet_tba_df[ten_duong_day_col].astype(str).str.strip().str.contains(dd, case=False, na=False)]
                    
                    if not df_filtered_by_dd.empty:
                        st.success(f"📄 Danh sách TBA trên đường dây {dd}")
                        st.dataframe(df_filtered_by_dd.reset_index(drop=True))
                    else:
                        st.warning(f"❌ Không tìm thấy TBA trên đường dây {dd}. Vui lòng kiểm tra lại mã đường dây hoặc dữ liệu trong sheet.")
                    return True
                else:
                    st.warning("❗ Vui lòng cung cấp mã đường dây có định dạng XXXE6.22.")
                    return True
            except Exception as e:
                st.error(f"Lỗi khi lấy dữ liệu TBA: {e}")
                return True
        return False
    
    # Hàm để xử lý câu hỏi về CBCNV
    def handle_cbcnv(question):
        normalized_question = normalize_text(question)
        if "cbcnv" in normalized_question or "cán bộ công nhân viên" in normalized_question:
            try:
                sheet_cbcnv = all_data.get("CBCNV")
                if sheet_cbcnv is None or sheet_cbcnv.empty:
                    st.warning("⚠️ Không tìm thấy sheet 'CBCNV' hoặc sheet rỗng.")
                    return True # Đã xử lý nhưng không có dữ liệu

                df = sheet_cbcnv # Already a DataFrame from load_all_sheets

                # --- CBCNV: Biểu đồ theo bộ phận + nút "Chọn bộ phận" ---
                if ("bieu do" in normalized_question or "biểu đồ" in normalized_question) and ("bo phan" in normalized_question or "bộ phận" in normalized_question):
                    dept_col = find_column_name(df, ['Bộ phận công tác', 'Bộ phận', 'Bộ phận/người phụ trách'])
                    if not dept_col:
                        st.warning("❗ Không tìm thấy cột 'Bộ phận công tác' trong sheet 'CBCNV'.")
                        return True

                    # Làm sạch dữ liệu bộ phận
                    df[dept_col] = df[dept_col].astype(str).str.strip()
                    df_valid = df[df[dept_col].str.len() > 0].copy()

                    # Nút toggle chọn bộ phận
                    state_key = "cbcnv_show_dept_filter"
                    if state_key not in st.session_state:
                        st.session_state[state_key] = False

                    col_btn, col_sp = st.columns([1, 4])
                    with col_btn:
                        if st.button("Chọn bộ phận", key="btn_chon_bo_phan"):
                            st.session_state[state_key] = not st.session_state[state_key]

                    # Danh sách bộ phận
                    dept_options = sorted(df_valid[dept_col].dropna().unique().tolist())
                    selected_depts = dept_options
                    if st.session_state[state_key]:
                        selected_depts = st.multiselect("Chọn bộ phận", dept_options, default=dept_options, key="ms_dept")

                    # Lọc theo lựa chọn
                    df_filtered = df_valid[df_valid[dept_col].isin(selected_depts)].copy()

                    # Hiển thị bảng danh sách
                    st.subheader("📄 Danh sách CBCNV (lọc theo bộ phận)")
                    st.dataframe(df_filtered.reset_index(drop=True))

                    # Nhóm theo bộ phận
                    counts = df_filtered[dept_col].value_counts().sort_values(ascending=False)
                    if counts.empty:
                        st.warning("⚠️ Không có dữ liệu để vẽ biểu đồ.")
                        return True

                    # Biểu đồ cột
                    fig1, ax1 = plt.subplots(figsize=(12, 6))
                    bars = ax1.bar(counts.index.astype(str), counts.values)
                    ax1.set_title("Phân bố CBCNV theo bộ phận (cột)")
                    ax1.set_xlabel("Bộ phận")
                    ax1.set_ylabel("Số lượng")
                    ax1.tick_params(axis='x', rotation=45)

                    # Gắn nhãn số lên cột
                    for bar in bars:
                        height = bar.get_height()
                        ax1.annotate(f"{int(height)}",
                                     (bar.get_x() + bar.get_width() / 2, height),
                                     ha="center", va="bottom", xytext=(0, 3),
                                     textcoords="offset points", fontsize=10, fontweight="bold")

                    st.pyplot(fig1)
                    plt.close(fig1)

                    # Biểu đồ tròn
                    fig2, ax2 = plt.subplots(figsize=(8, 8))
                    def _autopct(pct):
                        total = counts.sum()
                        val = int(round(pct * total / 100.0))
                        return f"{val} ({pct:.1f}%)"
                    ax2.pie(counts.values, labels=counts.index.astype(str), autopct=_autopct, startangle=90, counterclock=False)
                    ax2.set_title("Phân bố CBCNV theo bộ phận (tròn)")
                    ax2.axis('equal')
                    st.pyplot(fig2)
                    plt.close(fig2)

                    return True

                # --- CBCNV: Biểu đồ theo trình độ chuyên môn ---
                if "trình độ chuyên môn" in normalized_question:
                    tdcm_col = find_column_name(df, ['Trình độ chuyên môn', 'Trình độ', 'S'])
                    
                    if tdcm_col:
                        # Nhóm "Kỹ sư" và "Cử nhân" vào một cột; "Thạc sỹ" để riêng
                        df['Nhóm Trình độ'] = df[tdcm_col].astype(str).apply(lambda x: 
                            'Kỹ sư & Cử nhân' if 'kỹ sư' in normalize_text(x) or 'cử nhân' in normalize_text(x) else 
                            'Thạc sỹ' if 'thạc sỹ' in normalize_text(x) else 
                            x # Giữ nguyên các trình độ khác
                        )
                        
                        df_grouped = df['Nhóm Trình độ'].value_counts().reset_index()
                        df_grouped.columns = ['Trình độ chuyên môn', 'Số lượng']

                        st.subheader("📊 Phân bố CBCNV theo trình độ chuyên môn")
                        st.dataframe(df_grouped)

                        plt.figure(figsize=(10, 6))
                        ax = sns.barplot(data=df_grouped, x='Trình độ chuyên môn', y='Số lượng', palette='viridis')

                        plt.title("Phân bố CBCNV theo Trình độ Chuyên môn", fontsize=16)
                        plt.xlabel("Trình độ Chuyên môn", fontsize=14)
                        plt.ylabel("Số lượng", fontsize=14)
                        
                        for p in ax.patches:
                            ax.annotate(f'{int(p.get_height())}', 
                                        (p.get_x() + p.get_width() / 2., p.get_height()), 
                                        ha='center', 
                                        va='center', 
                                        xytext=(0, 10), 
                                        textcoords='offset points',
                                        fontsize=12,
                                        fontweight='bold')

                        st.pyplot(plt)
                        plt.close()
                        return True
                    else:
                        st.warning("❗ Không tìm thấy cột 'Trình độ chuyên môn' trong sheet CBCNV.")
                        return True

                # --- CBCNV: Biểu đồ theo độ tuổi ---
                elif "độ tuổi" in normalized_question:
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
                        ax = sns.barplot(data=df_grouped, x='Nhóm tuổi', y='Số lượng', palette='magma')
                        
                        plt.title("Phân bố CBCNV theo độ tuổi", fontsize=16)
                        plt.xlabel("Nhóm tuổi", fontsize=14)
                        plt.ylabel("Số lượng", fontsize=14)
                        
                        for p in ax.patches:
                            ax.annotate(f'{int(p.get_height())}',
                                        (p.get_x() + p.get_width() / 2., p.get_height()),
                                        ha='center',
                                        va='center',
                                        xytext=(0, 10),
                                        textcoords='offset points',
                                        fontsize=12,
                                        fontweight='bold')

                        plt.tight_layout()
                        st.pyplot(plt)
                        plt.close()
                        return True
                    else:
                        st.warning("❗ Không tìm thấy cột 'Độ tuổi' trong sheet CBCNV")
                        return True
                else: # Nếu chỉ hỏi thông tin chung về CBCNV
                    st.subheader("👨‍👩‍👧‍👦 Danh sách Cán bộ Công nhân viên")
                    st.dataframe(df.reset_index(drop=True))
                    return True
            except Exception as e:
                st.error(f"Lỗi khi xử lý dữ liệu CBCNV: {e}")
                return True
        return False

    # Hàm vẽ biểu đồ sự cố chung, có thể tái sử dụng
    def plot_incident_chart(df, category_col_name, chart_type, year, month=None, is_cumulative=False):
        if not df.empty:
            df_current_year = df[df['thang_nam'].dt.year == year].copy()
            df_previous_year = df[df['thang_nam'].dt.year == year - 1].copy()

            if is_cumulative and month is not None:
                df_current_year = df_current_year[df_current_year['thang_nam'].dt.month <= month]
                df_previous_year = df_previous_year[df_previous_year['thang_nam'].dt.month <= month]
            elif month is not None:
                df_current_year = df_current_year[df_current_year['thang_nam'].dt.month == month]
                df_previous_year = df_previous_year[df_previous_year['thang_nam'].dt.month == month]
            # If month is None and not cumulative, it implies for the whole year

            if not df_current_year.empty or not df_previous_year.empty:
                su_co_current_count = df_current_year[category_col_name].value_counts().reset_index()
                su_co_current_count.columns = [chart_type, 'Số lượng sự cố']
                su_co_current_count['Năm'] = year

                su_co_previous_count = df_previous_year[category_col_name].value_counts().reset_index()
                su_co_previous_count.columns = [chart_type, 'Số lượng sự cố']
                su_co_previous_count['Năm'] = year - 1
                
                combined_df = pd.concat([su_co_current_count, su_co_previous_count])

                title_prefix = "Lũy kế đến " if is_cumulative and month is not None else ""
                month_str = f"tháng {month}/" if month is not None else ""
                chart_title = f"{title_prefix}Số lượng sự cố {month_str}{year} so với cùng kỳ năm {year - 1} theo {chart_type}"
                st.subheader(f"📊 Biểu đồ {chart_title}")
                st.dataframe(combined_df.reset_index(drop=True))

                plt.figure(figsize=(14, 8))
                ax = sns.barplot(data=combined_df, x=chart_type, y='Số lượng sự cố', hue='Năm', palette='viridis')
                
                plt.title(chart_title, fontsize=16)
                plt.xlabel(chart_type, fontsize=14)
                plt.ylabel("Số lượng sự cố", fontsize=14)

                for p in ax.patches:
                    ax.annotate(f'{int(p.get_height())}', 
                                (p.get_x() + p.get_width() / 2., p.get_height()), 
                                ha='center', 
                                va='center', 
                                xytext=(0, 10), 
                                textcoords='offset points',
                                fontsize=10,
                                fontweight='bold')
                
                plt.xticks(rotation=45, ha='right')
                plt.tight_layout()
                st.pyplot(plt)
                plt.close()
            else:
                st.warning(f"❗ Không có dữ liệu sự cố nào trong khoảng thời gian được hỏi.")
        else:
            st.warning(f"❗ Sheet 'Quản lý sự cố' không có dữ liệu hoặc không thể đọc được.")

    # Xử lý khi người dùng nhấn nút "Gửi"
    if send_button_pressed:
        user_msg = st.session_state.user_input_value
        if user_msg and user_msg != st.session_state.last_processed_user_msg:
            st.session_state.last_processed_user_msg = user_msg
            is_handled = False
            normalized_user_msg = normalize_text(user_msg)
            
            # --- ĐOẠN MÃ XỬ LÝ CÁC CÂU HỎI ĐỘNG VỀ SỰ CỐ ---
            # Regex cho câu hỏi có tháng và năm cụ thể
            incident_month_year_match = re.search(r'(?:tháng|lũy kế đến tháng)\s*(\d+)\s*năm\s*(\d{4}).*vẽ biểu đồ theo (đường dây|tính chất|loại sự cố)', normalized_user_msg)
            # Regex cho câu hỏi chỉ có năm
            incident_year_only_match = re.search(r'sự cố năm\s*(\d{4}).*so sánh với cùng kỳ, vẽ biểu đồ theo (đường dây|tính chất|loại sự cố)', normalized_user_msg)

            if incident_month_year_match or incident_year_only_match:
                sheet_name = "Quản lý sự cố"
                sheet_data = all_data.get(sheet_name) # Get DataFrame directly
                
                if sheet_data is not None and not sheet_data.empty:
                    df = sheet_data # Already a DataFrame
                    thang_nam_col = find_column_name(df, ['Tháng/Năm sự cố', 'Tháng/Năm'])
                    
                    if thang_nam_col:
                        try:
                            df['thang_nam'] = pd.to_datetime(df[thang_nam_col], format='%m/%Y', errors='coerce')
                            df = df.dropna(subset=['thang_nam'])
                            
                            if incident_month_year_match:
                                month = int(incident_month_year_match.group(1))
                                year = int(incident_month_year_match.group(2))
                                chart_type = incident_month_year_match.group(3)
                                is_cumulative = "lũy kế đến tháng" in normalized_user_msg
                            elif incident_year_only_match:
                                year = int(incident_year_only_match.group(1))
                                chart_type = incident_year_only_match.group(2)
                                month = datetime.datetime.now().month # Mặc định là tháng hiện tại
                                is_cumulative = True # Mặc định là lũy kế đến tháng hiện tại

                            category_col = None
                            if chart_type == 'đường dây':
                                category_col = find_column_name(df, ['Đường dây', 'Đường dây sự cố', 'J'])
                            elif chart_type == 'tính chất':
                                category_col = find_column_name(df, ['Tính chất', 'I'])
                            elif chart_type == 'loại sự cố':
                                category_col = find_column_name(df, ['Loại sự cố', 'Loại', 'E'])

                            if category_col:
                                plot_incident_chart(df, category_col, chart_type, year, month, is_cumulative)
                                is_handled = True
                            else:
                                st.warning(f"❗ Không tìm thấy cột phân loại '{chart_type}' trong sheet {sheet_name}.")
                                is_handled = True
                        except Exception as e:
                            st.error(f"❌ Lỗi khi xử lý dữ liệu sự cố: {e}")
                            is_handled = True
                    else:
                        st.warning(f"❗ Không tìm thấy cột 'Tháng/Năm sự cố' hoặc 'Tháng/Năm' trong sheet {sheet_name}.")
                        is_handled = True
                else:
                    st.warning(f"❗ Sheet '{sheet_name}' không có dữ liệu hoặc không thể đọc được.")
                is_handled = True
            
            
            # --- KPI tháng mm/năm yyyy (tổng quát, chạy trước block cứng 6/2025) ---
            if not is_handled and handle_kpi_monthly(user_msg):
                is_handled = True

# --- Xử lý câu hỏi KPI tháng cụ thể (ví dụ: tháng 6 năm 2025) ---
            if "lấy thông tin kpi của các đơn vị tháng 6 năm 2025 và sắp xếp theo thứ tự giảm dần" in normalized_user_msg:
                sheet_name = "KPI"
                sheet_data = all_data.get(sheet_name) # Get DataFrame directly
                if sheet_data is not None and not sheet_data.empty:
                    df = sheet_data # Already a DataFrame
                    kpi_col = find_column_name(df, ['Điểm KPI', 'KPI'])
                    nam_col = find_column_name(df, ['Năm'])
                    thang_col = find_column_name(df, ['Tháng'])
                    donvi_col = find_column_name(df, ['Đơn vị'])

                    if kpi_col and nam_col and thang_col and donvi_col:
                        # Chuyển đổi dấu phẩy thành dấu chấm trước khi chuyển sang số
                        df[kpi_col] = df[kpi_col].astype(str).str.replace(',', '.', regex=False)
                        df[kpi_col] = pd.to_numeric(df[kpi_col], errors='coerce')
                        df[nam_col] = pd.to_numeric(df[nam_col], errors='coerce')
                        df[thang_col] = pd.to_numeric(df[thang_col], errors='coerce')

                        # Lọc dữ liệu
                        df_filtered = df[(df[nam_col] == 2025) & (df[thang_col] == 6)]
                        donvi_can_vẽ = ["Định Hóa", "Đồng Hỷ", "Đại Từ", "Phú Bình", "Phú Lương", "Phổ Yên", "Sông Công", "Thái Nguyên", "Võ Nhai"]
                        df_filtered = df_filtered[df_filtered[donvi_col].isin(donvi_can_vẽ)]

                        # Sắp xếp và hiển thị
                        if not df_filtered.empty: # Only proceed if df_filtered is not empty
                            df_sorted = df_filtered.sort_values(by=kpi_col, ascending=False)
                            st.subheader("📊 KPI các đơn vị tháng 6 năm 2025")
                            st.dataframe(df_sorted.reset_index(drop=True))

                            plt.figure(figsize=(10, 6))
                            # Đã thay đổi: x là đơn vị, y là điểm KPI, và palette
                            ax = sns.barplot(data=df_sorted, x=donvi_col, y=kpi_col, palette="tab10") # Thay đổi palette
                            plt.title("KPI tháng 6/2025 theo đơn vị")
                            plt.xlabel("Đơn vị") # Đã thay đổi nhãn trục x
                            plt.ylabel("Điểm KPI") # Đã thay đổi nhãn trục y
                            plt.xticks(rotation=45, ha='right') # Xoay nhãn trục x
                            plt.tight_layout()

                            # Thêm giá trị lên trên cột
                            for p in ax.patches:
                                ax.annotate(f'{p.get_height():.2f}', 
                                            (p.get_x() + p.get_width() / 2., p.get_height()), 
                                            ha='center', 
                                            va='center', 
                                            xytext=(0, 10), 
                                            textcoords='offset points',
                                            fontsize=10,
                                            fontweight='bold')

                            st.pyplot(plt)
                            plt.close()
                        else:
                            st.warning("❗ Không có dữ liệu KPI nào để hiển thị cho tháng 6 năm 2025 và các đơn vị đã chọn.")
                    else:
                        st.warning(f"❗ Không tìm thấy đầy đủ cột (Năm, Tháng, Đơn vị, Điểm KPI) trong sheet {sheet_name}.")
                else:
                    st.warning(f"❗ Sheet '{sheet_name}' không có dữ liệu hoặc không thể đọc được.")
                is_handled = True
            
            # --- Xử lý câu hỏi KPI lũy kế theo năm ---
            kpi_cumulative_match = re.search(r'kpi của các đơn vị lũy kế năm (\d{4}) và sắp xếp theo thứ tự giảm dần', normalized_user_msg)
            if kpi_cumulative_match:
                target_year = int(kpi_cumulative_match.group(1))

                sheet_name = "KPI"
                sheet_data = all_data.get(sheet_name) # Get DataFrame directly
                if sheet_data is not None and not sheet_data.empty:
                    df = sheet_data # Already a DataFrame
                    kpi_col = find_column_name(df, ['Điểm KPI', 'KPI'])
                    nam_col = find_column_name(df, ['Năm'])
                    thang_col = find_column_name(df, ['Tháng'])
                    donvi_col = find_column_name(df, ['Đơn vị'])

                    if kpi_col and nam_col and thang_col and donvi_col:
                        # Chuẩn hóa dữ liệu KPI
                        df[kpi_col] = df[kpi_col].astype(str).str.replace(',', '.', regex=False)
                        df[kpi_col] = pd.to_numeric(df[kpi_col], errors='coerce')
                        df[nam_col] = pd.to_numeric(df[nam_col], errors='coerce')
                        df[thang_col] = pd.to_numeric(df[thang_col], errors='coerce')

                        # Lọc dữ liệu cho năm mục tiêu
                        df_filtered_year = df[(df[nam_col] == target_year)].copy()
                        
                        if not df_filtered_year.empty:
                            # Đã thay đổi: Tính KPI lũy kế (trung bình các tháng) cho mỗi đơn vị trong năm đó
                            df_kpi_cumulative = df_filtered_year.groupby(donvi_col)[kpi_col].mean().reset_index()
                            df_kpi_cumulative.columns = ['Đơn vị', 'Điểm KPI Lũy kế (Trung bình)'] # Cập nhật tên cột
                            df_kpi_cumulative = df_kpi_cumulative.sort_values(by='Điểm KPI Lũy kế (Trung bình)', ascending=False)

                            st.subheader(f"📊 KPI lũy kế (Trung bình) năm {target_year} của các đơn vị")
                            st.dataframe(df_kpi_cumulative.reset_index(drop=True))

                            plt.figure(figsize=(12, 7))
                            # Sử dụng palette để mỗi cột có màu riêng biệt
                            ax = sns.barplot(data=df_kpi_cumulative, x='Đơn vị', y='Điểm KPI Lũy kế (Trung bình)', palette='hls')
                            plt.title(f"KPI lũy kế (Trung bình) năm {target_year} theo đơn vị", fontsize=16)
                            plt.xlabel("Đơn vị", fontsize=14)
                            plt.ylabel("Điểm KPI Lũy kế (Trung bình)", fontsize=14)
                            plt.xticks(rotation=45, ha='right') # Xoay nhãn trục x để dễ đọc
                            plt.grid(axis='y', linestyle='--', alpha=0.7)

                            # Hiển thị giá trị trên đỉnh cột
                            for p in ax.patches:
                                ax.annotate(f'{p.get_height():.2f}', 
                                            (p.get_x() + p.get_width() / 2., p.get_height()), 
                                            ha='center', 
                                            va='center', 
                                            xytext=(0, 10), 
                                            textcoords='offset points',
                                            fontsize=10,
                                            fontweight='bold')

                            plt.tight_layout()
                            st.pyplot(plt)
                            plt.close()
                        else:
                            st.warning(f"❗ Không tìm thấy dữ liệu KPI cho năm {target_year}. Vui lòng kiểm tra lại dữ liệu trong sheet.")
                    else:
                        st.warning(f"❗ Không tìm thấy đầy đủ cột (Năm, Tháng, Đơn vị, Điểm KPI) trong sheet {sheet_name}.")
                else:
                    st.warning(f"❗ Sheet '{sheet_name}' không có dữ liệu hoặc không thể đọc được.")
                is_handled = True
            
            # --- Xử lý câu hỏi so sánh KPI theo năm cho một đơn vị cụ thể ---
            kpi_compare_match = re.search(r'kpi năm (\d{4}) của ([\w\s]+) so sánh với các năm trước', normalized_user_msg)
            if kpi_compare_match:
                target_year = int(kpi_compare_match.group(1))
                target_donvi = kpi_compare_match.group(2).strip()

                sheet_name = "KPI"
                sheet_data = all_data.get(sheet_name) # Get DataFrame directly
                if sheet_data is not None and not sheet_data.empty:
                    df = sheet_data # Already a DataFrame
                    kpi_col = find_column_name(df, ['Điểm KPI', 'KPI'])
                    nam_col = find_column_name(df, ['Năm'])
                    thang_col = find_column_name(df, ['Tháng'])
                    donvi_col = find_column_name(df, ['Đơn vị'])

                    if kpi_col and nam_col and thang_col and donvi_col:
                        # Chuẩn hóa dữ liệu KPI
                        df[kpi_col] = df[kpi_col].astype(str).str.replace(',', '.', regex=False)
                        df[kpi_col] = pd.to_numeric(df[kpi_col], errors='coerce')
                        df[nam_col] = pd.to_numeric(df[nam_col], errors='coerce')
                        df[thang_col] = pd.to_numeric(df[thang_col], errors='coerce')

                        # Lọc dữ liệu cho đơn vị mục tiêu
                        df_filtered_donvi = df[df[donvi_col].str.lower() == target_donvi.lower()].copy()
                        
                        if not df_filtered_donvi.empty:
                            # Lấy các năm có dữ liệu cho đơn vị này, bao gồm năm mục tiêu và các năm trước đó
                            # Lấy tối đa 4 năm gần nhất bao gồm năm mục tiêu
                            years_to_plot = sorted(df_filtered_donvi[nam_col].dropna().unique().tolist(), reverse=True)
                            years_to_plot = [y for y in years_to_plot if y <= target_year][:4] # Giới hạn 4 năm gần nhất
                            years_to_plot.sort() # Sắp xếp lại theo thứ tự tăng dần để vẽ biểu đồ

                            if not years_to_plot:
                                st.warning(f"❗ Không có dữ liệu KPI cho đơn vị '{target_donvi}' trong các năm gần đây.")
                                is_handled = True
                                # continue # This continue is for a loop, but here it's inside an if, so it would break the flow.
                            else:
                                # Create a DataFrame for plotting, including only relevant columns
                                plot_df = df_filtered_donvi[df_filtered_donvi[nam_col].isin(years_to_plot)][[nam_col, thang_col, kpi_col]].copy()
                                plot_df = plot_df.dropna(subset=[kpi_col, thang_col, nam_col])
                                plot_df[thang_col] = plot_df[thang_col].astype(int)
                                plot_df[nam_col] = plot_df[nam_col].astype(int)
                                
                                # Sort by year and month for correct line plotting
                                plot_df = plot_df.sort_values(by=[nam_col, thang_col])

                                st.subheader(f"📊 So sánh KPI của {target_donvi} qua các tháng")
                                st.dataframe(plot_df)

                                plt.figure(figsize=(12, 7))
                                
                                # Plot each year as a separate line
                                for year in years_to_plot:
                                    year_data = plot_df[plot_df[nam_col] == year].copy()
                                    
                                    # For the target year, only plot up to the last available month
                                    if year == target_year:
                                        if not year_data.empty:
                                            max_month_current_year = year_data[thang_col].max()
                                            year_data = year_data[year_data[thang_col] <= max_month_current_year]
                                        else:
                                            st.warning(f"❗ Không có dữ liệu KPI cho năm {target_year} của đơn vị '{target_donvi}'.")
                                            continue # Skip plotting for this year if no data

                                    if not year_data.empty:
                                        sns.lineplot(data=year_data, x=thang_col, y=kpi_col, marker='o', label=str(year))
                                        
                                        # Add annotations for all years plotted
                                        for x_val, y_val in zip(year_data[thang_col], year_data[kpi_col]):
                                            plt.text(x_val, y_val, f'{y_val:.2f}', ha='center', va='bottom', fontsize=9)


                                plt.title(f"So sánh KPI của {target_donvi} qua các tháng theo năm")
                                plt.xlabel("Tháng")
                                plt.ylabel("Điểm KPI")
                                plt.xticks(range(1, 13)) # Ensure x-axis shows months 1-12
                                plt.xlim(0.5, 12.5) # Set x-axis limits to clearly show months 1-12
                                plt.grid(True, linestyle='--', alpha=0.7)
                                plt.legend(title="Năm")
                                plt.tight_layout()
                                st.pyplot(plt)
                                plt.close()
                        else:
                            st.warning(f"❗ Không tìm thấy dữ liệu KPI cho đơn vị '{target_donvi}'. Vui lòng kiểm tra lại tên đơn vị.")
                    else:
                        st.warning(f"❗ Không tìm thấy đầy đủ cột (Năm, Tháng, Đơn vị, Điểm KPI) trong sheet {sheet_name}.")
                else:
                    st.warning(f"❗ Sheet '{sheet_name}' không có dữ liệu hoặc không thể đọc được.")
                is_handled = True
            
            # --- Xử lý câu hỏi về TBA theo công suất ---
            tba_capacity_match = re.search(r'công suất\s*(\d+)\s*kva', normalized_user_msg)
            if tba_capacity_match:
                target_capacity_num = tba_capacity_match.group(1)
                target_capacity = f"{target_capacity_num}KVA" # Reconstruct to match data format in sheet

                sheet_name = "Tên các TBA"
                sheet_data = all_data.get(sheet_name)
                if sheet_data is not None and not sheet_data.empty:
                    df = sheet_data

                    cong_suat_col = find_column_name(df, ['Công suất', 'Công suất ']) # Include both with and without space
                    if cong_suat_col:
                        # Normalize the column data for robust comparison (remove spaces, convert to upper)
                        df_filtered_by_capacity = df[
                            df[cong_suat_col].astype(str).str.replace(' ', '').str.upper() == target_capacity.upper()
                        ]

                        if not df_filtered_by_capacity.empty:
                            st.success(f"📄 Danh sách TBA có công suất {target_capacity}")
                            st.dataframe(df_filtered_by_capacity.reset_index(drop=True))
                        else:
                            st.warning(f"❌ Không tìm thấy TBA có công suất {target_capacity}. Vui lòng kiểm tra lại công suất hoặc dữ liệu trong sheet.")
                        is_handled = True
                    else:
                        st.warning(f"❗ Không tìm thấy cột 'Công suất' trong sheet {sheet_name}.")
                        is_handled = True
                else:
                    st.warning(f"❗ Sheet '{sheet_name}' không có dữ liệu hoặc không thể đọc được.")
                is_handled = True

            # --- ĐOẠN MÃ XỬ LÝ CÁC CÂU HỎI KHÁC ---
            if not is_handled:
                if handle_lanh_dao(user_msg): # Gọi hàm handle_lanh_dao ở đây
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
