import gspread
import json
import re # Đã thêm
import pandas as pd # Đã thêm
import streamlit as st
from google.oauth2.service_account import Credentials
from audio_recorder_streamlit import audio_recorder
import speech_recognition as sr
import tempfile
import os
from openai import OpenAI
from pathlib import Path
import easyocr
from fuzzywuzzy import fuzz

# Cấu hình API Google Sheet
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

# Check for secrets before proceeding
if "google_service_account" in st.secrets:
    info = st.secrets["google_service_account"]
    try:
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        client = gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Lỗi xác thực Google Service Account: {e}. Vui lòng kiểm tra lại file bí mật.")
        st.stop()
else:
    st.error("❌ Không tìm thấy google_service_account trong secrets. Vui lòng cấu hình.")
    st.stop()

# Lấy API key OpenAI
openai_api_key = st.secrets.get("openai_api_key")
client_ai = OpenAI(api_key=openai_api_key) if openai_api_key else None
if openai_api_key:
    st.success("✅ Đã kết nối OpenAI API key từ Streamlit secrets.")

spreadsheet_url = "https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit"

# Hàm để lấy dữ liệu từ một sheet cụ thể
def get_sheet_data(sheet_name):
    try:
        sheet = client.open_by_url(spreadsheet_url).worksheet(sheet_name)
        
        if sheet_name == "KPI":
            all_values = sheet.get_all_values()
            if all_values:
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
qa_df = pd.DataFrame(qa_data) if qa_data is not None else pd.DataFrame()

# Hàm lấy dữ liệu từ tất cả sheet trong file (từ app - Copy (2).py)
@st.cache_data
def load_all_sheets():
    try:
        spreadsheet = client.open_by_url(spreadsheet_url)
        sheet_names = [ws.title for ws in spreadsheet.worksheets()]
        data = {}
        for name in sheet_names:
            try:
                records = spreadsheet.worksheet(name).get_all_records()
                data[name] = pd.DataFrame(records)
            except Exception as e:
                st.warning(f"⚠️ Lỗi khi tải sheet '{name}': {e}")
                data[name] = pd.DataFrame()
        return data
    except Exception as e:
        st.error(f"❌ Lỗi khi tải tất cả sheets: {e}")
        return {}

all_data = load_all_sheets()

# Hàm để đọc câu hỏi từ file JSON
def load_sample_questions(file_path="sample_questions.json"):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            questions_data = json.load(f)
        if isinstance(questions_data, list) and all(isinstance(q, str) for q in questions_data):
            return questions_data
        elif isinstance(questions_data, list) and all(isinstance(q, dict) and "text" in q for q in questions_data):
            return [q["text"] for q in questions_data]
        else:
            st.error("Định dạng file sample_questions.json không hợp lệ.")
            return []
    except FileNotFoundError:
        st.warning(f"⚠️ Không tìm thấy file: {file_path}.")
        return []
    except json.JSONDecodeError:
        st.error(f"❌ Lỗi đọc file JSON: {file_path}.")
        return []

sample_questions_from_file = load_sample_questions()

# --- Bắt đầu bố cục mới: Logo ở trái, phần còn lại của chatbot căn giữa ---
header_col1, header_col2 = st.columns([1, 8])

with header_col1:
    public_logo_url = "https://raw.githubusercontent.com/phamlong666/Chatbot/main/logo_hinh_tron.png"
    try:
        st.image(public_logo_url, width=100)
    except Exception as e_public_url:
        st.error(f"❌ Lỗi khi hiển thị logo: {e_public_url}")

with header_col2:
    st.markdown("<h1 style='font-size: 30px;'>🤖 Chatbot Đội QLĐLKV Định Hóa</h1>", unsafe_allow_html=True)

col_left_spacer, col_main_content, col_right_spacer = st.columns([1, 5, 1])

