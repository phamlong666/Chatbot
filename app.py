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
from audio_recorder_streamlit import audio_recorder

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

# ======================== KẾT NỐI GOOGLE SHEET ========================
SERVICE_ACCOUNT_FILE = "service_account.json"

@st.cache_resource
def get_gspread_client():
    """Kết nối tới Google Sheets API bằng service_account.json."""
    try:
        if not Path(SERVICE_ACCOUNT_FILE).exists():
            st.error(f"❌ Lỗi: Không tìm thấy file {SERVICE_ACCOUNT_FILE}. Vui lòng tải lên file này.")
            st.stop()
        
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Lỗi kết nối Google Sheets: {e}. Vui lòng kiểm tra file '{SERVICE_ACCOUNT_FILE}' và quyền truy cập.")
        st.stop()

@st.cache_data(ttl=3600) # Cache dữ liệu trong 1 giờ để tăng tốc độ
def get_sheet_data(sheet_name):
    """Lấy dữ liệu từ một sheet cụ thể trong Google Spreadsheet."""
    client = get_gspread_client()
    spreadsheet_url = "https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit?usp=sharing"
    try:
        sheet = client.open_by_url(spreadsheet_url).worksheet(sheet_name)
        
        if sheet_name == "KPI":
            all_values = sheet.get_all_values()
            if all_values:
                # Đảm bảo tiêu đề là duy nhất trước khi tạo DataFrame
                headers = all_values[0]
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
                return df_temp.to_dict('records') # Trả về dưới dạng list of dictionaries
            else:
                return [] # Trả về list rỗng nếu không có dữ liệu
        else:
            return sheet.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Không tìm thấy sheet '{sheet_name}'. Vui lòng kiểm tra tên sheet.")
        return None
    except Exception as e:
        st.error(f"❌ Lỗi khi mở Google Sheet '{sheet_name}': {e}. Vui lòng kiểm tra định dạng tiêu đề của sheet. Nếu có tiêu đề trùng lặp, hãy đảm bảo chúng là duy nhất.")
        return None

# Tải dữ liệu từ sheet "Hỏi-Trả lời" một lần khi ứng dụng khởi động
qa_df = pd.DataFrame(get_sheet_data("Hỏi-Trả lời")) if get_sheet_data("Hỏi-Trả lời") else pd.DataFrame()

def normalize_text(text):
    """Chuẩn hóa chuỗi để so sánh chính xác hơn (loại bỏ dấu cách thừa, chuyển về chữ thường)."""
    if isinstance(text, str):
        return re.sub(r'\s+', ' ', text).strip().lower()
    return ""

def find_answer_from_sheet(question_text):
    """Tìm câu trả lời trong sheet 'Hỏi-Trả lời' dựa trên câu hỏi."""
    global qa_df # Đảm bảo qa_df được truy cập toàn cục
    all_matches = []
    
    # Kiểm tra khớp chính xác 100% cho cú pháp "An toàn:..."
    if question_text.lower().startswith("an toàn:"):
        specific_question = normalize_text(question_text.replace("an toàn:", "").strip())
        if not qa_df.empty and 'Câu hỏi' in qa_df.columns and 'Câu trả lời' in qa_df.columns:
            for _, row in qa_df.iterrows():
                question_from_sheet_normalized = normalize_text(str(row['Câu hỏi']))
                if specific_question == question_from_sheet_normalized:
                    all_matches.append(str(row['Câu trả lời']))
            if all_matches:
                return all_matches # Trả về các câu trả lời khớp chính xác nếu tìm thấy
            else:
                return ["⚠️ Không tìm thấy câu trả lời chính xác 100% cho yêu cầu 'An toàn:' của bạn. Vui lòng đảm bảo câu hỏi khớp hoàn toàn (có thể bỏ qua dấu cách thừa)."]

    # Đối với các câu hỏi chung, sử dụng so khớp mờ (fuzzy matching)
    if not qa_df.empty and 'Câu hỏi' in qa_df.columns and 'Câu trả lời' in qa_df.columns:
        for _, row in qa_df.iterrows():
            score = fuzz.ratio(str(row['Câu hỏi']).lower(), question_text.lower())
            if score >= 60: # Ngưỡng điểm tương đồng
                all_matches.append({'answer': str(row['Câu trả lời']), 'score': score})
    
    # Sắp xếp các kết quả theo điểm số giảm dần
    all_matches.sort(key=lambda x: x['score'], reverse=True)
    
    if all_matches:
        return [match['answer'] for match in all_matches]
    else:
        return [] # Trả về list rỗng nếu không tìm thấy kết quả nào phù hợp

# Lấy API key OpenAI
openai_api_key = None
if "openai_api_key" in st.secrets:
    openai_api_key = st.secrets["openai_api_key"]
    # st.success("✅ Đã kết nối OpenAI API key từ Streamlit secrets.") # Bỏ comment nếu muốn hiển thị
else:
    pass # Không hiển thị cảnh báo nếu không có API key, chỉ khi cố gắng gọi API

if openai_api_key:
    client_ai = OpenAI(api_key=openai_api_key)
