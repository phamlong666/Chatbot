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
    # st.success("✅ Đã kết nối OpenAI API key từ Streamlit secrets.")
else:
    st.warning("⚠️ Không tìm thấy 'openai_api_key' trong secrets.toml. Các chức năng xử lý câu hỏi phức tạp sẽ không hoạt động.")

if openai_api_key:
    client_ai = OpenAI(api_key=openai_api_key)
else:
    client_ai = None

# URL của Google Sheets
spreadsheet_url = "https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit"

# --- CÁC HÀM XỬ LÝ DỮ LIỆU TỪ GOOGLE SHEETS VÀ TẠO CÂU TRẢ LỜI ---
def get_sheet_data(sheet_name):
    """
    Hàm để lấy dữ liệu từ một sheet cụ thể và xử lý các tiêu đề trùng lặp cho sheet KPI.
    """
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
                return df_temp.to_dict('records')
            else:
                return []
        else:
            return sheet.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Không tìm thấy sheet '{sheet_name}'. Vui lòng kiểm tra tên sheet.")
        return None
    except Exception as e:
        st.error(f"❌ Lỗi khi mở Google Sheet '{sheet_name}': {e}. Vui lòng kiểm tra định dạng tiêu đề của sheet. Nếu có tiêu đề trùng lặp, hãy đảm bảo chúng là duy nhất.")
        return None

def normalize_text(text):
    """
    Hàm chuẩn hóa chuỗi để so sánh chính xác hơn (loại bỏ dấu cách thừa, chuyển về chữ thường).
    """
    if isinstance(text, str):
        return re.sub(r'\s+', ' ', text).strip().lower()
    return ""

# Tải dữ liệu từ sheet "Hỏi-Trả lời" một lần khi ứng dụng khởi động
qa_data = get_sheet_data("Hỏi-Trả lời")
qa_df = pd.DataFrame(qa_data) if qa_data else pd.DataFrame()

@st.cache_data
def load_all_sheets():
    """
    Tải dữ liệu từ tất cả sheet trong file Google Sheets.
    """
    try:
        spreadsheet = client.open_by_url(spreadsheet_url)
        sheet_names = [ws.title for ws in spreadsheet.worksheets()]
        data = {}
        for name in sheet_names:
            try:
                # Dùng hàm get_sheet_data để xử lý cả KPI
                records = get_sheet_data(name)
                if records is not None:
                    data[name] = pd.DataFrame(records)
            except Exception as e:
                st.warning(f"⚠️ Lỗi khi tải dữ liệu từ sheet '{name}': {e}")
                data[name] = pd.DataFrame()
        return data
    except Exception as e:
        st.error(f"❌ Lỗi khi tải danh sách các sheet: {e}")
        return {}

all_data = load_all_sheets()

def load_sample_questions(file_path="sample_questions.json"):
    """
    Hàm để đọc câu hỏi từ file JSON.
    """
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

def find_similar_questions(user_question, data, threshold=80):
    """
    Tìm các câu hỏi tương tự trong DataFrame QA sử dụng thư viện fuzzywuzzy.
    Trả về một danh sách các câu trả lời tương ứng.
    """
    normalized_user_question = normalize_text(user_question)
    
    similar_q_a = []
    if not data.empty:
        for index, row in data.iterrows():
            question = row.get("Câu hỏi", "")
            answer = row.get("Trả lời", "")
            if question and answer:
                normalized_question = normalize_text(question)
                similarity_ratio = fuzz.ratio(normalized_user_question, normalized_question)
                if similarity_ratio >= threshold:
                    similar_q_a.append((similarity_ratio, answer))
    
    # Sắp xếp kết quả theo độ tương tự giảm dần
    similar_q_a.sort(key=lambda x: x[0], reverse=True)
    
    # Chỉ trả về phần câu trả lời
    return [item[1] for item in similar_q_a]