with col_main_content:
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
    if "audio_processed" not in st.session_state:
        st.session_state.audio_processed = False
    
    # --- Trích xuất văn bản từ ảnh (OCR) ---
    st.markdown("### 📸 Hoặc tải ảnh chứa câu hỏi (nếu có)")
    uploaded_image = st.file_uploader("Tải ảnh câu hỏi", type=["jpg", "png", "jpeg"])

    def extract_text_from_image(image_path):
        reader = easyocr.Reader(['vi'])
        result = reader.readtext(image_path, detail=0)
        text = " ".join(result)
        return text

    if uploaded_image is not None:
        temp_image_path = Path("temp_uploaded_image.jpg")
        with open(temp_image_path, "wb") as f:
            f.write(uploaded_image.getbuffer())

        try:
            extracted_text = extract_text_from_image(str(temp_image_path))
            st.success("✅ Đã quét được nội dung từ ảnh:")
            st.write(extracted_text)
            st.session_state.user_input_value = extracted_text
            st.rerun()
        except Exception as e:
            st.error(f"❌ Lỗi khi trích xuất văn bản từ ảnh: {e}")
        finally:
            if temp_image_path.exists():
                os.remove(temp_image_path)

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
                    st.session_state.user_input_value = text
                    st.session_state.audio_processed = True
                    st.rerun()
                except sr.UnknownValueError:
                    st.warning("⚠️ Không nhận dạng được giọng nói.")
                except sr.RequestError as e:
                    st.error(f"❌ Lỗi nhận dạng: {e}")
        finally:
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)

    with st.form(key='chat_buttons_form'):
        mic_col, send_button_col, clear_button_col = st.columns([9, 1, 1])
        with mic_col:
            user_msg_input_in_form = st.text_input("Nhập lệnh hoặc dùng micro để nói:", value=st.session_state.get("user_input_value", ""), key="user_input_value")
        with send_button_col:
            send_button_pressed = st.form_submit_button("Gửi")
        with clear_button_col:
            clear_button_pressed = st.form_submit_button("Xóa")

    def on_sample_question_select():
        st.session_state.user_input_value = st.session_state.sample_question_selector

    selected_sample_question = st.selectbox(
        "Chọn câu hỏi từ danh sách:",
        options=[""] + sample_questions_from_file,
        index=0,
        key="sample_question_selector",
        on_change=on_sample_question_select
    )

    question_to_process = st.session_state.user_input_value.strip()

    if clear_button_pressed:
        st.session_state.user_input_value = ""
        st.session_state.qa_results = []
        st.session_state.qa_index = 0
        st.session_state.last_processed_user_msg = ""
        st.session_state.current_qa_display = ""
        st.session_state.audio_processed = False
        st.rerun()

    if send_button_pressed and question_to_process:
        st.info(f"📨 Đang xử lý câu hỏi: {question_to_process}")
        st.session_state.last_processed_user_msg = question_to_process
        st.session_state.audio_processed = False

        st.session_state.qa_results = []
        st.session_state.qa_index = 0
        st.session_state.current_qa_display = ""

        user_msg_lower = question_to_process.lower()

        found_qa_answer = False

        if user_msg_lower.startswith("an toàn:"):
            specific_question_for_safety = normalize_text(user_msg_lower.replace("an toàn:", "").strip())
            if not qa_df.empty and 'Câu hỏi' in qa_df.columns and 'Câu trả lời' in qa_df.columns:
                exact_match_found_for_safety = False
                for index, row in qa_df.iterrows():
                    question_from_sheet_normalized = normalize_text(str(row['Câu hỏi']))
                    if specific_question_for_safety == question_from_sheet_normalized:
                        st.session_state.qa_results.append(str(row['Câu trả lời']))
                        exact_match_found_for_safety = True
                        found_qa_answer = True
                if not exact_match_found_for_safety:
                    st.warning("⚠️ Không tìm thấy câu trả lời chính xác 100%.")
                    found_qa_answer = True

        if not found_qa_answer and not qa_df.empty and 'Câu hỏi' in qa_df.columns and 'Câu trả lời' in qa_df.columns:
            all_matches = []
            for index, row in qa_df.iterrows():
                question_from_sheet = str(row['Câu hỏi']).lower()
                score = fuzz.ratio(user_msg_lower, question_from_sheet)
                if score >= 60:
                    all_matches.append({'question': str(row['Câu hỏi']), 'answer': str(row['Câu trả lời']), 'score': score})
            all_matches.sort(key=lambda x: x['score'], reverse=True)
            if all_matches:
                st.session_state.qa_results = [match['answer'] for match in all_matches]
                st.session_state.qa_index = 0
                found_qa_answer = True
            else:
                found_qa_answer = False

        if found_qa_answer:
            if st.session_state.qa_results:
                st.session_state.current_qa_display = st.session_state.qa_results[st.session_state.qa_index]
                if len(st.session_state.qa_results) > 1:
                    st.session_state.qa_index += 1
            pass
        else:
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
            elif "kpi" in user_msg_lower or "chỉ số hiệu suất" in user_msg_lower or "kết quả hoạt động" in user_msg_lower:
                records = get_sheet_data("KPI")
                if records:
                    df_kpi = pd.DataFrame(records)
                    
                    if 'Năm' in df_kpi.columns:
                        df_kpi['Năm'] = df_kpi['Năm'].astype(str).str.extract(r'(\d{4})')[0]
                        df_kpi['Năm'] = pd.to_numeric(df_kpi['Năm'], errors='coerce').dropna().astype(int)
                    else:
                        st.warning("⚠️ Không tìm thấy cột 'Năm' trong sheet 'KPI'.")
                        df_kpi = pd.DataFrame()

                    if 'Tháng' in df_kpi.columns:
                        df_kpi['Tháng'] = pd.to_numeric(df_kpi['Tháng'], errors='coerce').dropna().astype(int)
                    else:
                        st.warning("⚠️ Không tìm thấy cột 'Tháng' trong sheet 'KPI'.")
                        df_kpi = pd.DataFrame()

                    kpi_value_column = 'Điểm KPI'

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

                        selected_unit_col = unit_column_mapping.get(unit_name_from_query)

                        if target_year_kpi and "so sánh" in user_msg_lower and selected_unit_col:
                            st.subheader(f"Biểu đồ KPI theo tháng cho năm {target_year_kpi} và các năm trước")
                            df_to_plot_line = df_kpi[df_kpi['Đơn vị'].astype(str).str.lower() == selected_unit_col.lower()].copy()
                            if not df_to_plot_line.empty:
                                try:
                                    df_to_plot_line.loc[:, kpi_value_column] = df_to_plot_line[kpi_value_column].astype(str).str.replace(',', '.', regex=False)
                                    df_to_plot_line.loc[:, kpi_value_column] = pd.to_numeric(df_to_plot_line[kpi_value_column], errors='coerce')
                                    df_to_plot_line.dropna(subset=[kpi_value_column, 'Năm', 'Tháng'], inplace=True)
                                    
                                    years_to_plot = sorted(df_to_plot_line['Năm'].unique())
                                    
                                    chart_data = pd.melt(df_to_plot_line, id_vars=['Năm', 'Tháng'], value_vars=[kpi_value_column], var_name='KPI_Type', value_name='Value')
                                    chart_data['Year_Month'] = chart_data['Năm'].astype(str) + '-' + chart_data['Tháng'].astype(str).str.zfill(2)
                                    
                                    # Plotting with Streamlit's built-in line chart
                                    st.line_chart(chart_data.set_index('Year_Month')[['Value']])
                                except Exception as plot_e:
                                    st.error(f"❌ Lỗi khi vẽ biểu đồ: {plot_e}")
                            else:
                                st.warning(f"⚠️ Không tìm thấy dữ liệu cho đơn vị '{selected_unit_col}'")

    if st.session_state.current_qa_display:
        st.markdown("---")
        st.subheader("💡 Câu trả lời")
        st.write(st.session_state.current_qa_display)
        if len(st.session_state.qa_results) > st.session_state.qa_index:
            if st.button("Tìm câu trả lời khác"):
                st.session_state.current_qa_display = st.session_state.qa_results[st.session_state.qa_index]
                st.session_state.qa_index += 1
                st.rerun()

    if not st.session_state.current_qa_display and st.session_state.last_processed_user_msg:
        st.markdown("---")
        st.warning("⚠️ Không tìm thấy câu trả lời phù hợp trong cơ sở dữ liệu.")