else:
    client_ai = None

# Hàm để đọc câu hỏi mẫu từ file JSON
def load_sample_questions(file_path="sample_questions.json"):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            questions_data = json.load(f)
        if isinstance(questions_data, list) and all(isinstance(q, str) for q in questions_data):
            return questions_data
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

# Tải các câu hỏi mẫu khi ứng dụng khởi động
sample_questions_from_file = load_sample_questions()

# --- Bắt đầu bố cục mới: Logo ở trái, phần còn lại của chatbot căn giữa ---

# Phần header: Logo và tiêu đề, được đặt ở đầu trang và logo căn trái
header_col1, header_col2 = st.columns([1, 8])

with header_col1:
    public_logo_url = "https://raw.githubusercontent.com/phamlong666/Chatbot/main/logo_hinh_tron.png"
    try:
        st.image(public_logo_url, width=100)
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
    st.markdown("<h1 style='font-size: 30px;'>🤖 Chatbot Đội QLĐLKV Định Hóa</h1>", unsafe_allow_html=True)

# Phần nội dung chính của chatbot (ô nhập liệu, nút, kết quả) sẽ được căn giữa
col_left_spacer, col_main_content, col_right_spacer = st.columns([1, 5, 1])

with col_main_content: # Tất cả nội dung chatbot sẽ nằm trong cột này
    # Khởi tạo session state
    if 'last_processed_user_msg' not in st.session_state:
        st.session_state.last_processed_user_msg = ""
    if 'qa_results' not in st.session_state:
        st.session_state.qa_results = []
    if 'qa_index' not in st.session_state:
        st.session_state.qa_index = 0
    if 'user_input_value' not in st.session_state:
        st.session_state.user_input_value = ""
    if 'current_qa_display' not in st.session_state:
        st.session_state.current_qa_display = ""
    if 'text_input_key' not in st.session_state: # Đảm bảo key này tồn tại
        st.session_state.text_input_key = ""

    # ======================== GIAO DIỆN NHẬP LIỆU (FORM) ========================
    with st.form(key='chat_buttons_form'):
        mic_col, send_button_col, clear_button_col = st.columns([9, 1, 1])

        with mic_col:
            # Ô nhập liệu chính
            user_msg_input_in_form = st.text_input(
                "Nhập lệnh hoặc dùng micro để nói:",
                value=st.session_state.get("user_input_value", ""),
                key="text_input_key"
            )

            # Ghi âm giọng nói
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
                            st.session_state.user_input_value = text # Cập nhật session state để hiển thị trong text_input
                            st.rerun() # Rerun để cập nhật ô nhập liệu ngay lập tức
                        except sr.UnknownValueError:
                            st.warning("⚠️ Không nhận dạng được giọng nói. Vui lòng thử lại rõ ràng hơn.")
                        except sr.RequestError as e:
                            st.error(f"❌ Lỗi kết nối dịch vụ nhận dạng: {e}. Vui lòng kiểm tra kết nối internet.")
                except Exception as e:
                    st.error(f"❌ Lỗi khi xử lý file âm thanh: {e}")
                finally:
                    if audio_path and os.path.exists(audio_path):
                        os.remove(audio_path)

        with send_button_col:
            send_button_pressed = st.form_submit_button("Gửi")

        with clear_button_col:
            clear_button_pressed = st.form_submit_button("Xóa")

    # Giao diện chọn câu hỏi mẫu
    selected_sample_question = st.selectbox(
        "📋 Hoặc chọn câu hỏi từ danh sách:",
        options=[""] + sample_questions_from_file, # Sử dụng biến đã tải từ file
        index=0,
        key="sample_question_selector"
    )

    # Logic để cập nhật user_input_value khi chọn câu hỏi mẫu
    if selected_sample_question and selected_sample_question != st.session_state.get("text_input_key", ""):
        st.session_state.user_input_value = selected_sample_question
        st.rerun()

    # Xác định câu hỏi cuối cùng để xử lý
    # Ưu tiên giá trị từ ô text_input_key (người dùng nhập hoặc từ micro)
    # Nếu không có, thì lấy từ selected_sample_question
    question_to_process = st.session_state.get("text_input_key", "")
    if not question_to_process:
        question_to_process = selected_sample_question

    if clear_button_pressed:
        st.session_state.user_input_value = ""
        st.session_state.text_input_key = "" # Xóa nội dung trong ô nhập liệu
        st.session_state.qa_results = []
        st.session_state.qa_index = 0
        st.session_state.last_processed_user_msg = ""
        st.session_state.current_qa_display = ""
        st.rerun()

    # Logic xử lý câu hỏi chính chỉ chạy khi nút "Gửi" được nhấn và có câu hỏi
    if send_button_pressed and question_to_process:
        st.info(f"📨 Đang xử lý câu hỏi: {question_to_process}")
        st.session_state.last_processed_user_msg = question_to_process
        st.session_state.user_input_value = "" # Xóa giá trị ẩn sau khi gửi
        st.session_state.text_input_key = "" # Xóa nội dung trong ô nhập liệu sau khi gửi

        # Reset QA results and display for a new query
        st.session_state.qa_results = []
        st.session_state.qa_index = 0
        st.session_state.current_qa_display = ""

        user_msg_lower = question_to_process.lower()

        # --- Ưu tiên tìm kiếm câu trả lời trong sheet "Hỏi-Trả lời" ---
        qa_answers = find_answer_from_sheet(question_to_process)

        if qa_answers and not (len(qa_answers) == 1 and qa_answers[0].startswith("⚠️ Không tìm thấy")):
            st.session_state.qa_results = qa_answers
            st.session_state.qa_index = 0
            st.session_state.current_qa_display = st.session_state.qa_results[st.session_state.qa_index]
            if len(st.session_state.qa_results) > 1:
                st.session_state.qa_index += 1 # Chuyển sang kết quả tiếp theo cho nút "Tìm tiếp"
        else:
            # Nếu không tìm thấy câu trả lời trong QA sheet hoặc là thông báo lỗi từ QA sheet,
            # thì tiếp tục xử lý các truy vấn khác
            if qa_answers and qa_answers[0].startswith("⚠️ Không tìm thấy"):
                st.warning(qa_answers[0]) # Hiển thị cảnh báo từ find_answer_from_sheet
            
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
                        df_kpi['Năm'] = df_kpi['Năm'].astype(str).str.extract(r'(\d{4})')[0]
                        df_kpi['Năm'] = pd.to_numeric(df_kpi['Năm'], errors='coerce').dropna().astype(int)
                    else:
                        st.warning("⚠️ Không tìm thấy cột 'Năm' trong sheet 'KPI'. Một số chức năng KPI có thể không hoạt động.")
                        df_kpi = pd.DataFrame()

                    if 'Tháng' in df_kpi.columns:
                        df_kpi['Tháng'] = pd.to_numeric(df_kpi['Tháng'], errors='coerce').dropna().astype(int)
                    else:
                        st.warning("⚠️ Không tìm thấy cột 'Tháng' trong sheet 'KPI'. Một số chức năng KPI có thể không hoạt động.")
                        df_kpi = pd.DataFrame()

                    kpi_value_column = 'Điểm KPI' # Cột giá trị KPI cố định

                    if not df_kpi.empty:
                        st.subheader("Dữ liệu KPI")
                        st.dataframe(df_kpi)

                        target_year_kpi = None
                        kpi_year_match = re.search(r"năm\s+(\d{4})", user_msg_lower)
                        if kpi_year_match:
                            target_year_kpi = kpi_year_match.group(1)

                        unit_name_from_query = None
                        unit_column_mapping = {
                            "định hóa": "Định Hóa", "đồng hỷ": "Đồng Hỷ", "đại từ": "Đại Từ",
                            "phú bình": "Phú Bình", "phú lương": "Phú Lương", "phổ yên": "Phổ Yên",
                            "sông công": "Sông Công", "thái nguyên": "Thái Nguyên", "võ nhai": "Võ Nhai"
                        }
                        
                        for unit_key, unit_col_name in unit_column_mapping.items():
                            if unit_key in user_msg_lower:
                                unit_name_from_query = unit_key
                                break

                        if target_year_kpi and "so sánh" in user_msg_lower:
                            st.subheader(f"Biểu đồ KPI theo tháng cho năm {target_year_kpi} và các năm trước")

                            can_plot_line_chart = True

                            if unit_name_from_query:
                                selected_unit = unit_column_mapping.get(unit_name_from_query)
                                if selected_unit:
                                    df_to_plot_line = df_kpi[df_kpi['Đơn vị'].astype(str).str.lower() == selected_unit.lower()].copy()
                                    
                                    if df_to_plot_line.empty:
                                        st.warning(f"⚠️ Không tìm thấy dữ liệu cho đơn vị '{selected_unit}' trong sheet 'KPI'.")
                                        can_plot_line_chart = False
                                else:
                                    st.warning(f"⚠️ Không tìm thấy tên đơn vị hợp lệ trong câu hỏi của bạn.")
                                    can_plot_line_chart = False
                            else:
                                st.warning("⚠️ Vui lòng chỉ định đơn vị cụ thể (ví dụ: 'Định Hóa') để vẽ biểu đồ KPI so sánh năm.")
                                can_plot_line_chart = False

                            if can_plot_line_chart and target_year_kpi and 'Năm' in df_to_plot_line.columns and 'Tháng' in df_to_plot_line.columns and kpi_value_column in df_to_plot_line.columns:
                                try:
                                    df_to_plot_line.loc[:, kpi_value_column] = df_to_plot_line[kpi_value_column].astype(str).str.replace(',', '.', regex=False)
                                    df_to_plot_line.loc[:, kpi_value_column] = pd.to_numeric(df_to_plot_line[kpi_value_column], errors='coerce')
                                    df_to_plot_line = df_to_plot_line.dropna(subset=[kpi_value_column])

                                    fig, ax = plt.subplots(figsize=(14, 8))
                                    
                                    years_to_compare = [int(target_year_kpi)]
                                    other_years_in_data = [y for y in df_to_plot_line['Năm'].unique() if y != int(target_year_kpi)]
                                    years_to_compare.extend(sorted(other_years_in_data, reverse=True))

                                    colors = cm.get_cmap('tab10', len(years_to_compare))

                                    for i, year in enumerate(years_to_compare):
                                        df_year = df_to_plot_line[df_to_plot_line['Năm'] == year].sort_values(by='Tháng')
                                        
                                        if str(year) == target_year_kpi:
                                            last_valid_month = df_year[df_year[kpi_value_column].notna()]['Tháng'].max()
                                            if last_valid_month is not None:
                                                df_year_filtered = df_year[df_year['Tháng'] <= last_valid_month]
                                            else:
                                                df_year_filtered = df_year
                                            
                                            ax.plot(df_year_filtered['Tháng'], df_year_filtered[kpi_value_column], 
                                                    marker='o', label=f'Năm {year}', color=colors(i), linestyle='-')
                                            for x, y in zip(df_year_filtered['Tháng'], df_year_filtered[kpi_value_column]):
                                                if pd.notna(y):
                                                    ax.text(x, y + (ax.get_ylim()[1] * 0.01), f'{y:.1f}', ha='center', va='bottom', fontsize=8, color=colors(i))
                                        else:
                                            ax.plot(df_year['Tháng'], df_year[kpi_value_column], 
                                                    marker='x', linestyle='-', label=f'Năm {year}', color=colors(i), alpha=0.7)
                                            for x, y in zip(df_year['Tháng'], df_year[kpi_value_column]):
                                                if pd.notna(y):
                                                    ax.text(x, y + (ax.get_ylim()[1] * 0.01), f'{y:.1f}', ha='center', va='bottom', fontsize=8, color=colors(i), alpha=0.7)

                                    ax.set_xlabel("Tháng")
                                    ax.set_ylabel("Giá trị KPI")
                                    chart_title_suffix = f"của {selected_unit}" if selected_unit else ""
                                    ax.set_title(f"So sánh KPI theo tháng {chart_title_suffix} (Năm {target_year_kpi} vs các năm khác)")
                                    ax.set_xticks(range(1, 13))
                                    ax.legend()
                                    plt.grid(True)
                                    plt.tight_layout()
                                    st.pyplot(fig, dpi=400)

                                except Exception as e:
                                    st.error(f"❌ Lỗi khi vẽ biểu đồ KPI so sánh năm: {e}. Vui lòng kiểm tra định dạng dữ liệu trong sheet (cột 'Tháng', 'Năm', và '{kpi_value_column}').")
                            else:
                                if can_plot_line_chart:
                                    st.warning("⚠️ Không tìm thấy các cột cần thiết ('Tháng', 'Năm', hoặc cột giá trị KPI) trong dữ liệu đã lọc để vẽ biểu đồ so sánh.")

                        elif target_year_kpi and ("các đơn vị" in user_msg_lower or unit_name_from_query):
                            st.subheader(f"Biểu đồ KPI của các đơn vị năm {target_year_kpi}")

                            can_plot_bar_chart = True
                            
                            df_kpi_year = df_kpi[df_kpi['Năm'] == int(target_year_kpi)].copy()

                            target_month_kpi = None
                            month_match = re.search(r"tháng\s+(\d{1,2})", user_msg_lower)
                            if month_match:
                                target_month_kpi = int(month_match.group(1))

                            is_cumulative = "lũy kế" in user_msg_lower

                            if not df_kpi_year.empty:
                                df_kpi_year.loc[:, kpi_value_column] = df_kpi_year[kpi_value_column].astype(str).str.replace(',', '.', regex=False)
                                df_kpi_year.loc[:, kpi_value_column] = pd.to_numeric(df_kpi_year[kpi_value_column], errors='coerce')
                                df_kpi_year = df_kpi_year.dropna(subset=[kpi_value_column])

                                unit_kpis_aggregated = {}
                                
                                if unit_name_from_query:
                                    selected_unit = unit_column_mapping.get(unit_name_from_query)
                                    if selected_unit:
                                        unit_data = df_kpi_year[df_kpi_year['Đơn vị'].astype(str).str.lower() == selected_unit.lower()]
                                        
                                        if not unit_data.empty:
                                            if target_month_kpi:
                                                monthly_data = unit_data[unit_data['Tháng'] == target_month_kpi]
                                                if not monthly_data.empty:
                                                    unit_kpis_aggregated[selected_unit] = monthly_data[kpi_value_column].mean()
                                                else:
                                                    st.warning(f"⚠️ Không có dữ liệu KPI cho đơn vị '{selected_unit}' trong tháng {target_month_kpi} năm {target_year_kpi}.")
                                                    can_plot_bar_chart = False
                                            elif is_cumulative:
                                                current_month = datetime.datetime.now().month
                                                cumulative_data = unit_data[unit_data['Tháng'] <= current_month]
                                                if not cumulative_data.empty:
                                                    unit_kpis_aggregated[selected_unit] = cumulative_data[kpi_value_column].mean()
                                                else:
                                                    st.warning(f"⚠️ Không có dữ liệu KPI lũy kế cho đơn vị '{selected_unit}' đến tháng {current_month} năm {target_year_kpi}.")
                                                    can_plot_bar_chart = False
                                            else:
                                                unit_kpis_aggregated[selected_unit] = unit_data[kpi_value_column].mean()
                                        else:
                                            st.warning(f"⚠️ Không có dữ liệu KPI cho đơn vị '{selected_unit}' trong năm {target_year_kpi}.")
                                            can_plot_bar_chart = False
                                    else:
                                        st.warning(f"⚠️ Không tìm thấy tên đơn vị hợp lệ trong câu hỏi của bạn.")
                                        can_plot_bar_chart = False
                                else:
                                    if 'Đơn vị' in df_kpi_year.columns:
                                        if target_month_kpi:
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
                records = get_sheet_data("Quản lý sự cố")
                if records:
                    df_suco = pd.DataFrame(records)

                    target_year = None
                    target_month = None
                    compare_year = None

                    month_year_full_match = re.search(r"tháng\s+(\d{1,2})(?:/(\d{4}))?", user_msg_lower)
                    if month_year_full_match:
                        target_month = month_year_full_match.group(1)
                        target_year = month_year_full_match.group(2)

                    if not target_year:
                        year_only_match = re.search(r"năm\s+(\d{4})", user_msg_lower)
                        if year_only_match:
                            target_year = year_only_match.group(1)

                    compare_match = re.search(r"so sánh.*?(\d{4}).*?với.*?(\d{4})", user_msg_lower)
                    if compare_match:
                        target_year = compare_match.group(1)
                        compare_year = compare_match.group(2)
                        st.info(f"Đang so sánh sự cố năm {target_year} với năm {compare_year}.")
                    elif "cùng kỳ" in user_msg_lower:
                        cung_ky_year_match = re.search(r"cùng kỳ\s+(\d{4})", user_msg_lower)
                        if cung_ky_year_match:
                            compare_year = cung_ky_year_match.group(1)

                        if not target_year:
                            target_year = str(datetime.datetime.now().year)

                        if not compare_year:
                            try:
                                compare_year = str(int(target_year) - 1)
                            except (ValueError, TypeError):
                                st.warning("⚠️ Không thể xác định năm so sánh cho 'cùng kỳ'.")
                                compare_year = None

                        if target_year and compare_year:
                            st.info(f"Đang so sánh sự cố năm {target_year} với cùng kỳ năm {compare_year}.")
                        else:
                            st.warning("⚠️ Không đủ thông tin để thực hiện so sánh 'cùng kỳ'.")
                            compare_year = None

                    filtered_df_suco = df_suco

                    if 'Tháng/Năm sự cố' not in df_suco.columns:
                        st.warning("⚠️ Không tìm thấy cột 'Tháng/Năm sự cố' trong sheet 'Quản lý sự cố'. Không thể lọc theo tháng/năm.")
                        if target_month or target_year or compare_year:
                            st.info("Hiển thị toàn bộ dữ liệu sự cố (nếu có) do không tìm thấy cột lọc tháng/năm.")
                    else:
                        df_suco['Tháng/Năm sự cố'] = df_suco['Tháng/Năm sự cố'].astype(str).fillna('')

                        if target_year and not compare_year:
                            year_suffix = f"/{target_year}"
                            filtered_df_suco = df_suco[df_suco['Tháng/Năm sự cố'].str.endswith(year_suffix)]
                            if target_month:
                                exact_match_str = f"{int(target_month):02d}/{target_year}"
                                filtered_df_suco = filtered_df_suco[filtered_df_suco['Tháng/Năm sự cố'] == exact_match_str]
                        elif target_year and compare_year:
                            df_target_year = df_suco[df_suco['Tháng/Năm sự cố'].str.endswith(f"/{target_year}")].copy()
                            df_compare_year = df_suco[df_suco['Tháng/Năm sự cố'].str.endswith(f"/{compare_year}")].copy()

                            if target_month:
                                month_prefix = f"{int(target_month):02d}/"
                                df_target_year = df_target_year[df_target_year['Tháng/Năm sự cố'].str.startswith(month_prefix)]
                                df_compare_year = df_compare_year[df_compare_year['Tháng/Năm sự cố'].str.startswith(month_prefix)]

                            filtered_df_suco = pd.concat([df_target_year.assign(Năm=target_year),
                                                          df_compare_year.assign(Năm=compare_year)])
                        elif target_month and not target_year:
                            month_prefix = f"{int(target_month):02d}/"
                            filtered_df_suco = df_suco[df_suco['Tháng/Năm sự cố'].str.startswith(month_prefix)]

                    if filtered_df_suco.empty and (target_month or target_year or compare_year):
                        st.warning(f"⚠️ Không tìm thấy sự cố nào {'trong tháng ' + target_month if target_month else ''} {'năm ' + target_year if target_year else ''} {'hoặc năm ' + compare_year if compare_year else ''}.")

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
                        st.dataframe(filtered_df_suco)

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
                                    if col in filtered_df_suco.columns and not filtered_df_suco[col].empty:
                                        col_data = filtered_df_suco[col].astype(str).fillna('Không xác định')

                                        if compare_year and 'Năm' in filtered_df_suco.columns:
                                            st.subheader(f"Biểu đồ so sánh số lượng sự cố theo '{col}' giữa năm {target_year} và năm {compare_year}")

                                            counts_target = filtered_df_suco[filtered_df_suco['Năm'] == target_year][col].astype(str).fillna('Không xác định').value_counts().sort_index()
                                            counts_compare = filtered_df_suco[filtered_df_suco['Năm'] == compare_year][col].astype(str).fillna('Không xác định').value_counts().sort_index()

                                            combined_counts = pd.DataFrame({
                                                f'Năm {target_year}': counts_target,
                                                f'Năm {compare_year}': counts_compare
                                            }).fillna(0)

                                            fig, ax = plt.subplots(figsize=(14, 8))
                                            bars = combined_counts.plot(kind='bar', ax=ax, width=0.8, colormap='viridis')
                                            for container in ax.containers:
                                                ax.bar_label(container, fmt='%d', label_type='edge', fontsize=9, padding=3)

                                            ax.set_xlabel(col)
                                            ax.set_ylabel("Số lượng sự cố")
                                            ax.set_title(f"Biểu đồ so sánh số lượng sự cố theo {col} giữa năm {target_year} và năm {compare_year}")
                                            plt.xticks(rotation=45, ha='right')
                                            plt.tight_layout()
                                            st.pyplot(fig, dpi=400)

                                        else:
                                            st.subheader(f"Biểu đồ số lượng sự cố theo '{col}'")
                                            counts = col_data.value_counts()
                                            fig, ax = plt.subplots(figsize=(12, 7))
                                            colors = cm.get_cmap('tab10', len(counts.index))

                                            x_labels = [str(item) for item in counts.index]
                                            y_values = counts.values

                                            bars = ax.bar(x_labels, y_values, color=colors.colors)
                                            for bar in bars:
                                                yval = bar.get_height()
                                                ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, round(yval), ha='center', va='bottom', color='black')

                                            ax.set_xlabel("Bộ phận công tác" if col == 'Tính chất' else col)
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
                        st.warning("⚠️ Không tìm thấy dữ liệu phù hợp với yêu cầu của bạn.")
                else:
                    st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet 'Quản lý sự cố'. Vui lòng kiểm tra tên sheet và quyền truy cập.")

            # Xử lý truy vấn liên quan đến sheet "Danh sách lãnh đạo xã, phường" (Ưu tiên cao)
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
                        subheader_parts = ["Dữ liệu từ sheet 'Danh sách lãnh đạo xã, phường'"]
                        if location_name:
                            subheader_parts.append(f"cho {location_name.title()}")
                        st.subheader(" ".join(subheader_parts) + ":")
                        st.dataframe(filtered_df_lanhdao)
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
                    power_capacity = None

                    line_match = re.search(r"đường dây\s+([a-zA-Z0-9\.]+)", user_msg_lower)
                    if line_match:
                        line_name = line_match.group(1).upper()

                    power_match = re.search(r"(\d+)\s*kva", user_msg_lower)
                    if power_match:
                        try:
                            power_capacity = int(power_match.group(1))
                        except ValueError:
                            st.warning("⚠️ Công suất không hợp lệ. Vui lòng nhập một số nguyên.")
                            power_capacity = None

                    filtered_df_tba = df_tba.copy()

                    if line_name and 'Tên đường dây' in filtered_df_tba.columns:
                        filtered_df_tba = filtered_df_tba[filtered_df_tba['Tên đường dây'].astype(str).str.upper() == line_name]
                        if filtered_df_tba.empty:
                            st.warning(f"⚠️ Không tìm thấy TBA nào cho đường dây '{line_name}'.")
                            filtered_df_tba = pd.DataFrame()
                    
                    if power_capacity is not None and 'Công suất' in filtered_df_tba.columns and not filtered_df_tba.empty:
                        filtered_df_tba.loc[:, 'Công suất_numeric'] = pd.to_numeric(
                            filtered_df_tba['Công suất'].astype(str).str.extract(r'(\d+)')[0],
                            errors='coerce'
                        )
                        filtered_df_tba = filtered_df_tba.dropna(subset=['Công suất_numeric'])
                        filtered_df_tba = filtered_df_tba[filtered_df_tba['Công suất_numeric'] == power_capacity]
                        filtered_df_tba = filtered_df_tba.drop(columns=['Công suất_numeric'])

                        if filtered_df_tba.empty:
                            st.warning(f"⚠️ Không tìm thấy TBA nào có công suất {power_capacity}KVA.")

                    if not filtered_df_tba.empty:
                        subheader_parts = ["Dữ liệu từ sheet 'Tên các TBA'"]
                        if line_name:
                            subheader_parts.append(f"cho đường dây {line_name}")
                        if power_capacity is not None:
                            subheader_parts.append(f"có công suất {power_capacity}KVA")

                        st.subheader(" ".join(subheader_parts) + ":")
                        st.dataframe(filtered_df_tba)
                    else:
                        if not (line_name or (power_capacity is not None)):
                            st.subheader("Toàn bộ thông tin TBA:")
                            st.dataframe(df_tba)
                        else:
                            st.warning("⚠️ Không tìm thấy dữ liệu phù hợp với yêu cầu của bạn.")
                else:
                    st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet 'Tên các TBA'. Vui lòng kiểm tra tên sheet và quyền truy cập.")

            # Xử lý truy vấn liên quan đến doanh thu và biểu đồ
            elif "doanh thu" in user_msg_lower or "báo cáo tài chính" in user_msg_lower or "biểu đồ doanh thu" in user_msg_lower:
                records = get_sheet_data("DoanhThu")
                if records:
                    df = pd.DataFrame(records)
                    if not df.empty:
                        st.subheader("Dữ liệu Doanh thu")
                        st.dataframe(df)

                        if 'Tháng' in df.columns and 'Doanh thu' in df.columns:
                            try:
                                df['Doanh thu'] = pd.to_numeric(df['Doanh thu'], errors='coerce')
                                df = df.dropna(subset=['Doanh thu'])

                                st.subheader("Biểu đồ Doanh thu theo tháng")
                                fig, ax = plt.subplots(figsize=(12, 7))
                                colors = cm.get_cmap('viridis', len(df['Tháng'].unique()))
                                bars = ax.bar(df['Tháng'], df['Doanh thu'], color=colors.colors)

                                for bar in bars:
                                    yval = bar.get_height()
                                    ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, round(yval, 2), ha='center', va='bottom', color='black')

                                ax.set_xlabel("Tháng")
                                ax.set_ylabel("Doanh thu (Đơn vị)")
                                ax.set_title("Biểu đồ Doanh thu thực tế theo tháng")
                                plt.xticks(rotation=45, ha='right')
                                plt.tight_layout()
                                st.pyplot(fig, dpi=400)
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
                records = get_sheet_data("CBCNV")
                if records:
                    df_cbcnv = pd.DataFrame(records)

                    person_name = None
                    bo_phan = None
                    is_specific_query = False

                    name_match = re.search(r"(?:thông tin|của)\s+([a-zA-Z\s]+)", user_msg_lower)
                    if name_match:
                        person_name = name_match.group(1).strip()
                        known_keywords = ["trong", "tổ", "phòng", "đội", "cbcnv", "tất cả", "độ tuổi", "trình độ chuyên môn", "giới tính"]
                        for kw in known_keywords:
                            if kw in person_name:
                                person_name = person_name.split(kw, 1)[0].strip()
                                break
                        is_specific_query = True

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
                                is_specific_query = True
                            break

                    df_to_process = df_cbcnv.copy()

                    if person_name and 'Họ và tên' in df_to_process.columns:
                        temp_filtered_by_name = df_to_process[df_to_process['Họ và tên'].astype(str).str.lower() == person_name.lower()]
                        if temp_filtered_by_name.empty:
                            st.info(f"Không tìm thấy chính xác '{person_name.title()}'. Đang tìm kiếm gần đúng...")
                            temp_filtered_by_name = df_to_process[df_to_process['Họ và tên'].astype(str).str.lower().str.contains(person_name.lower(), na=False)]
                            if temp_filtered_by_name.empty:
                                st.warning(f"⚠️ Không tìm thấy người nào có tên '{person_name.title()}' hoặc tên gần giống.")
                                df_to_process = pd.DataFrame()
                            else:
                                df_to_process = temp_filtered_by_name
                        else:
                            df_to_process = temp_filtered_by_name

                    if bo_phan and 'Bộ phận công tác' in df_to_process.columns and not df_to_process.empty:
                        initial_filtered_count = len(df_to_process)
                        df_to_process = df_to_process[df_to_process['Bộ phận công tác'].str.lower().str.contains(bo_phan.lower(), na=False)]
                        if df_to_process.empty and initial_filtered_count > 0:
                            st.warning(f"⚠️ Không tìm thấy kết quả cho bộ phận '{bo_phan.title()}' trong danh sách đã lọc theo tên.")
                    elif bo_phan and 'Bộ phận công tác' in df_cbcnv.columns and not person_name:
                        df_to_process = df_cbcnv[df_cbcnv['Bộ phận công tác'].str.lower().str.contains(bo_phan.lower(), na=False)]
                        if df_to_process.empty:
                            st.warning(f"⚠️ Không tìm thấy dữ liệu cho bộ phận '{bo_phan.title()}'.")

                    df_to_show = df_to_process
                    if df_to_show.empty and not is_specific_query:
                        df_to_show = df_cbcnv
                        st.subheader("Toàn bộ thông tin CBCNV:")
                    elif not df_to_show.empty:
                        subheader_parts = ["Thông tin CBCNV"]
                        if person_name:
                            subheader_parts.append(f"của {person_name.title()}")
                        if bo_phan:
                            subheader_parts.append(f"thuộc {bo_phan.title()}")
                        st.subheader(" ".join(subheader_parts) + ":")
                    else:
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
                        st.dataframe(df_to_show)

                    if ("biểu đồ" in user_msg_lower or "báo cáo" in user_msg_lower) and not df_to_show.empty:
                        if 'Bộ phận công tác' in df_to_show.columns and not df_to_show['Bộ phận công tác'].empty:
                            st.subheader("Biểu đồ số lượng nhân viên theo Bộ phận công tác")
                            bo_phan_counts = df_to_show['Bộ phận công tác'].astype(str).fillna('Không xác định').value_counts()

                            if "biểu đồ tròn bộ phận công tác" not in user_msg_lower:
                                fig, ax = plt.subplots(figsize=(12, 7))
                                colors = cm.get_cmap('tab10', len(bo_phan_counts.index))
                                bars = ax.bar(bo_phan_counts.index, bo_phan_counts.values, color=colors.colors)
                                for bar in bars:
                                    yval = bar.get_height()
                                    ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, round(yval), ha='center', va='bottom', color='black')
                                ax.set_xlabel("Bộ phận công tác")
                                ax.set_ylabel("Số lượng nhân viên")
                                ax.set_title("Biểu đồ số lượng CBCNV theo Bộ phận")
                                plt.xticks(rotation=45, ha='right')
                                plt.tight_layout()
                                st.pyplot(fig, dpi=400)
                            else:
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
                        
                        if "độ tuổi" in user_msg_lower and 'Ngày sinh CBCNV' in df_to_show.columns:
                            st.subheader("Biểu đồ số lượng nhân viên theo độ tuổi")
                            current_year = datetime.datetime.now().year

                            def calculate_age(dob_str):
                                try:
                                    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%y'):
                                        try:
                                            dob = datetime.datetime.strptime(str(dob_str), fmt)
                                            return current_year - dob.year
                                        except ValueError:
                                            continue
                                    return None
                                except TypeError:
                                    return None

                            df_to_show['Tuổi'] = df_to_show['Ngày sinh CBCNV'].apply(calculate_age)
                            df_to_show = df_to_show.dropna(subset=['Tuổi'])

                            age_bins = [0, 30, 40, 50, 100]
                            age_labels = ['<30 tuổi', '30 đến <40 tuổi', '40 đến <50 tuổi', '>50 tuổi']
                            
                            df_to_show['Nhóm tuổi'] = pd.cut(df_to_show['Tuổi'], 
                                                             bins=age_bins, 
                                                             labels=age_labels, 
                                                             right=False,
                                                             include_lowest=True)

                            age_counts = df_to_show['Nhóm tuổi'].value_counts().reindex(age_labels, fill_value=0)

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

                        if "trình độ chuyên môn" in user_msg_lower and 'Trình độ chuyên môn' in df_to_show.columns:
                            st.subheader("Biểu đồ số lượng nhân viên theo Trình độ chuyên môn")
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

                        if "giới tính" in user_msg_lower and 'Giới tính' in df_to_show.columns:
                            st.subheader("Biểu đồ số lượng nhân viên theo Giới tính")
                            gioi_tinh_counts = df_to_show['Giới tính'].astype(str).fillna('Không xác định').value_counts()

                            fig, ax = plt.subplots(figsize=(8, 8))
                            colors = ['#66b3ff', '#ff9999', '#99ff99', '#ffcc99']

                            wedges, texts, autotexts = ax.pie(gioi_tinh_counts.values, 
                                                                labels=gioi_tinh_counts.index, 
                                                                autopct='%1.1f%%', 
                                                                startangle=90, 
                                                                colors=colors[:len(gioi_tinh_counts)],
                                                                pctdistance=0.85)
                            for autotext in autotexts:
                                autotext.set_color('black')
                                autotext.set_fontsize(10)

                            ax.axis('equal')
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
                                {"role": "user", "content": user_msg_lower}
                            ]
                        )
                        st.session_state.current_qa_display = response.choices[0].message.content
                    except Exception as e:
                        st.error(f"❌ Lỗi khi gọi OpenAI: {e}. Vui lòng kiểm tra API key hoặc quyền truy cập mô hình.")
                else:
                    st.warning("Không có API key OpenAI. Vui lòng thêm vào st.secrets để sử dụng chatbot cho các câu hỏi tổng quát.")

    # Luôn hiển thị câu trả lời QA hiện tại nếu có
    if st.session_state.current_qa_display:
        st.info("Câu trả lời:")
        st.write(st.session_state.current_qa_display)

    # Nút "Tìm tiếp" chỉ hiển thị khi có nhiều hơn một kết quả QA và chưa hiển thị hết
    if st.session_state.qa_results and st.session_state.qa_index < len(st.session_state.qa_results):
        if st.button("Tìm tiếp"):
            st.session_state.current_qa_display = st.session_state.qa_results[st.session_state.qa_index]
            st.session_state.qa_index += 1
            st.rerun()
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