def plot_bar_chart(df, x_col, y_col, title, unit=""):
    """
    Hàm để vẽ biểu đồ cột.
    """
    df_sorted = df.sort_values(by=y_col, ascending=False)
    
    colors = cm.viridis(np.linspace(0, 1, len(df_sorted)))
    
    fig, ax = plt.subplots(figsize=(12, 8))
    bars = ax.bar(df_sorted[x_col], df_sorted[y_col], color=colors)
    
    ax.set_xlabel(x_col)
    ax.set_ylabel(f"{y_col} ({unit})")
    ax.set_title(title, pad=20)
    plt.xticks(rotation=45, ha='right')
    
    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height:,.0f}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha='center',
                    va='bottom')
    
    plt.tight_layout()
    st.pyplot(fig)

def plot_line_chart(df, x_col, y_col, title, unit=""):
    """
    Hàm để vẽ biểu đồ đường.
    """
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.plot(df[x_col], df[y_col], marker='o', linestyle='-', color='b')
    ax.set_xlabel(x_col)
    ax.set_ylabel(f"{y_col} ({unit})")
    ax.set_title(title)
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    st.pyplot(fig)

def plot_pie_chart(df, values_col, names_col, title):
    """
    Hàm để vẽ biểu đồ tròn.
    """
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.pie(df[values_col], labels=df[names_col], autopct='%1.1f%%', startangle=90, colors=cm.Paired(np.arange(len(df))))
    ax.axis('equal')
    ax.set_title(title)
    plt.tight_layout()
    st.pyplot(fig)

def process_complex_query(user_question, all_data, client_ai):
    """
    Sử dụng OpenAI API để xử lý các câu hỏi phức tạp hơn.
    """
    if client_ai is None:
        st.warning("❌ Không tìm thấy OpenAI API key. Vui lòng cấu hình để sử dụng chức năng này.")
        return None

    system_prompt = f"""
    Bạn là một trợ lý ảo chuyên xử lý dữ liệu và tạo báo cáo cho Đội Quản lý đường lưới khu vực Định Hóa.
    Bạn có quyền truy cập vào các bộ dữ liệu sau từ Google Sheets:
    - Sheet 'KPI': Thông tin KPI hàng tháng.
    - Sheet 'CBCNV': Thông tin cán bộ công nhân viên.
    - Sheet 'Sự cố': Thông tin các sự cố.
    - Sheet 'Lãnh đạo': Thông tin lãnh đạo các xã.

    Dữ liệu thô hiện có của bạn (chỉ hiển thị vài dòng đầu) là:
    {json.dumps({name: data.head(2).to_dict('records') for name, data in all_data.items()}, ensure_ascii=False, indent=2)}

    Yêu cầu của bạn là:
    1. Phân tích câu hỏi của người dùng để xác định sheet dữ liệu cần dùng và các thông tin cần trích xuất.
    2. Dựa trên phân tích, đưa ra một JSON Object duy nhất chứa các thông tin sau:
        - "sheet_name": Tên sheet cần truy vấn (ví dụ: "KPI", "CBCNV", "Sự cố", "Lãnh đạo").
        - "action": Hành động cần thực hiện ("trả lời", "vẽ biểu đồ", "so sánh").
        - "filters": Một dictionary chứa các bộ lọc (ví dụ: {{"Thời gian": "tháng 6 năm 2025"}}).
        - "chart_type": (Nếu action là "vẽ biểu đồ") Loại biểu đồ cần vẽ ("cột", "đường", "tròn").
        - "x_axis": (Nếu cần vẽ biểu đồ) Tên cột cho trục x.
        - "y_axis": (Nếu cần vẽ biểu đồ) Tên cột cho trục y.
        - "compare_with": (Nếu action là "so sánh") Thông tin so sánh (ví dụ: "cùng kỳ", "năm trước").
        - "sort_by": (Nếu cần sắp xếp) Tên cột để sắp xếp.
        - "sort_order": (Nếu cần sắp xếp) Thứ tự sắp xếp ("tăng dần", "giảm dần").
    3. Nếu không thể tạo JSON hợp lệ, hãy trả lời bằng một câu văn bản thông thường.
    4. Cần đảm bảo các trường trong JSON phải chính xác và không bị thiếu. Nếu một trường không có, không cần đưa vào JSON.

    Ví dụ về JSON bạn cần tạo:
    - Câu hỏi: "Lấy thông tin KPI của các đơn vị tháng 6 năm 2025 và sắp xếp theo thứ tự giảm dần"
    - JSON: {{"sheet_name": "KPI", "action": "trả lời", "filters": {{"Thời gian": "tháng 6 năm 2025"}}, "sort_by": "Chỉ tiêu", "sort_order": "giảm dần"}}
    - Câu hỏi: "Lấy thông tin CBCNV và vẽ biểu đồ theo độ tuổi"
    - JSON: {{"sheet_name": "CBCNV", "action": "vẽ biểu đồ", "filters": {{}}, "chart_type": "cột", "x_axis": "Độ tuổi", "y_axis": "Số lượng"}}

    Chú ý: Hạn chế tối đa việc tạo ra các trường không cần thiết trong JSON. Hãy đưa ra một JSON object duy nhất và hợp lệ.
    """

    try:
        response = client_ai.chat.completions.create(
            model="gpt-3.5-turbo",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_question}
            ],
            temperature=0
        )
        json_output = response.choices[0].message.content
        st.write(f"Đã nhận JSON từ API: {json_output}") # Để debug
        return json.loads(json_output)
    except json.JSONDecodeError:
        st.error("❌ API trả về JSON không hợp lệ. Vui lòng thử lại hoặc thay đổi câu hỏi.")
        return None
    except Exception as e:
        st.error(f"❌ Lỗi khi gọi OpenAI API: {e}. Vui lòng kiểm tra API key hoặc thử lại.")
        return None

