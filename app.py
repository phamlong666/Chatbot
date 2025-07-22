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
from audio_recorder_streamlit import audio_recorder  # ✅ Thay thế thư viện mic_recorder bằng thư viện ổn định hơn

# Cấu hình Streamlit page để sử dụng layout rộng
st.set_page_config(layout="wide")

# Cấu hình Matplotlib để hiển thị tiếng Việt
plt.rcParams['font.family'] = 'DejaVu Sans' # Hoặc 'Arial', 'Times New Roman' nếu có
plt.rcParams['font.size'] = 10
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['xtick.labelsize'] = 10
plt.rcParams['ytick.labelsize'] = 10
plt.rcParams['figure.titlesize'] = 16

# Kết nối Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

if "google_service_account" in st.secrets:
    info = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
else:
    st.error("❌ Không tìm thấy google_service_account trong secrets. Vui lòng cấu hình.")
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

# Hàm để lấy dữ liệu từ một sheet cụ thể
def get_sheet_data(sheet_name):
    try:
        spreadsheet_url = "https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit"
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
    if 'user_input_value' not in st.session_state:
        st.session_state.user_input_value = ""
    if 'current_qa_display' not in st.session_state: # NEW: To hold the currently displayed QA answer
        st.session_state.current_qa_display = ""
    # Khởi tạo key động cho text_area (không còn cần thiết cho input chính nhưng giữ lại nếu có chỗ khác dùng)
    if 'text_area_key' not in st.session_state:
        st.session_state.text_area_key = 0

    # Ghi âm nằm ngoài form, chạy độc lập
    audio_bytes = audio_recorder(
        text="🎙 Nhấn để nói",
        recording_color="#e8b62c",
        neutral_color="#6aa36f",
        icon_size="2x"
    )

    if audio_bytes:
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
                    st.session_state.user_input_value = text # Cập nhật session state
                    st.rerun() # Rerun để cập nhật ô nhập liệu
                except sr.UnknownValueError:
                    st.warning("⚠️ Không nhận dạng được giọng nói.")
                except sr.RequestError as e:
                    st.error(f"❌ Lỗi nhận dạng: {e}")
        finally:
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)

    # 🔄 Bổ sung form bấm gửi/xóa ở dưới
    with st.form(key='chat_buttons_form'):
        mic_col, send_button_col, clear_button_col = st.columns([9, 1, 1])
        
        with mic_col:
            # Đây là ô nhập liệu chính hiện tại, giá trị được lấy từ session_state.user_input_value
            user_msg_input_in_form = st.text_input("Nhập lệnh hoặc dùng micro để nói:", value=st.session_state.get("user_input_value", ""), key="text_input_key")

        with send_button_col:
            send_button_pressed = st.form_submit_button("Gửi")
        with clear_button_col:
            clear_button_pressed = st.form_submit_button("Xóa")

    # ✅ Xử lý lệnh từ micro hoặc nhập tay hoặc chọn câu hỏi
    st.markdown("### 📝 Hoặc chọn câu hỏi mẫu:")
    selected_sample_question = st.selectbox(
        "Chọn câu hỏi từ danh sách:", 
        options=["", "lấy danh sách lãnh đạo xã Định Hóa", "Ai là giám đốc Điện lực?"], 
        index=0,
        key="sample_question_selector"
    )

    # Logic để cập nhật user_input_value khi chọn câu hỏi mẫu
    # So sánh với giá trị hiện tại của text_input_key để tránh rerun không cần thiết
    if selected_sample_question and selected_sample_question != st.session_state.get("text_input_key", ""):
        st.session_state.user_input_value = selected_sample_question # Cập nhật session state
        st.rerun() # Rerun để cập nhật ô nhập liệu

    if clear_button_pressed:
        st.session_state.user_input_value = "" # Xóa giá trị trong session state
        st.session_state.text_input_key = "" # Xóa giá trị trong widget nhập liệu
        st.session_state.qa_results = []
        st.session_state.qa_index = 0
        st.session_state.last_processed_user_msg = ""
        st.session_state.current_qa_display = ""
        st.rerun()

    # Logic xử lý câu hỏi chính chỉ chạy khi nút "Gửi" được nhấn
    if send_button_pressed:
        # Lấy giá trị từ ô nhập liệu chính (text_input_key) để xử lý
        user_msg = st.session_state.get("text_input_key", "")
        if user_msg: # Chỉ xử lý nếu có nội dung nhập vào
            st.session_state.last_processed_user_msg = user_msg # Cập nhật tin nhắn cuối cùng đã xử lý
            st.session_state.user_input_value = "" # Đặt lại giá trị ẩn
            st.session_state.text_input_key = "" # Xóa nội dung trong ô nhập liệu sau khi gửi
            user_msg_lower = user_msg.lower()

            # Reset QA results and display for a new query
            st.session_state.qa_results = []
            st.session_state.qa_index = 0 
            st.session_state.current_qa_display = "" # Clear previous display

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
                            df_kpi = pd.DataFrame() # Đảm bảo df_kpi rỗng nếu không có cột Tháng


                        if not df_kpi.empty:
                            st.subheader("Dữ liệu KPI")
                            st.dataframe(df_kpi)

                            target_year_kpi = None
                            kpi_year_match = re.search(r"năm\s+(\d{4})", user_msg_lower)
                            if kpi_year_match:
                                target_year_kpi = kpi_year_match.group(1)

                            unit_name_from_query = None
                            # Ánh xạ tên đơn vị trong câu hỏi với tên cột trong Google Sheet
                            unit_column_mapping = {
                                "định hóa": "Định Hóa",
                                "đồng hỷ": "Đồng Hỷ",
                                "đại từ": "Đại Từ",
                                "phú bình": "Phú Bình",
                                "phú lương": "Phú Lương",
                                "phổ yên": "Phổ Yên",
                                "sông công": "Sông Công",
                                "thái nguyên": "Thái Nguyên",
                                "võ nhai": "Võ Nhai"
                            }
                            
                            # Cải thiện logic trích xuất unit_name_from_query
                            # Lặp qua các key trong unit_column_mapping để tìm khớp trong user_msg_lower
                            for unit_key, unit_col_name in unit_column_mapping.items():
                                if unit_key in user_msg_lower:
                                    unit_name_from_query = unit_key
                                    break # Tìm thấy khớp đầu tiên thì dừng lại

                            # Lấy các cột đơn vị thực sự có trong DataFrame
                            actual_unit_columns_in_df = [col for col in unit_column_mapping.values() if col in df_kpi.columns]

                            # Lấy thông tin KPI năm X so sánh với các năm trước (biểu đồ line)
                            if target_year_kpi and "so sánh" in user_msg_lower:
                                st.subheader(f"Biểu đồ KPI theo tháng cho năm {target_year_kpi} và các năm trước")

                                kpi_value_column = 'Điểm KPI' # Cột giá trị KPI cố định
                                can_plot_line_chart = True

                                if unit_name_from_query: # Nếu có đơn vị cụ thể trong câu hỏi
                                    # Lấy tên đơn vị chính xác từ mapping để khớp với cột 'Đơn vị'
                                    selected_unit = unit_column_mapping.get(unit_name_from_query)
                                    if selected_unit:
                                        # Lọc DataFrame cho đơn vị cụ thể
                                        df_to_plot_line = df_kpi[df_kpi['Đơn vị'].astype(str).str.lower() == selected_unit.lower()].copy()
                                        
                                        if df_to_plot_line.empty:
                                            st.warning(f"⚠️ Không tìm thấy dữ liệu cho đơn vị '{selected_unit}' trong sheet 'KPI'. Vui lòng kiểm tra tên đơn vị.")
                                            can_plot_line_chart = False
                                    else:
                                        st.warning(f"⚠️ Không tìm thấy tên đơn vị hợp lệ trong câu hỏi của bạn. Vui lòng kiểm tra lại.")
                                        can_plot_line_chart = False
                                else: # Không có đơn vị cụ thể, không thể vẽ biểu đồ so sánh đường
                                    st.warning("⚠️ Vui lòng chỉ định đơn vị cụ thể (ví dụ: 'Định Hóa') để vẽ biểu đồ KPI so sánh năm.")
                                    can_plot_line_chart = False

                                if can_plot_line_chart and target_year_kpi and 'Năm' in df_to_plot_line.columns and 'Tháng' in df_to_plot_line.columns and kpi_value_column in df_to_plot_line.columns:
                                    try:
                                        # Cải thiện: Thay thế dấu phẩy bằng dấu chấm trước khi chuyển đổi sang số
                                        # Sử dụng .loc để tránh SettingWithCopyWarning
                                        df_to_plot_line.loc[:, kpi_value_column] = df_to_plot_line[kpi_value_column].astype(str).str.replace(',', '.', regex=False)
                                        df_to_plot_line.loc[:, kpi_value_column] = pd.to_numeric(df_to_plot_line[kpi_value_column], errors='coerce')
                                        
                                        # CHỈ LOẠI BỎ HÀNG NẾU KPI BỊ THIẾU ĐỂ GIỮ CÁC THÁNG ĐẦY ĐỦ
                                        df_to_plot_line = df_to_plot_line.dropna(subset=[kpi_value_column]) # Chỉ loại bỏ nếu KPI thiếu

                                        fig, ax = plt.subplots(figsize=(14, 8))
                                        
                                        # Lọc theo năm mục tiêu và các năm trước đó
                                        years_to_compare = [int(target_year_kpi)]
                                        # Lấy các năm khác có dữ liệu
                                        other_years_in_data = [y for y in df_to_plot_line['Năm'].unique() if y != int(target_year_kpi)]
                                        years_to_compare.extend(sorted(other_years_in_data, reverse=True))

                                        colors = cm.get_cmap('tab10', len(years_to_compare))

                                        for i, year in enumerate(years_to_compare):
                                            df_year = df_to_plot_line[df_to_plot_line['Năm'] == year].sort_values(by='Tháng')
                                            
                                            if str(year) == target_year_kpi:
                                                # Chỉ vẽ đến tháng có dữ liệu cho năm hiện tại
                                                last_valid_month = df_year[df_year[kpi_value_column].notna()]['Tháng'].max()
                                                if last_valid_month is not None:
                                                    df_year_filtered = df_year[df_year['Tháng'] <= last_valid_month]
                                                else:
                                                    df_year_filtered = df_year
                                                
                                                ax.plot(df_year_filtered['Tháng'], df_year_filtered[kpi_value_column], 
                                                        marker='o', label=f'Năm {year}', color=colors(i), linestyle='-') # Ensure solid line
                                                # Thêm giá trị trên đường cho năm mục tiêu (tùy chọn, có thể gây rối nếu nhiều điểm)
                                                for x, y in zip(df_year_filtered['Tháng'], df_year_filtered[kpi_value_column]):
                                                    # Chỉ thêm text nếu giá trị không phải NaN
                                                    if pd.notna(y):
                                                        ax.text(x, y + (ax.get_ylim()[1] * 0.01), f'{y:.1f}', ha='center', va='bottom', fontsize=8, color=colors(i))
                                            else:
                                                # Vẽ đủ 12 tháng cho các năm trước. ax.plot sẽ tự động bỏ qua NaN
                                                ax.plot(df_year['Tháng'], df_year[kpi_value_column], 
                                                        marker='x', linestyle='-', label=f'Năm {year}', color=colors(i), alpha=0.7) # Ensure solid line
                                                # Thêm giá trị trên đường cho các năm trước (tùy chọn, có thể gây rối nếu nhiều điểm)
                                                for x, y in zip(df_year['Tháng'], df_year[kpi_value_column]):
                                                    if pd.notna(y):
                                                        ax.text(x, y + (ax.get_ylim()[1] * 0.01), f'{y:.1f}', ha='center', va='bottom', fontsize=8, color=colors(i), alpha=0.7)


                                        ax.set_xlabel("Tháng")
                                        ax.set_ylabel("Giá trị KPI")
                                        chart_title_suffix = f"của {selected_unit}" if selected_unit else "" # Use selected_unit here
                                        ax.set_title(f"So sánh KPI theo tháng {chart_title_suffix} (Năm {target_year_kpi} vs các năm khác)")
                                        ax.set_xticks(range(1, 13))
                                        ax.legend()
                                        plt.grid(True)
                                        plt.tight_layout()
                                        st.pyplot(fig, dpi=400)

                                    except Exception as e:
                                        st.error(f"❌ Lỗi khi vẽ biểu đồ KPI so sánh năm: {e}. Vui lòng kiểm tra định dạng dữ liệu trong sheet (cột 'Tháng', 'Năm', và '{kpi_value_column}').")
                                else:
                                    if can_plot_line_chart: # Chỉ hiển thị cảnh báo nếu việc vẽ biểu đồ được mong đợi nhưng thiếu cột
                                        st.warning("⚠️ Không tìm thấy các cột cần thiết ('Tháng', 'Năm', hoặc cột giá trị KPI) trong dữ liệu đã lọc để vẽ biểu đồ so sánh.")

                            # Lấy thông tin KPI của các đơn vị năm X (biểu đồ cột)
                            elif target_year_kpi and ("các đơn vị" in user_msg_lower or unit_name_from_query):
                                st.subheader(f"Biểu đồ KPI của các đơn vị năm {target_year_kpi}")

                                can_plot_bar_chart = True
                                
                                # Lọc DataFrame theo năm mục tiêu
                                df_kpi_year = df_kpi[df_kpi['Năm'] == int(target_year_kpi)].copy()

                                # NEW: Extract target month and cumulative flag
                                target_month_kpi = None
                                month_match = re.search(r"tháng\s+(\d{1,2})", user_msg_lower)
                                if month_match:
                                    target_month_kpi = int(month_match.group(1))

                                is_cumulative = "lũy kế" in user_msg_lower

                                if not df_kpi_year.empty:
                                    # Ensure 'Điểm KPI' is numeric and handle commas
                                    df_kpi_year.loc[:, 'Điểm KPI'] = df_kpi_year['Điểm KPI'].astype(str).str.replace(',', '.', regex=False)
                                    df_kpi_year.loc[:, 'Điểm KPI'] = pd.to_numeric(df_kpi_year[kpi_value_column], errors='coerce')
                                    
                                    # Drop rows where 'Điểm KPI' is NaN after conversion
                                    df_kpi_year = df_kpi_year.dropna(subset=[kpi_value_column])

                                    unit_kpis_aggregated = {}
                                    
                                    if unit_name_from_query: # Nếu có yêu cầu đơn vị cụ thể
                                        selected_unit = unit_column_mapping.get(unit_name_from_query)
                                        if selected_unit:
                                            unit_data = df_kpi_year[df_kpi_year['Đơn vị'].astype(str).str.lower() == selected_unit.lower()]
                                            
                                            if not unit_data.empty:
                                                if target_month_kpi:
                                                    # Filter for specific month
                                                    monthly_data = unit_data[unit_data['Tháng'] == target_month_kpi]
                                                    if not monthly_data.empty:
                                                        unit_kpis_aggregated[selected_unit] = monthly_data[kpi_value_column].mean() # Mean for that specific month
                                                    else:
                                                        st.warning(f"⚠️ Không có dữ liệu KPI cho đơn vị '{selected_unit}' trong tháng {target_month_kpi} năm {target_year_kpi}.")
                                                        can_plot_bar_chart = False
                                                elif is_cumulative:
                                                    current_month = datetime.datetime.now().month
                                                    cumulative_data = unit_data[unit_data['Tháng'] <= current_month]
                                                    if not cumulative_data.empty:
                                                        unit_kpis_aggregated[selected_unit] = cumulative_data[kpi_value_column].mean() # Mean for cumulative months
                                                    else:
                                                        st.warning(f"⚠️ Không có dữ liệu KPI lũy kế cho đơn vị '{selected_unit}' đến tháng {current_month} năm {target_year_kpi}.")
                                                        can_plot_bar_chart = False
                                                else:
                                                    # Default: mean for the whole year for the specific unit
                                                    unit_kpis_aggregated[selected_unit] = unit_data[kpi_value_column].mean()
                                            else:
                                                st.warning(f"⚠️ Không có dữ liệu KPI cho đơn vị '{selected_unit}' trong năm {target_year_kpi}.")
                                                can_plot_bar_chart = False
                                        else:
                                            st.warning(f"⚠️ Không tìm thấy tên đơn vị hợp lệ trong câu hỏi của bạn. Vui lòng kiểm tra lại.")
                                            can_plot_bar_chart = False
                                    else: # If no specific unit, aggregate for all units
                                        if 'Đơn vị' in df_kpi_year.columns:
                                            if target_month_kpi:
                                                # Filter for specific month for all units
                                                monthly_data_all_units = df_kpi_year[df_kpi_year['Tháng'] == target_month_kpi]
                                                if not monthly_data_all_units.empty:
                                                    unit_kpis_aggregated = monthly_data_all_units.groupby('Đơn vị')[kpi_value_column].mean().to_dict()
                                                else:
                                                    st.warning(f"⚠️ Không có dữ liệu KPI cho tháng {target_month_kpi} năm {target_year_kpi} cho bất kỳ đơn vị nào.")
                                                    can_plot_bar_chart = False
                                            elif is_cumulative:
                                                current_month = datetime.datetime.now().month
                                                cumulative_data_all_units = df_kpi_year[df_kpi_year['Tháng'] <= current_month]
                                                if not cumulative_data_all_units.empty:
                                                    unit_kpis_aggregated = cumulative_data_all_units.groupby('Đơn vị')[kpi_value_column].mean().to_dict()
                                                else:
                                                    st.warning(f"⚠️ Không có dữ liệu KPI lũy kế đến tháng {current_month} năm {target_year_kpi} cho bất kỳ đơn vị nào.")
                                                    can_plot_bar_chart = False
                                            else:
                                                # Default: mean for the whole year for all units
                                                unit_kpis_aggregated = df_kpi_year.groupby('Đơn vị')[kpi_value_column].mean().to_dict()
                                        else:
                                            st.warning("⚠️ Không tìm thấy cột 'Đơn vị' trong sheet 'KPI' để tổng hợp dữ liệu.")
                                            can_plot_bar_chart = False

                                    if can_plot_bar_chart and unit_kpis_aggregated:
                                        unit_kpis_df = pd.DataFrame(list(unit_kpis_aggregated.items()), columns=['Đơn vị', 'Giá trị KPI'])
                                        unit_kpis_df = unit_kpis_df.sort_values(by='Giá trị KPI', ascending=False)

                                        fig, ax = plt.subplots(figsize=(12, 7))
                                        colors = cm.get_cmap('tab20', len(unit_kpis_df['Đơn vị']))

                                        bars = ax.bar(unit_kpis_df['Đơn vị'], unit_kpis_df['Giá trị KPI'], color=colors.colors)

                                        for bar in bars:
                                            yval = bar.get_height()
                                            ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, round(yval, 2), ha='center', va='bottom', color='black')

                                        chart_title_prefix = f"KPI của {selected_unit}" if unit_name_from_query and selected_unit else "KPI của các đơn vị"
                                        
                                        if target_month_kpi:
                                            chart_title_suffix = f"tháng {target_month_kpi} năm {target_year_kpi}"
                                        elif is_cumulative:
                                            chart_title_suffix = f"lũy kế đến tháng {datetime.datetime.now().month} năm {target_year_kpi}"
                                        else:
                                            chart_title_suffix = f"năm {target_year_kpi}"

                                        ax.set_title(f"{chart_title_prefix} {chart_title_suffix}")
                                        ax.set_xlabel("Đơn vị")
                                        ax.set_ylabel("Giá trị KPI")
                                        plt.xticks(rotation=45, ha='right')
                                        plt.tight_layout()
                                        st.pyplot(fig, dpi=400)
                                    elif can_plot_bar_chart:
                                        st.warning(f"⚠️ Không có dữ liệu KPI tổng hợp để vẽ biểu đồ cho năm {target_year_kpi}.")
                                else:
                                    st.warning(f"⚠️ Không có dữ liệu KPI cho năm {target_year_kpi} để vẽ biểu đồ đơn vị.")
                            elif "biểu đồ" in user_msg_lower and not target_year_kpi:
                                st.warning("⚠️ Vui lòng chỉ định năm bạn muốn xem biểu đồ KPI (ví dụ: 'biểu đồ KPI năm 2025').")

                        else:
                            st.warning("⚠️ Dữ liệu KPI rỗng, không thể hiển thị hoặc vẽ biểu đồ.")
                    else:
                        st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet KPI. Vui lòng kiểm tra tên sheet và quyền truy cập.")

                # Xử lý truy vấn liên quan đến sheet "Quản lý sự cố"
                elif "sự cố" in user_msg_lower or "quản lý sự cố" in user_msg_lower:
                    records = get_sheet_data("Quản lý sự cố") # Tên sheet chính xác từ hình ảnh
                    if records:
                        df_suco = pd.DataFrame(records)

                        target_year = None
                        target_month = None
                        compare_year = None # Biến mới để lưu năm so sánh

                        # Cố gắng trích xuất "tháng MM/YYYY" hoặc "tháng MM"
                        month_year_full_match = re.search(r"tháng\s+(\d{1,2})(?:/(\d{4}))?", user_msg_lower)
                        if month_year_full_match:
                            target_month = month_year_full_match.group(1)
                            target_year = month_year_full_match.group(2) # Có thể là None nếu chỉ có tháng

                        # Nếu năm chưa được trích xuất từ "tháng MM/YYYY", cố gắng trích xuất từ "nămYYYY"
                        if not target_year:
                            year_only_match = re.search(r"năm\s+(\d{4})", user_msg_lower)
                            if year_only_match:
                                target_year = year_only_match.group(1)

                        # Bổ sung logic trích xuất năm so sánh (ví dụ: "so sánh 2025 với 2024")
                        compare_match = re.search(r"so sánh.*?(\d{4}).*?với.*?(\d{4})", user_msg_lower)
                        if compare_match:
                            target_year = compare_match.group(1)
                            compare_year = compare_match.group(2)
                            st.info(f"Đang so sánh sự cố năm {target_year} với năm {compare_year}.")
                        # NEW: Handle "cùng kỳ" without explicit year
                        elif "cùng kỳ" in user_msg_lower:
                            # Try to find a year for "cùng kỳ" explicitly, otherwise default
                            cung_ky_year_match = re.search(r"cùng kỳ\s+(\d{4})", user_msg_lower)
                            if cung_ky_year_match:
                                compare_year = cung_ky_year_match.group(1)

                            # If target_year is not set yet, default to current year (e.g., 2025)
                            if not target_year:
                                # import datetime
                                target_year = str(datetime.datetime.now().year)

                            # If compare_year was not explicitly given, derive it from target_year
                            if not compare_year:
                                try:
                                    compare_year = str(int(target_year) - 1)
                                except (ValueError, TypeError):
                                    st.warning("⚠️ Không thể xác định năm so sánh cho 'cùng kỳ'. Vui lòng cung cấp năm cụ thể hoặc đảm bảo năm mục tiêu hợp lệ.")
                                    compare_year = None # Reset to None if calculation fails

                            if target_year and compare_year:
                                st.info(f"Đang so sánh sự cố năm {target_year} với cùng kỳ năm {compare_year}.")
                            else:
                                st.warning("⚠️ Không đủ thông tin để thực hiện so sánh 'cùng kỳ'. Vui lòng chỉ định năm hoặc đảm bảo cú pháp hợp lệ.")
                                compare_year = None # Ensure compare_year is None if we can't form a valid comparison


                        filtered_df_suco = df_suco # Khởi tạo với toàn bộ dataframe

                        # Kiểm tra sự tồn tại của cột 'Tháng/Năm sự cố'
                        if 'Tháng/Năm sự cố' not in df_suco.columns:
                            st.warning("⚠️ Không tìm thấy cột 'Tháng/Năm sự cố' trong sheet 'Quản lý sự cố'. Không thể lọc theo tháng/năm.")
                            # Nếu cột bị thiếu, không thể lọc theo tháng/năm, hiển thị toàn bộ dữ liệu hoặc không có gì
                            if target_month or target_year or compare_year: # Nếu có yêu cầu lọc/so sánh nhưng cột thiếu
                                st.info("Hiển thị toàn bộ dữ liệu sự cố (nếu có) do không tìm thấy cột lọc tháng/năm.")
                                # filtered_df_suco vẫn là df_suco ban đầu
                            else:
                                pass # filtered_df_suco đã là df_suco
                        else:
                            # Thực hiện lọc dựa trên tháng và năm đã trích xuất
                            # Chuẩn hóa cột 'Tháng/Năm sự cố' để đảm bảo kiểu dữ liệu chuỗi và xử lý NaN
                            df_suco['Tháng/Năm sự cố'] = df_suco['Tháng/Năm sự cố'].astype(str).fillna('')

                            if target_year and not compare_year: # Chỉ lọc theo một năm nếu không phải so sánh
                                # Lọc theo hậu tố năm "/YYYY"
                                year_suffix = f"/{target_year}"
                                filtered_df_suco = df_suco[df_suco['Tháng/Năm sự cố'].str.endswith(year_suffix)]
                                if target_month: # Nếu có cả tháng và năm
                                    exact_match_str = f"{int(target_month):02d}/{target_year}"
                                    filtered_df_suco = filtered_df_suco[filtered_df_suco['Tháng/Năm sự cố'] == exact_match_str]
                            elif target_year and compare_year: # Xử lý so sánh hai năm
                                # Lọc dữ liệu cho năm mục tiêu
                                df_target_year = df_suco[df_suco['Tháng/Năm sự cố'].str.endswith(f"/{target_year}")].copy()
                                # Lọc dữ liệu cho năm so sánh
                                df_compare_year = df_suco[df_suco['Tháng/Năm sự cố'].str.endswith(f"/{compare_year}")].copy()

                                # Nếu có tháng cụ thể, lọc thêm theo tháng
                                if target_month:
                                    month_prefix = f"{int(target_month):02d}/"
                                    df_target_year = df_target_year[df_target_year['Tháng/Năm sự cố'].str.startswith(month_prefix)]
                                    df_compare_year = df_compare_year[df_compare_year['Tháng/Năm sự cố'].str.startswith(month_prefix)]

                                # Gộp dữ liệu của hai năm để hiển thị và vẽ biểu đồ so sánh
                                filtered_df_suco = pd.concat([df_target_year.assign(Năm=target_year),
                                                              df_compare_year.assign(Năm=compare_year)])
                                # Đảm bảo cột 'Năm' được thêm vào để phân biệt dữ liệu khi vẽ biểu đồ

                            elif target_month and not target_year: # Chỉ lọc theo tháng nếu không có năm
                                # Lọc theo tiền tố tháng "MM/"
                                month_prefix = f"{int(target_month):02d}/"
                                filtered_df_suco = df_suco[df_suco['Tháng/Năm sự cố'].str.startswith(month_prefix)]


                        if filtered_df_suco.empty and (target_month or target_year or compare_year):
                            st.warning(f"⚠️ Không tìm thấy sự cố nào {'trong tháng ' + target_month if target_month else ''} {'năm ' + target_year if target_year else ''} {'hoặc năm ' + compare_year if compare_year else ''}.")
                            # Không hiển thị toàn bộ dataframe nếu có yêu cầu tháng/năm cụ thể mà không tìm thấy

                        if not filtered_df_suco.empty:
                            subheader_text = "Dữ liệu từ sheet 'Quản lý sự cố'"
                            if target_month and target_year and not compare_year:
                                subheader_text += f" tháng {int(target_month):02d} năm {target_year}"
                            elif target_year and not compare_year:
                                subheader_text += f" năm {target_year}"
                            elif target_month and not target_year:
                                subheader_text += f" tháng {int(target_month):02d}"
                            elif target_year and compare_year:
                                subheader_text += f" so sánh năm {target_year} và năm {compare_year}"

                            st.subheader(subheader_text + ":")
                            st.dataframe(filtered_df_suco) # Hiển thị dữ liệu đã lọc hoặc toàn bộ

                            # --- Bổ sung logic vẽ biểu đồ cho sheet "Quản lý sự cố" ---
                            if "biểu đồ" in user_msg_lower or "vẽ biểu đồ" in user_msg_lower:
                                chart_columns = []
                                if "đường dây" in user_msg_lower and 'Đường dây' in filtered_df_suco.columns:
                                    chart_columns.append('Đường dây')
                                if "tính chất" in user_msg_lower and 'Tính chất' in filtered_df_suco.columns:
                                    chart_columns.append('Tính chất')
                                if "loại sự cố" in user_msg_lower and 'Loại sự cố' in filtered_df_suco.columns:
                                    chart_columns.append('Loại sự cố')

                                if chart_columns:
                                    for col in chart_columns:
                                        # Fix: Chuyển đổi cột thành chuỗi và điền NaN để tránh lỗi TypeError khi value_counts() hoặc sort_index()
                                        if col in filtered_df_suco.columns and not filtered_df_suco[col].empty:
                                            # Đảm bảo cột là chuỗi và điền giá trị rỗng cho NaN
                                            col_data = filtered_df_suco[col].astype(str).fillna('Không xác định')

                                            if compare_year and 'Năm' in filtered_df_suco.columns: # Vẽ biểu đồ so sánh
                                                st.subheader(f"Biểu đồ so sánh số lượng sự cố theo '{col}' giữa năm {target_year} và năm {compare_year}")

                                                # Tạo bảng tần suất cho từng năm, xử lý NaN trước khi value_counts()
                                                counts_target = filtered_df_suco[filtered_df_suco['Năm'] == target_year][col].astype(str).fillna('Không xác định').value_counts().sort_index()
                                                counts_compare = filtered_df_suco[filtered_df_suco['Năm'] == compare_year][col].astype(str).fillna('Không xác định').value_counts().sort_index()

                                                # Gộp hai Series thành một DataFrame để dễ dàng vẽ biểu đồ nhóm
                                                combined_counts = pd.DataFrame({
                                                    f'Năm {target_year}': counts_target,
                                                    f'Năm {compare_year}': counts_compare
                                                }).fillna(0) # Điền 0 cho các giá trị không có trong một năm

                                                fig, ax = plt.subplots(figsize=(14, 8))

                                                # Vẽ biểu đồ cột nhóm
                                                bars = combined_counts.plot(kind='bar', ax=ax, width=0.8, colormap='viridis')

                                                # Thêm số liệu trên các cột biểu đồ nhóm
                                                for container in ax.containers:
                                                    ax.bar_label(container, fmt='%d', label_type='edge', fontsize=9, padding=3)

                                                ax.set_xlabel(col)
                                                ax.set_ylabel("Số lượng sự cố")
                                                ax.set_title(f"Biểu đồ so sánh số lượng sự cố theo {col} giữa năm {target_year} và năm {compare_year}")
                                                plt.xticks(rotation=45, ha='right')
                                                plt.tight_layout()
                                                st.pyplot(fig, dpi=400)

                                            else: # Vẽ biểu đồ cho một năm như bình thường
                                                st.subheader(f"Biểu đồ số lượng sự cố theo '{col}'")

                                                # Đếm số lượng các giá trị duy nhất trong cột, xử lý NaN trước khi value_counts()
                                                counts = col_data.value_counts()

                                                fig, ax = plt.subplots(figsize=(12, 7))
                                                colors = cm.get_cmap('tab10', len(counts.index))

                                                # Đảm bảo x_labels và y_values được định nghĩa ở đây
                                                x_labels = [str(item) for item in counts.index]
                                                y_values = counts.values

                                                bars = ax.bar(x_labels, y_values, color=colors.colors) # Sử dụng x_labels đã chuyển đổi

                                                # Thêm số liệu trên các cột biểu đồ đơn
                                                for bar in bars:
                                                    yval = bar.get_height()
                                                    ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, round(yval), ha='center', va='bottom', color='black')

                                                ax.set_xlabel("Bộ phận công tác" if col == 'Tính chất' else col) # Điều chỉnh nhãn x nếu cần
                                                ax.set_ylabel("Số lượng sự cố")
                                                ax.set_title(f"Biểu đồ số lượng sự cố theo {col}")
                                                plt.xticks(rotation=45, ha='right')
                                                plt.tight_layout()
                                                st.pyplot(fig, dpi=400)
                                        else:
                                            st.warning(f"⚠️ Cột '{col}' không có dữ liệu để vẽ biểu đồ hoặc không tồn tại.")
                                else:
                                    st.warning("⚠️ Vui lòng chỉ định cột bạn muốn vẽ biểu đồ (ví dụ: 'đường dây', 'tính chất', 'loại sự cố').")
                            else:
                                st.info("Để vẽ biểu đồ sự cố, bạn có thể thêm 'và vẽ biểu đồ theo [tên cột]' vào câu hỏi.")
                        else:
                            # Nếu filtered_df rỗng sau tất cả các bước lọc và không có thông báo cụ thể
                            # Điều này xảy ra nếu có yêu cầu tháng/năm cụ thể mà không tìm thấy dữ liệu
                            st.warning("⚠️ Không tìm thấy dữ liệu phù hợp với yêu cầu của bạn.")
                    else:
                        st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet 'Quản lý sự cố'. Vui lòng kiểm tra tên sheet và quyền truy cập.")

                # Xử lý truy vấn liên quan đến sheet "Danh sách lãnh đạo xã, phường" (Ưu tiên cao)
                elif any(k in user_msg_lower for k in ["lãnh đạo xã", "lãnh đạo phường", "lãnh đạo định hóa", "danh sách lãnh đạo"]):
                    records = get_sheet_data("Danh sách lãnh đạo xã, phường") # Tên sheet chính xác từ hình ảnh
                    if records:
                        df_lanhdao = pd.DataFrame(records)

                        location_name = None
                        match_xa_phuong = re.search(r"(xã|phường)\s+([a-zA-Z0-9\s]+)", user_msg_lower)
                        if match_xa_phuong:
                            location_name = match_xa_phuong.group(2).strip()
                        elif "định hóa" in user_msg_lower: # Ưu tiên "Định Hóa" nếu được nhắc đến cụ thể
                            location_name = "định hóa"

                        filtered_df_lanhdao = df_lanhdao
                        # Đảm bảo cột 'Thuộc xã/phường' tồn tại và lọc dữ liệu
                        if location_name and 'Thuộc xã/phường' in df_lanhdao.columns:
                            # Sử dụng str.contains để tìm kiếm linh hoạt hơn (không cần khớp chính xác)
                            # asType(str) để đảm bảo cột là kiểu chuỗi và xử lý NaN
                            filtered_df_lanhdao = df_lanhdao[df_lanhdao['Thuộc xã/phường'].astype(str).str.lower().str.contains(location_name.lower(), na=False)]

                            if filtered_df_lanhdao.empty:
                                st.warning(f"⚠️ Không tìm thấy lãnh đạo nào cho '{location_name.title()}'.")
                                st.dataframe(df_lanhdao) # Vẫn hiển thị toàn bộ dữ liệu nếu không tìm thấy kết quả lọc

                        if not filtered_df_lanhdao.empty:
                            subheader_parts = ["Dữ liệu từ sheet 'Danh sách lãnh đạo xã, phường'"]
                            if location_name:
                                subheader_parts.append(f"cho {location_name.title()}")
                            st.subheader(" ".join(subheader_parts) + ":")
                            st.dataframe(filtered_df_lanhdao) # Hiển thị dữ liệu đã lọc hoặc toàn bộ

                            # Bạn có thể thêm logic vẽ biểu đồ cho lãnh đạo xã/phường tại đây nếu cần
                            # Ví dụ: if "biểu đồ" in user_msg_lower: ...
                        else:
                            st.warning("⚠️ Dữ liệu từ sheet 'Danh sách lãnh đạo xã, phường' rỗng.")
                    else:
                        st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet 'Danh sách lãnh đạo xã, phường'. Vui lòng kiểm tra tên sheet và quyền truy cập.")

                # Xử lý truy vấn liên quan đến sheet "Tên các TBA"
                elif "tba" in user_msg_lower or "thông tin tba" in user_msg_lower:
                    records = get_sheet_data("Tên các TBA")
                    if records:
                        df_tba = pd.DataFrame(records)

                        line_name = None
                        power_capacity = None # Biến mới để lưu công suất

                        # Trích xuất tên đường dây
                        line_match = re.search(r"đường dây\s+([a-zA-Z0-9\.]+)", user_msg_lower)
                        if line_match:
                            line_name = line_match.group(1).upper() # Lấy tên đường dây và chuyển thành chữ hoa để khớp

                        # Trích xuất công suất (ví dụ: "560KVA", "250KVA")
                        # Regex tìm số theo sau là "kva" (không phân biệt hoa thường)
                        power_match = re.search(r"(\d+)\s*kva", user_msg_lower)
                        if power_match:
                            try:
                                power_capacity = int(power_match.group(1)) # Chuyển đổi công suất sang số nguyên
                            except ValueError:
                                st.warning("⚠️ Công suất không hợp lệ. Vui lòng nhập một số nguyên.")
                                power_capacity = None

                        filtered_df_tba = df_tba.copy() # Bắt đầu với bản sao của toàn bộ DataFrame

                        # Lọc theo tên đường dây nếu có
                        if line_name and 'Tên đường dây' in filtered_df_tba.columns:
                            filtered_df_tba = filtered_df_tba[filtered_df_tba['Tên đường dây'].astype(str).str.upper() == line_name]
                            if filtered_df_tba.empty:
                                st.warning(f"⚠️ Không tìm thấy TBA nào cho đường dây '{line_name}'.")
                                # Nếu không tìm thấy theo đường dây, dừng lại và không lọc thêm
                                filtered_df_tba = pd.DataFrame() # Đảm bảo nó rỗng để không hiển thị toàn bộ
                        
                        # Lọc theo công suất nếu có và cột 'Công suất' tồn tại
                        if power_capacity is not None and 'Công suất' in filtered_df_tba.columns and not filtered_df_tba.empty:
                            # Clean the 'Công suất' column by removing "KVA" and then convert to numeric
                            # Áp dụng regex để trích xuất chỉ phần số trước khi chuyển đổi
                            # Sử dụng .loc để tránh SettingWithCopyWarning
                            filtered_df_tba.loc[:, 'Công suất_numeric'] = pd.to_numeric(
                                filtered_df_tba['Công suất'].astype(str).str.extract(r'(\d+)')[0], # Lấy cột đầu tiên của DataFrame được trích xuất
                                errors='coerce' # Chuy đổi các giá trị không phải số thành NaN
                            )

                            # Loại bỏ các hàng có giá trị NaN trong cột 'Công suất_numeric'
                            filtered_df_tba = filtered_df_tba.dropna(subset=['Công suất_numeric'])

                            # Lọc các hàng có công suất khớp
                            filtered_df_tba = filtered_df_tba[filtered_df_tba['Công suất_numeric'] == power_capacity]

                            # Xóa cột tạm thời
                            filtered_df_tba = filtered_df_tba.drop(columns=['Công suất_numeric'])

                            if filtered_df_tba.empty:
                                st.warning(f"⚠️ Không tìm thấy TBA nào có công suất {power_capacity}KVA.")
                                # filtered_df_tba vẫn rỗng ở đây

                        if not filtered_df_tba.empty:
                            subheader_parts = ["Dữ liệu từ sheet 'Tên các TBA'"]
                            if line_name:
                                subheader_parts.append(f"cho đường dây {line_name}")
                            if power_capacity is not None:
                                subheader_parts.append(f"có công suất {power_capacity}KVA")

                            st.subheader(" ".join(subheader_parts) + ":")
                            st.dataframe(filtered_df_tba) # Hiển thị dữ liệu đã lọc

                            # Bạn có thể thêm logic vẽ biểu đồ cho TBA tại đây nếu cần
                            # Ví dụ: if "biểu đồ" in user_msg_lower: ...
                        else:
                            # Nếu filtered_df_tba rỗng sau tất cả các bước lọc
                            # Chỉ hiển thị toàn bộ danh sách nếu không có yêu cầu cụ thể nào được tìm thấy
                            if not (line_name or (power_capacity is not None)): # Nếu không có yêu cầu đường dây hoặc công suất
                                st.subheader("Toàn bộ thông tin TBA:")
                                st.dataframe(df_tba)
                            else:
                                st.warning("⚠️ Không tìm thấy dữ liệu phù hợp với yêu cầu của bạn.")
                    else:
                        st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet 'Tên các TBA'. Vui lòng kiểm tra tên sheet và quyền truy cập.")

                # Xử lý truy vấn liên quan đến doanh thu và biểu đồ
                elif "doanh thu" in user_msg_lower or "báo cáo tài chính" in user_msg_lower or "biểu đồ doanh thu" in user_msg_lower:
                    records = get_sheet_data("DoanhThu") # Tên sheet DoanhThu
                    if records:
                        df = pd.DataFrame(records)
                        if not df.empty:
                            st.subheader("Dữ liệu Doanh thu")
                            st.dataframe(df) # Hiển thị dữ liệu thô

                            # Thử vẽ biểu đồ nếu có các cột cần thiết (ví dụ: 'Tháng', 'Doanh thu')
                            # Bạn cần đảm bảo tên cột trong Google Sheet của bạn khớp với code
                            if 'Tháng' in df.columns and 'Doanh thu' in df.columns:
                                try:
                                    # Chuyển đổi cột 'Doanh thu' sang dạng số
                                    df['Doanh thu'] = pd.to_numeric(df['Doanh thu'], errors='coerce')
                                    df = df.dropna(subset=['Doanh thu']) # Loại bỏ các hàng có giá trị NaN sau chuyển đổi

                                    st.subheader("Biểu đồ Doanh thu theo tháng")
                                    fig, ax = plt.subplots(figsize=(12, 7))

                                    # Tạo danh sách màu sắc duy nhất cho mỗi tháng
                                    colors = cm.get_cmap('viridis', len(df['Tháng'].unique()))

                                    bars = ax.bar(df['Tháng'], df['Doanh thu'], color=colors.colors)

                                    # Hiển thị giá trị trên đỉnh mỗi cột với màu đen
                                    for bar in bars:
                                        yval = bar.get_height()
                                        ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, round(yval, 2), ha='center', va='bottom', color='black') # Màu chữ đen

                                    ax.set_xlabel("Tháng")
                                    ax.set_ylabel("Doanh thu (Đơn vị)") # Thay "Đơn vị" bằng đơn vị thực tế
                                    ax.set_title("Biểu đồ Doanh thu thực tế theo tháng")
                                    plt.xticks(rotation=45, ha='right')
                                    plt.tight_layout()
                                    st.pyplot(fig, dpi=400) # Tăng DPI để biểu đồ nét hơn
                                except Exception as e:
                                    st.error(f"❌ Lỗi khi vẽ biểu đồ doanh thu: {e}. Vui lòng kiểm tra định dạng dữ liệu trong sheet.")
                            else:
                                st.warning("⚠️ Không tìm thấy các cột 'Tháng' hoặc 'Doanh thu' trong sheet DoanhThu để vẽ biểu đồ.")
                        else:
                            st.warning("⚠️ Dữ liệu doanh thu rỗng, không thể hiển thị hoặc vẽ biểu đồ.")
                    else:
                        st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet DoanhThu. Vui lòng kiểm tra tên sheet và quyền truy cập.")

                # Xử lý truy vấn liên quan đến nhân sự (sheet CBCNV)
                elif "cbcnv" in user_msg_lower or "danh sách" in user_msg_lower or any(k in user_msg_lower for k in ["tổ", "phòng", "đội", "nhân viên", "nhân sự", "thông tin", "độ tuổi", "trình độ chuyên môn", "giới tính"]):
                    records = get_sheet_data("CBCNV") # Tên sheet CBCNV
                    if records:
                        df_cbcnv = pd.DataFrame(records) # Chuyển đổi thành DataFrame

                        person_name = None
                        bo_phan = None
                        is_specific_query = False # Flag để kiểm tra nếu có yêu cầu tìm kiếm cụ thể

                        # Regex để bắt tên người sau "thông tin" hoặc "của" (tham lam)
                        name_match = re.search(r"(?:thông tin|của)\s+([a-zA-Z\s]+)", user_msg_lower)
                        if name_match:
                            person_name = name_match.group(1).strip()
                            # Loại bỏ các từ khóa có thể bị bắt nhầm vào tên
                            known_keywords = ["trong", "tổ", "phòng", "đội", "cbcnv", "tất cả", "độ tuổi", "trình độ chuyên môn", "giới tính"] # Thêm các từ khóa mới
                            for kw in known_keywords:
                                if kw in person_name:
                                    person_name = person_name.split(kw, 1)[0].strip()
                                    break
                            is_specific_query = True

                        # Logic lọc theo bộ phận
                        for keyword in ["tổ ", "phòng ", "đội "]:
                            if keyword in user_msg_lower:
                                parts = user_msg_lower.split(keyword, 1)
                                if len(parts) > 1:
                                    remaining_msg = parts[1].strip()
                                    bo_phan_candidate = remaining_msg.split(' ')[0].strip()
                                    if "quản lý vận hành" in remaining_msg:
                                        bo_phan = "quản lý vận hành"
                                    elif "kinh doanh" in remaining_msg:
                                        bo_phan = "kinh doanh"
                                    else:
                                        bo_phan = bo_phan_candidate
                                    is_specific_query = True # Có yêu cầu bộ phận là yêu cầu cụ thể
                                break

                        df_to_process = df_cbcnv.copy() # Bắt đầu với bản sao của toàn bộ DataFrame

                        if person_name and 'Họ và tên' in df_to_process.columns:
                            temp_filtered_by_name = df_to_process[df_to_process['Họ và tên'].astype(str).str.lower() == person_name.lower()]
                            if temp_filtered_by_name.empty:
                                st.info(f"Không tìm thấy chính xác '{person_name.title()}'. Đang tìm kiếm gần đúng...")
                                temp_filtered_by_name = df_to_process[df_to_process['Họ và tên'].astype(str).str.lower().str.contains(person_name.lower(), na=False)]
                                if temp_filtered_by_name.empty:
                                    st.warning(f"⚠️ Không tìm thấy người nào có tên '{person_name.title()}' hoặc tên gần giống.")
                                    df_to_process = pd.DataFrame() # Set to empty if no name found
                                else:
                                    df_to_process = temp_filtered_by_name
                            else:
                                df_to_process = temp_filtered_by_name

                        if bo_phan and 'Bộ phận công tác' in df_to_process.columns and not df_to_process.empty: # Apply department filter only if df_to_process is not already empty
                            initial_filtered_count = len(df_to_process)
                            df_to_process = df_to_process[df_to_process['Bộ phận công tác'].str.lower().str.contains(bo_phan.lower(), na=False)]
                            if df_to_process.empty and initial_filtered_count > 0:
                                st.warning(f"⚠️ Không tìm thấy kết quả cho bộ phận '{bo_phan.title()}' trong danh sách đã lọc theo tên.")
                        elif bo_phan and 'Bộ phận công tác' in df_cbcnv.columns and not person_name: # Only filter by bo_phan if no person_name was specified
                            df_to_process = df_cbcnv[df_cbcnv['Bộ phận công tác'].str.lower().str.contains(bo_phan.lower(), na=False)]
                            if df_to_process.empty:
                                st.warning(f"⚠️ Không tìm thấy dữ liệu cho bộ phận '{bo_phan.title()}'.")


                        # Determine which DataFrame to display and chart
                        df_to_show = df_to_process
                        if df_to_show.empty and not is_specific_query: # Nếu không có truy vấn cụ thể (tên hoặc bộ phận) và df rỗng, hiển thị toàn bộ
                            df_to_show = df_cbcnv
                            st.subheader("Toàn bộ thông tin CBCNV:")
                        elif not df_to_show.empty: # Nếu df_to_show có dữ liệu, hiển thị nó (đã lọc hoặc toàn bộ nếu không có truy vấn cụ thể)
                            subheader_parts = ["Thông tin CBCNV"]
                            if person_name:
                                subheader_parts.append(f"của {person_name.title()}")
                            if bo_phan:
                                subheader_parts.append(f"thuộc {bo_phan.title()}")
                            st.subheader(" ".join(subheader_parts) + ":")
                        else: # df_to_show rỗng VÀ đó là một truy vấn cụ thể (is_specific_query là True)
                            st.warning("⚠️ Không tìm thấy dữ liệu phù hợp với yêu cầu của bạn.")

                        if not df_to_show.empty:
                            reply_list = []
                            for idx, r in df_to_show.iterrows():
                                reply_list.append(
                                    f"Họ và tên: {r.get('Họ và tên', 'N/A')}\n"
                                    f"Ngày sinh: {r.get('Ngày sinh CBCNV', 'N/A')}\n"
                                    f"Trình độ chuyên môn: {r.get('Trình độ chuyên môn', 'N/A')}\n"
                                    f"Tháng năm vào ngành: {r.get('Tháng năm vào ngành', 'N/A')}\n"
                                    f"Bộ phận công tác: {r.get('Bộ phận công tác', 'N/A')}\n"
                                    f"Chức danh: {r.get('Chức danh', 'N/A')}\n"
                                    f"---"
                                )
                            st.text_area("Kết quả", value="\n".join(reply_list), height=300)
                            st.dataframe(df_to_show) # Also display as dataframe for clarity

                        # --- Bổ sung logic vẽ biểu đồ CBCNV ---
                        if ("biểu đồ" in user_msg_lower or "báo cáo" in user_msg_lower) and not df_to_show.empty:
                            if 'Bộ phận công tác' in df_to_show.columns and not df_to_show['Bộ phận công tác'].empty:
                                st.subheader("Biểu đồ số lượng nhân viên theo Bộ phận công tác")
                                # Đảm bảo cột là chuỗi và điền giá trị rỗng cho NaN trước khi value_counts()
                                bo_phan_counts = df_to_show['Bộ phận công tác'].astype(str).fillna('Không xác định').value_counts()

                                # Biểu đồ cột mặc định
                                if "biểu đồ tròn bộ phận công tác" not in user_msg_lower:
                                    fig, ax = plt.subplots(figsize=(12, 7))

                                    colors = cm.get_cmap('tab10', len(bo_phan_counts.index))

                                    bars = ax.bar(bo_phan_counts.index, bo_phan_counts.values, color=colors.colors)

                                    # Thêm số liệu trên các cột biểu đồ
                                    for bar in bars:
                                        yval = bar.get_height()
                                        ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, round(yval), ha='center', va='bottom', color='black')

                                    ax.set_xlabel("Bộ phận công tác")
                                    ax.set_ylabel("Số lượng nhân viên")
                                    ax.set_title("Biểu đồ số lượng CBCNV theo Bộ phận")
                                    plt.xticks(rotation=45, ha='right')
                                    plt.tight_layout()
                                    st.pyplot(fig, dpi=400)
                                else: # Biểu đồ tròn nếu được yêu cầu
                                    st.subheader("Biểu đồ hình tròn số lượng nhân viên theo Bộ phận công tác")
                                    fig, ax = plt.subplots(figsize=(8, 8))
                                    colors = cm.get_cmap('tab10', len(bo_phan_counts.index))

                                    wedges, texts, autotexts = ax.pie(bo_phan_counts.values, 
                                                                        labels=bo_phan_counts.index, 
                                                                        autopct='%1.1f%%', 
                                                                        startangle=90, 
                                                                        colors=colors.colors,
                                                                        pctdistance=0.85)
                                    for autotext in autotexts:
                                        autotext.set_color('black')
                                        autotext.set_fontsize(10)
                                    ax.axis('equal')
                                    ax.set_title("Biểu đồ hình tròn số lượng CBCNV theo Bộ phận")
                                    plt.tight_layout()
                                    st.pyplot(fig, dpi=400)

                            else:
                                st.warning("⚠️ Không tìm thấy cột 'Bộ phận công tác' hoặc dữ liệu rỗng để vẽ biểu đồ nhân sự.")
                            
                            # 1. Vẽ biểu đồ theo độ tuổi (cột Q: 'Ngày sinh CBCNV')
                            if "độ tuổi" in user_msg_lower and 'Ngày sinh CBCNV' in df_to_show.columns:
                                st.subheader("Biểu đồ số lượng nhân viên theo độ tuổi")
                                
                                # Lấy năm hiện tại
                                current_year = datetime.datetime.now().year

                                # Hàm tính tuổi từ ngày sinh
                                def calculate_age(dob_str):
                                    try:
                                        # Cố gắng phân tích cú pháp ngày sinh theo nhiều định dạng
                                        for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%y'):
                                            try:
                                                dob = datetime.datetime.strptime(str(dob_str), fmt)
                                                return current_year - dob.year
                                            except ValueError:
                                                continue
                                        return None # Trả về None nếu không khớp định dạng nào
                                    except TypeError: # Xử lý trường hợp dob_str không phải là chuỗi
                                        return None

                                df_to_show['Tuổi'] = df_to_show['Ngày sinh CBCNV'].apply(calculate_age)
                                df_to_show = df_to_show.dropna(subset=['Tuổi']) # Loại bỏ các hàng không tính được tuổi

                                # Phân loại độ tuổi
                                age_bins = [0, 30, 40, 50, 100] # Giới hạn trên của mỗi nhóm
                                age_labels = ['<30 tuổi', '30 đến <40 tuổi', '40 đến <50 tuổi', '>50 tuổi']
                                
                                # Sử dụng pd.cut để phân loại và bao gồm cả biên phải (right=False) cho nhóm đầu tiên
                                # và right=True cho các nhóm còn lại để khớp với yêu cầu "<30 tuổi" và "từ 30 đến <40 tuổi"
                                df_to_show['Nhóm tuổi'] = pd.cut(df_to_show['Tuổi'], 
                                                                 bins=age_bins, 
                                                                 labels=age_labels, 
                                                                 right=False, # Bao gồm biên trái
                                                                 include_lowest=True) # Bao gồm giá trị thấp nhất

                                # Đếm số lượng theo nhóm tuổi
                                age_counts = df_to_show['Nhóm tuổi'].value_counts().reindex(age_labels, fill_value=0) # Đảm bảo thứ tự và điền 0 cho nhóm không có

                                fig, ax = plt.subplots(figsize=(12, 7))
                                colors = cm.get_cmap('viridis', len(age_counts.index))
                                bars = ax.bar(age_counts.index, age_counts.values, color=colors.colors)

                                for bar in bars:
                                    yval = bar.get_height()
                                    ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, round(yval), ha='center', va='bottom', color='black')

                                ax.set_xlabel("Nhóm tuổi")
                                ax.set_ylabel("Số lượng nhân viên")
                                ax.set_title("Biểu đồ số lượng CBCNV theo Nhóm tuổi")
                                plt.xticks(rotation=45, ha='right')
                                plt.tight_layout()
                                st.pyplot(fig, dpi=400)
                            elif "độ tuổi" in user_msg_lower:
                                st.warning("⚠️ Không tìm thấy cột 'Ngày sinh CBCNV' hoặc dữ liệu rỗng để vẽ biểu đồ độ tuổi.")

                            # 2. Vẽ biểu đồ theo trình độ chuyên môn (cột I: 'Trình độ chuyên môn')
                            if "trình độ chuyên môn" in user_msg_lower and 'Trình độ chuyên môn' in df_to_show.columns:
                                st.subheader("Biểu đồ số lượng nhân viên theo Trình độ chuyên môn")
                                # Đảm bảo cột là chuỗi và điền giá trị rỗng cho NaN trước khi value_counts()
                                trinh_do_counts = df_to_show['Trình độ chuyên môn'].astype(str).fillna('Không xác định').value_counts()

                                fig, ax = plt.subplots(figsize=(12, 7))
                                colors = cm.get_cmap('plasma', len(trinh_do_counts.index))
                                bars = ax.bar(trinh_do_counts.index, trinh_do_counts.values, color=colors.colors)

                                for bar in bars:
                                    yval = bar.get_height()
                                    ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, round(yval), ha='center', va='bottom', color='black')

                                ax.set_xlabel("Trình độ chuyên môn")
                                ax.set_ylabel("Số lượng nhân viên")
                                ax.set_title("Biểu đồ số lượng CBCNV theo Trình độ chuyên môn")
                                plt.xticks(rotation=45, ha='right')
                                plt.tight_layout()
                                st.pyplot(fig, dpi=400)
                            elif "trình độ chuyên môn" in user_msg_lower:
                                st.warning("⚠️ Không tìm thấy cột 'Trình độ chuyên môn' hoặc dữ liệu rỗng để vẽ biểu đồ trình độ chuyên môn.")

                            # 3. Vẽ biểu đồ theo Giới tính (cột D: 'Giới tính')
                            if "giới tính" in user_msg_lower and 'Giới tính' in df_to_show.columns:
                                st.subheader("Biểu đồ số lượng nhân viên theo Giới tính")
                                # Đảm bảo cột là chuỗi và điền giá trị rỗng cho NaN trước khi value_counts()
                                gioi_tinh_counts = df_to_show['Giới tính'].astype(str).fillna('Không xác định').value_counts()

                                fig, ax = plt.subplots(figsize=(8, 8)) # Hình tròn thường đẹp hơn với tỷ lệ 1:1
                                colors = ['#66b3ff', '#ff9999', '#99ff99', '#ffcc99'] # Màu sắc tùy chỉnh

                                wedges, texts, autotexts = ax.pie(gioi_tinh_counts.values, 
                                                                    labels=gioi_tinh_counts.index, 
                                                                    autopct='%1.1f%%', 
                                                                    startangle=90, 
                                                                    colors=colors[:len(gioi_tinh_counts)], # Sử dụng đủ màu cho số lượng phần tử
                                                                    pctdistance=0.85) # Khoảng cách của phần trăm từ tâm

                                # Đảm bảo phần trăm được hiển thị rõ ràng
                                for autotext in autotexts:
                                    autotext.set_color('black')
                                    autotext.set_fontsize(10)

                                ax.axis('equal') # Đảm bảo biểu đồ hình tròn là hình tròn
                                ax.set_title("Biểu đồ số lượng CBCNV theo Giới tính")
                                plt.tight_layout()
                                st.pyplot(fig, dpi=400)
                            elif "giới tính" in user_msg_lower:
                                st.warning("⚠️ Không tìm thấy cột 'Giới tính' hoặc dữ liệu rỗng để vẽ biểu đồ giới tính.")

                        elif ("biểu đồ" in user_msg_lower or "báo cáo" in user_msg_lower) and df_to_show.empty:
                            st.warning("⚠️ Không có dữ liệu để vẽ biểu đồ.")

                    else:
                        st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet CBCNV.")

                # Xử lý các câu hỏi chung bằng OpenAI
                else:
                    if client_ai:
                        try:
                            response = client_ai.chat.completions.create(
                                model="gpt-3.5-turbo",
                                messages=[
                                    {"role": "system", "content": "Bạn là trợ lý ảo của Đội QLĐLKV Định Hóa, chuyên hỗ trợ trả lời các câu hỏi kỹ thuật, nghiệp vụ, đoàn thể và cộng đồng liên quan đến ngành điện. Luôn cung cấp thông tin chính xác và hữu ích."},
                                    {"role": "user", "content": user_msg}
                                ]
                            )
                            st.session_state.current_qa_display = response.choices[0].message.content # Display AI response here
                        except Exception as e:
                            st.error(f"❌ Lỗi khi gọi OpenAI: {e}. Vui lòng kiểm tra API key hoặc quyền truy cập mô hình.")
                    else:
                        st.warning("Không có API key OpenAI. Vui lòng thêm vào st.secrets để sử dụng chatbot cho các câu hỏi tổng quát.")

    # Always display the current QA answer if available
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
    with open(temp_image_path, "wb") as f:
        f.write(uploaded_image.getbuffer())

    extracted_text = extract_text_from_image(str(temp_image_path))
    st.success("✅ Đã quét được nội dung từ ảnh:")
    st.write(extracted_text)

    st.session_state.user_input_value = extracted_text
    st.rerun()
