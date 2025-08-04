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
# Thư viện này cần được cài đặt: pip install cryptography
from cryptography.fernet import Fernet
from audio_recorder_streamlit import audio_recorder  # ✅ Thay thế thư viện mic_recorder bằng thư viện ổn định hơn

# Cấu hình Streamlit page để sử dụng layout rộng
st.set_page_config(layout="wide")

# Cấu hình Matplotlib để hiển thị tiếng Việt
plt.rcParams['font.family'] = 'DejaVu Sans' # Hoặc 'Arial', 'Times New Roman' nếu có
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
        # Lấy key mã hóa từ secrets.toml
        encryption_key_for_decryption = st.secrets["gdrive_service_account"]["encryption_key_for_decryption"]
        
        # Lấy private key đã mã hóa
        encrypted_private_key = st.secrets["gdrive_service_account"]["encrypted_private_key"]
        
        # Giải mã private key
        f = Fernet(encryption_key_for_decryption.encode())
        decrypted_private_key = f.decrypt(encrypted_private_key.encode()).decode()

        # Tạo một dictionary tương tự như secrets cũ, nhưng dùng key đã giải mã
        info = {
            "type": st.secrets["gdrive_service_account"]["type"],
            "project_id": st.secrets["gdrive_service_account"]["project_id"],
            "private_key_id": st.secrets["gdrive_service_account"]["private_key_id"],
            "private_key": decrypted_private_key, # Sử dụng key đã được giải mã
            "client_email": st.secrets["gdrive_service_account"]["client_email"],
            "client_id": st.secrets["gdrive_service_account"]["client_id"],
            "auth_uri": st.secrets["gdrive_service_account"]["auth_uri"],
            "token_uri": st.secrets["gdrive_service_account"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["gdrive_service_account"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["gdrive_service_account"]["client_x509_cert_url"],
            "universe_domain": st.secrets["gdrive_service_account"]["universe_domain"],
        }
        
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        client = gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Lỗi khi giải mã hoặc kết nối Google Sheets: {e}. Vui lòng kiểm tra lại cấu hình secrets.toml.")
        st.stop() # Dừng ứng dụng nếu có lỗi kết nối
else:
    st.error("❌ Không tìm thấy gdrive_service_account trong secrets. Vui lòng cấu hình.")
    st.stop() # Dừng ứng dụng nếu không có secrets

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

# Hàm lấy dữ liệu từ tất cả sheet trong file (từ app - Copy (2).py)
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

all_data = load_all_sheets() # Dữ liệu từ app - Copy (2).py

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

    #   Bổ sung form bấm gửi/xóa ở dưới
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

    # Đọc câu hỏi mẫu từ file
    sample_questions = []
    try:
        with open("sample_questions.json", "r", encoding="utf-8") as f:
            sample_questions = json.load(f)
    except Exception as e:
        st.warning(f"Không thể đọc file câu hỏi mẫu: {e}")

    # Callback function for selectbox
    def on_sample_question_select():
        # Khi một câu hỏi mẫu được chọn, cập nhật user_input_value
        st.session_state.user_input_value = st.session_state.sample_question_selector
        # Sau khi cập nhật, có thể muốn reset selectbox để nó không giữ lựa chọn cũ
        # st.session_state.sample_question_selector = "" # Tùy chọn: nếu muốn reset selectbox

    # Giao diện chọn câu hỏi
    selected_sample_question = st.selectbox(
        "Chọn câu hỏi từ danh sách:", 
        options=[""] + sample_questions, 
        index=0, 
        key="sample_question_selector",
        on_change=on_sample_question_select # Thêm callback function
    )

    # ✅ Ưu tiên lấy nội dung nhập tay/micro trước, sau đó là câu hỏi mẫu
    # Logic này sẽ được kích hoạt sau khi on_change callback chạy (nếu có)
    question_to_process = st.session_state.user_input_value.strip()
    # Không cần kiểm tra selected_sample_question ở đây nữa vì nó đã được xử lý qua callback

    # Xử lý nút Xóa
    if clear_button_pressed:
        st.session_state.user_input_value = ""
        st.session_state.qa_results = []
        st.session_state.qa_index = 0
        st.session_state.last_processed_user_msg = ""
        st.session_state.current_qa_display = ""
        st.session_state.audio_processed = False
        st.rerun()

    # Xử lý khi nhấn nút Gửi
    if send_button_pressed and question_to_process:
        st.info(f"📨 Đang xử lý câu hỏi: {question_to_process}")
        st.session_state.last_processed_user_msg = question_to_process
        # st.session_state.user_input_value = "" # Comment out this line to keep the input after submission
        st.session_state.audio_processed = False

        # Reset QA results and display for a new query
        st.session_state.qa_results = []
        st.session_state.qa_index = 0 
        st.session_state.current_qa_display = "" # Clear previous display

        user_msg_lower = question_to_process.lower() # Bây giờ user_msg_lower được lấy từ question_to_process

        # --- Bổ sung logic tìm kiếm câu trả lời trong sheet "Hỏi-Trả lời" ---
        found_qa_answer = False

        # NEW LOGIC: Kiểm tra cú pháp "An toàn:..." để yêu cầu khớp chính xác 100% sau khi chuẩn hóa
        if user_msg_lower.startswith("an toàn:"):
            # Trích xuất và chuẩn hóa phần câu hỏi thực tế sau "An toàn:"
            specific_question_for_safety = normalize_text(user_msg_lower.replace("an toàn:", "").strip())

            if not qa_df.empty and 'Câu hỏi' in qa_df.columns and 'Câu trả lời' in qa_df.columns:
                exact_match_found_for_safety = False
                for index, row in qa_df.iterrows():
                    question_from_sheet_normalized = normalize_text(str(row['Câu hỏi']))

                    # So sánh chính xác 100% sau khi đã chuẩn hóa
                    if specific_question_for_safety == question_from_sheet_normalized:
                        st.session_state.qa_results.append(str(row['Câu trả lời']))
                        exact_match_found_for_safety = True
                        found_qa_answer = True
                        # Không break để vẫn có thể tìm các câu trả lời khác nếu có nhiều bản ghi giống hệt

                if not exact_match_found_for_safety:
                    st.warning("⚠️ Không tìm thấy câu trả lời chính xác 100% cho yêu cầu 'An toàn:' của bạn. Vui lòng đảm bảo câu hỏi khớp hoàn toàn (có thể bỏ qua dấu cách thừa).")
                    found_qa_answer = True # Đánh dấu là đã xử lý nhánh này, dù không tìm thấy khớp đủ cao

        # Logic hiện có cho các câu hỏi chung (khớp tương đối)
        # Chỉ chạy nếu chưa tìm thấy câu trả lời từ nhánh "An toàn:"
        if not found_qa_answer and not qa_df.empty and 'Câu hỏi' in qa_df.columns and 'Câu trả lời' in qa_df.columns:

            # Collect all relevant answers with their scores
            all_matches = []
            for index, row in qa_df.iterrows():
                question_from_sheet = str(row['Câu hỏi']).lower()
                score = fuzz.ratio(user_msg_lower, question_from_sheet)

                if score >= 60: # Threshold for similarity
                    all_matches.append({'question': str(row['Câu hỏi']), 'answer': str(row['Câu trả lời']), 'score': score})

            # Sort matches by score in descending order
            all_matches.sort(key=lambda x: x['score'], reverse=True)

            if all_matches:
                # Store only the answers in session state for "Tìm tiếp" functionality
                st.session_state.qa_results = [match['answer'] for match in all_matches]
                st.session_state.qa_index = 0 # Start with the first result
                found_qa_answer = True
            else:
                found_qa_answer = False # No matches found

        if found_qa_answer:
            # Set the initial display content
            if st.session_state.qa_results:
                st.session_state.current_qa_display = st.session_state.qa_results[st.session_state.qa_index]
                if len(st.session_state.qa_results) > 1:
                    st.session_state.qa_index += 1 # Move to the next index for "Tìm tiếp"
            pass # Đã tìm thấy câu trả lời từ QA sheet, không làm gì thêm
        else:
            # Xử lý truy vấn để lấy dữ liệu từ BẤT KỲ sheet nào (ƯU TIÊN HÀNG ĐẦU)
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
                        st.warning("⚠️ Vui lòng cung cấp tên sheet rõ ràng. Ví dụ: 'lấy dữ liệu sheet DoanhThu'.")
            # Xử lý truy vấn liên quan đến KPI (sheet "KPI")
            elif "kpi" in user_msg_lower or "chỉ số hiệu suất" in user_msg_lower or "kết quả hoạt động" in user_msg_lower:
                records = get_sheet_data("KPI") # Tên sheet KPI
                if records:
                    df_kpi = pd.DataFrame(records)
                    # Cải thiện: Trích xuất năm từ chuỗi "Năm YYYY" trước khi chuyển đổi sang số
                    if 'Năm' in df_kpi.columns:
                        # Đảm bảo cột 'Năm' là chuỗi và xử lý các giá trị không phải chuỗi
                        df_kpi['Năm'] = df_kpi['Năm'].astype(str).str.extract(r'(\d{4})')[0]
                        df_kpi['Năm'] = pd.to_numeric(df_kpi['Năm'], errors='coerce').dropna().astype(int)
                    else:
                        st.warning("⚠️ Không tìm thấy cột 'Năm' trong sheet 'KPI'. Một số chức năng KPI có thể không hoạt động.")
                        df_kpi = pd.DataFrame() # Đảm bảo df_kpi rỗng nếu không có cột Năm
                    # NEW: Chuyển đổi cột 'Tháng' sang kiểu số nguyên một cách vững chắc
                    if 'Tháng' in df_kpi.columns:
                        df_kpi['Tháng'] = pd.to_numeric(df_kpi['Tháng'], errors='coerce').dropna().astype(int)
                    else:
                        st.warning("⚠️ Không tìm thấy cột 'Tháng' trong sheet 'KPI'. Một số chức năng KPI có thể không hoạt động.")
                        df_kpi = pd.DataFrame()
            else:
                # Gọi OpenAI để tạo phản hồi cho các truy vấn khác
                if client_ai:
                    with st.spinner("Đang xử lý với OpenAI..."):
                        try:
                            # Chuẩn bị context và prompt
                            prompt = (
                                f"Bạn là một trợ lý AI thông minh và thân thiện, chuyên tư vấn về các hoạt động của Đội Quản lý đường lâm nghiệp khu vực Định Hóa. "
                                f"Dưới đây là một số dữ liệu bạn có thể tham khảo: \n\n"
                                f"Dữ liệu các sheet: {all_data}\n\n" # Bổ sung tất cả dữ liệu
                                f"Câu hỏi của người dùng: {question_to_process}\n\n"
                                f"Dựa trên các dữ liệu trên, hãy trả lời câu hỏi của người dùng. Nếu dữ liệu không đủ, hãy trả lời một cách lịch sự rằng bạn không thể trả lời câu hỏi đó."
                            )
                            response = client_ai.chat.completions.create(
                                model="gpt-3.5-turbo",
                                messages=[
                                    {"role": "system", "content": prompt}
                                ],
                                max_tokens=2500,
                                temperature=0.5
                            )
                            ai_response = response.choices[0].message.content
                            st.info("Câu trả lời từ OpenAI:")
                            st.write(ai_response)
                        except Exception as e:
                            st.error(f"❌ Lỗi khi gọi OpenAI API: {e}. Vui lòng kiểm tra lại API key hoặc kết nối internet.")
                else:
                    st.error("❌ Không tìm thấy API key OpenAI. Vui lòng cấu hình trong secrets.toml.")

    # Hiển thị câu trả lời từ Google Sheet nếu có
    if st.session_state.current_qa_display:
        st.info("Câu trả lời:")
        st.write(st.session_state.current_qa_display)

    # Nút "Tìm tiếp" chỉ hiển thị khi có nhiều hơn một kết quả QA và chưa hiển thị hết
    if st.session_state.qa_results and st.session_state.qa_index < len(st.session_state.qa_results):
        if st.button("Tìm tiếp"):
            st.session_state.current_qa_display = st.session_state.qa_results[st.session_state.qa_index]
            st.session_state.qa_index += 1
            st.rerun() # Rerun để hiển thị kết quả tiếp theo
    elif st.session_state.qa_results and st.session_state.qa_index >= len(st.session_state.qa_results) and len(st.session_state.qa_results) > 1:
        st.info("Đã hiển thị tất cả các câu trả lời tương tự.")


# Hàm OCR: đọc text từ ảnh
def extract_text_from_image(image_path):
    reader = easyocr.Reader(['vi'])
    result = reader.readtext(image_path, detail=0)
    text = " ".join(result)
    return text

# --- Đặt đoạn này vào cuối file app.py ---
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
            # Tự động điền văn bản đã trích xuất vào ô nhập liệu
            st.session_state.user_input_value = extracted_text
            st.success("✅ Đã điền văn bản vào ô nhập liệu. Bạn có thể chỉnh sửa và nhấn 'Gửi'.")
            st.rerun() # Tải lại ứng dụng để cập nhật input
        else:
            st.warning("⚠️ Không trích xuất được văn bản từ ảnh. Vui lòng thử lại với ảnh rõ hơn.")
    except Exception as e:
        st.error(f"❌ Lỗi khi xử lý ảnh: {e}")
    finally:
        if temp_image_path.exists():
            os.remove(temp_image_path)