def generate_complex_answer(query_json, all_data):
    """
    Xử lý JSON object từ OpenAI để tạo câu trả lời hoặc biểu đồ.
    """
    if query_json is None:
        return "Xin lỗi, không thể xử lý yêu cầu của bạn do lỗi phân tích JSON từ API."
        
    sheet_name = query_json.get("sheet_name")
    action = query_json.get("action")
    filters = query_json.get("filters", {})
    
    if not sheet_name or sheet_name not in all_data:
        return f"Xin lỗi, tôi không tìm thấy sheet '{sheet_name}' hoặc không thể xử lý yêu cầu này."

    df = all_data[sheet_name]
    if df.empty:
        return f"Dữ liệu trong sheet '{sheet_name}' đang trống. Vui lòng cập nhật dữ liệu."

    filtered_df = df.copy()

    # Áp dụng bộ lọc
    for key, value in filters.items():
        if key in filtered_df.columns:
            filtered_df = filtered_df[filtered_df[key].astype(str).str.contains(value, case=False, na=False, regex=True)]
    
    if filtered_df.empty:
        return f"Xin lỗi, không có dữ liệu nào phù hợp với bộ lọc bạn đã yêu cầu."

    # Xử lý các hành động
    if action == "trả lời":
        sort_by = query_json.get("sort_by")
        sort_order = query_json.get("sort_order")
        
        if sort_by and sort_by in filtered_df.columns:
            ascending = sort_order != "giảm dần"
            # Thử chuyển đổi sang số để sắp xếp nếu có thể
            try:
                filtered_df[sort_by] = pd.to_numeric(filtered_df[sort_by], errors='coerce')
                filtered_df = filtered_df.sort_values(by=sort_by, ascending=ascending, na_position='last')
            except:
                filtered_df = filtered_df.sort_values(by=sort_by, ascending=ascending)
        
        markdown_table = filtered_df.to_markdown(index=False)
        return f"Dưới đây là kết quả của bạn:\n\n{markdown_table}"
    
    elif action == "vẽ biểu đồ":
        chart_type = query_json.get("chart_type")
        x_axis = query_json.get("x_axis")
        y_axis = query_json.get("y_axis")
        
        if not x_axis or not y_axis or x_axis not in filtered_df.columns or y_axis not in filtered_df.columns:
            return "Xin lỗi, không đủ thông tin để vẽ biểu đồ (thiếu trục x hoặc y)."

        filtered_df[y_axis] = pd.to_numeric(filtered_df[y_axis], errors='coerce')
        filtered_df.dropna(subset=[y_axis], inplace=True)
        
        title = f"Biểu đồ {chart_type} của {y_axis} theo {x_axis}"
        
        if chart_type == "cột":
            plot_bar_chart(filtered_df, x_axis, y_axis, title)
            return "Biểu đồ đã được tạo thành công."
        elif chart_type == "đường":
            plot_line_chart(filtered_df, x_axis, y_axis, title)
            return "Biểu đồ đã được tạo thành công."
        elif chart_type == "tròn":
            plot_pie_chart(filtered_df, y_axis, x_axis, title)
            return "Biểu đồ đã được tạo thành công."
        else:
            return f"Loại biểu đồ '{chart_type}' không được hỗ trợ."
    
    elif action == "so sánh":
        compare_with = query_json.get("compare_with")
        # Logic so sánh phức tạp hơn sẽ cần triển khai ở đây
        return "Tính năng so sánh đang được phát triển, vui lòng thử lại sau."
        
    else:
        return f"Hành động '{action}' không được hỗ trợ."

