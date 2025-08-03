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
plt.rcParams['font.size'] = 14
plt.rcParams['axes.labelsize'] = 14
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['xtick.labelsize'] = 14
plt.rcParams['ytick.labelsize'] = 14
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
        st.session_state.current_qa_display = ""  # Clear previous display

        user_msg_lower = question_to_process.lower() # Bây giờ user_msg_lower được lấy từ question_to_process

        # --- Bổ sung logic tìm kiếm câu trả lời trong sheet "Hỏi-Trả lời" ---
        found_qa_answer = False
        # NEW LOGIC: Kiểm tra cú pháp "An toàn:..." để yêu cầu khớp chính xác 100% sau khi chuẩn hóa
        if user_msg_lower.startswith("an toàn:"):
            # Trích xuất và chuẩn hóa phần câu hỏi thực tế sau "An toàn:"
            specific_question_for_safety = normalize_text(user_msg_lower.replace("an toàn:", "").strip())
            
            # Sử dụng list comprehension để tìm tất cả các câu trả lời khớp chính xác
            if not qa_df.empty and 'Câu hỏi' in qa_df.columns and 'Câu trả lời' in qa_df.columns:
                st.session_state.qa_results = [
                    row['Câu trả lời'] for index, row in qa_df.iterrows()
                    if normalize_text(row['Câu hỏi']) == specific_question_for_safety
                ]
            
            if st.session_state.qa_results:
                st.info("💡 Tìm thấy câu hỏi có độ chính xác 100%.")
                st.session_state.current_qa_display = st.session_state.qa_results[0]
                st.session_state.qa_index = 1
                found_qa_answer = True
            
        else: # Nếu không có cú pháp "an toàn:", tìm kiếm gần đúng
            if not qa_df.empty and 'Câu hỏi' in qa_df.columns and 'Câu trả lời' in qa_df.columns:
                # Sử dụng fuzzywuzzy để tìm các câu hỏi tương tự và sắp xếp theo độ tương đồng
                qa_df['Tỷ lệ tương đồng'] = qa_df['Câu hỏi'].apply(lambda x: fuzz.ratio(normalize_text(question_to_process), normalize_text(x)))
                
                # Lấy các kết quả có tỷ lệ tương đồng cao hơn ngưỡng (ví dụ: 80)
                qa_matches = qa_df[qa_df['Tỷ lệ tương đồng'] >= 80].sort_values(by='Tỷ lệ tương đồng', ascending=False)

                if not qa_matches.empty:
                    st.session_state.qa_results = qa_matches['Câu trả lời'].tolist()
                    st.info(f"💡 Tìm thấy {len(st.session_state.qa_results)} câu trả lời có độ tương đồng cao. Hiển thị kết quả tốt nhất:")
                    st.session_state.current_qa_display = st.session_state.qa_results[0]
                    st.session_state.qa_index = 1
                    found_qa_answer = True
                else:
                    st.info("Không tìm thấy câu trả lời trực tiếp trong Sổ tay, đang thử hỏi AI...")

        if not found_qa_answer and client_ai:
            # Nếu không tìm thấy câu trả lời nào trong sheet, chuyển sang hỏi AI
            try:
                # Tạo một prompt cho mô hình AI
                prompt_text = f"""
                Bạn là một trợ lý chatbot thông minh được thiết kế để trả lời các câu hỏi về thông tin nội bộ của Công ty Điện lực Thái Nguyên. 
                Bạn có quyền truy cập vào các bộ dữ liệu sau:
                - Dữ liệu KPI: trong dataframe 'KPI'
                - Dữ liệu nhân sự: trong dataframe 'CBCNV'
                - Dữ liệu sự cố: trong dataframe 'Suco'
                - Dữ liệu tài sản: trong dataframe 'Taisan'
                - Dữ liệu lãnh đạo: trong dataframe 'Lanhdao'
                
                Dữ liệu hiện tại:
                {json.dumps({k: v.to_dict('records') for k, v in all_data.items()})}

                Yêu cầu:
                1. Dựa vào dữ liệu được cung cấp, hãy trả lời câu hỏi của người dùng.
                2. Nếu câu hỏi liên quan đến dữ liệu KPI, CBCNV, Suco, Taisan, Lanhdao, hãy sử dụng thông tin trong các dataframe tương ứng để trả lời.
                3. Nếu câu hỏi không liên quan đến dữ liệu trên, hãy trả lời một cách tự nhiên và lịch sự.
                4. Cung cấp câu trả lời ngắn gọn, trực tiếp, và đi thẳng vào vấn đề. Nếu câu hỏi liên quan đến số liệu, hãy trích dẫn số liệu cụ thể.
                5. TUYỆT ĐỐI không được bịa đặt thông tin. Nếu không có thông tin, hãy nói rõ là "Tôi không có thông tin về vấn đề này."
                6. Nếu câu hỏi yêu cầu so sánh hoặc thống kê, hãy sử dụng dữ liệu để đưa ra câu trả lời chi tiết. Nếu cần, hãy tạo một biểu đồ để minh họa, nhưng TUYỆT ĐỐI không được tạo biểu đồ trừ khi được yêu cầu.

                Câu hỏi của người dùng: "{question_to_process}"
                """
                
                with st.spinner("⏳ AI đang tìm kiếm và phân tích dữ liệu..."):
                    response = client_ai.chat.completions.create(
                        model="gpt-3.5-turbo",  # Có thể thay đổi model nếu cần
                        messages=[{"role": "user", "content": prompt_text}],
                        temperature=0.2, # Giảm nhiệt độ để có câu trả lời chính xác, ít sáng tạo hơn
                    )
                    ai_answer = response.choices[0].message.content
                    st.success("🤖 AI đã có câu trả lời:")
                    st.write(ai_answer)
            except Exception as e:
                st.error(f"❌ Lỗi khi gọi API OpenAI: {e}. Vui lòng kiểm tra API key hoặc kết nối internet.")
        elif not found_qa_answer and not client_ai:
            st.warning("⚠️ Không có câu trả lời trong Sổ tay và chưa có OpenAI API key để xử lý. Vui lòng cấu hình API key.")
    
    # Hiển thị câu trả lời từ QA và nút "Tìm tiếp"
    if st.session_state.current_qa_display:
        st.markdown("### Câu trả lời:")
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
            f.write(uploaded_image.getvalue())
        
        st.info("⏳ Đang xử lý ảnh để trích xuất văn bản...")
        image_text = extract_text_from_image(str(temp_image_path))
        
        if image_text:
            st.success("✅ Đã trích xuất văn bản thành công!")
            st.write(f"📝 Văn bản từ ảnh: **{image_text}**")
            st.session_state.user_input_value = image_text # Cập nhật ô nhập liệu chính
            
            # Kích hoạt lại logic tìm kiếm ngay lập tức với văn bản đã trích xuất
            # Vì đây là một hành động mới, ta sẽ reset các kết quả tìm kiếm cũ
            st.session_state.qa_results = []
            st.session_state.qa_index = 0
            st.session_state.current_qa_display = ""
            
            user_msg_lower = image_text.lower()
            
            found_qa_answer = False
            # Tìm kiếm gần đúng với văn bản từ ảnh
            if not qa_df.empty and 'Câu hỏi' in qa_df.columns and 'Câu trả lời' in qa_df.columns:
                qa_df['Tỷ lệ tương đồng'] = qa_df['Câu hỏi'].apply(lambda x: fuzz.ratio(normalize_text(image_text), normalize_text(x)))
                qa_matches = qa_df[qa_df['Tỷ lệ tương đồng'] >= 80].sort_values(by='Tỷ lệ tương đồng', ascending=False)
                
                if not qa_matches.empty:
                    st.session_state.qa_results = qa_matches['Câu trả lời'].tolist()
                    st.info(f"💡 Tìm thấy {len(st.session_state.qa_results)} câu trả lời có độ tương đồng cao với văn bản trong ảnh. Hiển thị kết quả tốt nhất:")
                    st.session_state.current_qa_display = st.session_state.qa_results[0]
                    st.session_state.qa_index = 1
                    found_qa_answer = True
                else:
                    st.info("Không tìm thấy câu trả lời trực tiếp trong Sổ tay, đang thử hỏi AI...")
            
            if not found_qa_answer and client_ai:
                try:
                    # Tạo prompt cho AI với văn bản từ ảnh
                    prompt_text = f"""
                    Bạn là một trợ lý chatbot thông minh được thiết kế để trả lời các câu hỏi về thông tin nội bộ của Công ty Điện lực Thái Nguyên. 
                    Bạn có quyền truy cập vào các bộ dữ liệu sau:
                    - Dữ liệu KPI: trong dataframe 'KPI'
                    - Dữ liệu nhân sự: trong dataframe 'CBCNV'
                    - Dữ liệu sự cố: trong dataframe 'Suco'
                    - Dữ liệu tài sản: trong dataframe 'Taisan'
                    - Dữ liệu lãnh đạo: trong dataframe 'Lanhdao'
                    
                    Dữ liệu hiện tại:
                    {json.dumps({k: v.to_dict('records') for k, v in all_data.items()})}
                    
                    Yêu cầu:
                    1. Dựa vào dữ liệu được cung cấp, hãy trả lời câu hỏi của người dùng.
                    2. Nếu câu hỏi liên quan đến dữ liệu KPI, CBCNV, Suco, Taisan, Lanhdao, hãy sử dụng thông tin trong các dataframe tương ứng để trả lời.
                    3. Nếu câu hỏi không liên quan đến dữ liệu trên, hãy trả lời một cách tự nhiên và lịch sự.
                    4. Cung cấp câu trả lời ngắn gọn, trực tiếp, và đi thẳng vào vấn đề. Nếu câu hỏi liên quan đến số liệu, hãy trích dẫn số liệu cụ thể.
                    5. TUYỆT ĐỐI không được bịa đặt thông tin. Nếu không có thông tin, hãy nói rõ là "Tôi không có thông tin về vấn đề này."
                    6. Nếu câu hỏi yêu cầu so sánh hoặc thống kê, hãy sử dụng dữ liệu để đưa ra câu trả lời chi tiết. Nếu cần, hãy tạo một biểu đồ để minh họa, nhưng TUYỆT ĐỐI không được tạo biểu đồ trừ khi được yêu cầu.

                    Câu hỏi của người dùng (từ ảnh): "{image_text}"
                    """
                    
                    with st.spinner("⏳ AI đang tìm kiếm và phân tích dữ liệu từ ảnh..."):
                        response = client_ai.chat.completions.create(
                            model="gpt-3.5-turbo",  # Có thể thay đổi model nếu cần
                            messages=[{"role": "user", "content": prompt_text}],
                            temperature=0.2,
                        )
                        ai_answer = response.choices[0].message.content
                        st.success("🤖 AI đã có câu trả lời:")
                        st.write(ai_answer)
                except Exception as e:
                    st.error(f"❌ Lỗi khi gọi API OpenAI: {e}. Vui lòng kiểm tra API key hoặc kết nối internet.")
            elif not found_qa_answer and not client_ai:
                st.warning("⚠️ Không có câu trả lời trong Sổ tay và chưa có OpenAI API key để xử lý. Vui lòng cấu hình API key.")
        else:
            st.warning("⚠️ Không thể trích xuất văn bản từ ảnh.")
            st.session_state.user_input_value = ""
    except Exception as e:
        st.error(f"❌ Lỗi trong quá trình xử lý ảnh: {e}")
    finally:
        if temp_image_path.exists():
            os.remove(temp_image_path)