# Hàm OCR: đọc text từ ảnh
def extract_text_from_image(image_path):
    """
    Extracts Vietnamese text from an image file using EasyOCR.
    """
    reader = easyocr.Reader(['vi'])
    result = reader.readtext(image_path, detail=0)
    text = " ".join(result)
    return text

# --- Bắt đầu bố cục mới: Logo ở trái, phần còn lại của chatbot căn giữa ---
header_col1, header_col2 = st.columns([1, 8])

with header_col1:
    public_logo_url = "https://raw.githubusercontent.com/phamlong666/Chatbot/main/logo_hinh_tron.png"
    try:
        st.image(public_logo_url, width=100)
    except Exception as e:
        st.error(f"❌ Lỗi khi hiển thị logo: {e}.")

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
        st.session_state.audio_processed = False

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
        
        matching_answers = find_similar_questions(question_to_process, qa_df)
        
        if matching_answers:
            st.session_state.qa_results = matching_answers
            st.session_state.qa_index = 1
            st.session_state.current_qa_display = st.session_state.qa_results[0]
            st.success("✅ Đã tìm thấy câu trả lời tương tự trong cơ sở dữ liệu có sẵn.")
        else:
            if client_ai:
                st.info("💡 Không tìm thấy câu trả lời trực tiếp. Đang sử dụng OpenAI để xử lý...")
                query_json = process_complex_query(question_to_process, all_data, client_ai)
                if query_json:
                    answer = generate_complex_answer(query_json, all_data)
                    st.session_state.current_qa_display = answer
                else:
                    st.session_state.current_qa_display = "Xin lỗi, không thể xử lý yêu cầu của bạn."
            else:
                st.session_state.current_qa_display = "Xin lỗi, không tìm thấy OpenAI API key để xử lý yêu cầu này."
        
        st.rerun()

    if st.session_state.current_qa_display:
        st.info("Câu trả lời:")
        
        if "Biểu đồ đã được tạo thành công." not in st.session_state.current_qa_display:
            st.write(st.session_state.current_qa_display)

    if st.session_state.qa_results and st.session_state.qa_index < len(st.session_state.qa_results):
        if st.button("Tìm tiếp"):
            st.session_state.current_qa_display = st.session_state.qa_results[st.session_state.qa_index]
            st.session_state.qa_index += 1
            st.rerun()
    elif st.session_state.qa_results and st.session_state.qa_index >= len(st.session_state.qa_results) and len(st.session_state.qa_results) > 1:
        st.info("Đã hiển thị tất cả các câu trả lời tương tự.")

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
        st.error(f"❌ Lỗi trong quá trình xử lý ảnh: {e}")
    finally:
        if temp_image_path.exists():
            os.remove(temp_image_path)
