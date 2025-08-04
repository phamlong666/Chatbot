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

    # Đọc câu hỏi mẫu từ file sample_questions = []
    try:
        with open("sample_questions.json", "r", encoding="utf-8") as f:
            sample_questions = json.load(f)
    except Exception as e:
        st.warning(f"Không thể đọc file câu hỏi mẫu: {e}")

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

    # Xử lý khi người dùng nhấn nút "Gửi"
    if send_button_pressed:
        user_msg = st.session_state.user_input_value
        if user_msg and user_msg != st.session_state.last_processed_user_msg:
            st.session_state.last_processed_user_msg = user_msg # Cập nhật tin nhắn đã xử lý cuối cùng
            
            # Xử lý các câu hỏi liên quan đến biểu đồ KPI
            if "biểu đồ" in normalize_text(user_msg) or "thống kê" in normalize_text(user_msg) or "kpi" in normalize_text(user_msg):
                with st.spinner("⏳ Đang tạo biểu đồ..."):
                    kpi_data = get_sheet_data("KPI")
                    if kpi_data:
                        try:
                            kpi_df = pd.DataFrame(kpi_data)
                            st.subheader("📈 Biểu đồ KPI")
                            
                            # Chuyển đổi cột "Ngày" sang datetime để sắp xếp
                            kpi_df['Ngày'] = pd.to_datetime(kpi_df['Ngày'], format='%d/%m/%Y', errors='coerce')
                            kpi_df = kpi_df.sort_values(by='Ngày')
                            
                            # Chuyển đổi các cột số
                            for col in ['Số vụ', 'Số tiền']:
                                kpi_df[col] = pd.to_numeric(kpi_df[col].astype(str).str.replace(',', ''), errors='coerce')
                            
                            # Tạo layout 2 cột cho biểu đồ
                            chart_col1, chart_col2 = st.columns(2)
                            
                            with chart_col1:
                                fig_vu, ax_vu = plt.subplots(figsize=(10, 6))
                                ax_vu.bar(kpi_df['Ngày'], kpi_df['Số vụ'], color='skyblue')
                                ax_vu.set_title("Số vụ theo ngày")
                                ax_vu.set_xlabel("Ngày")
                                ax_vu.set_ylabel("Số vụ")
                                ax_vu.tick_params(axis='x', rotation=45)
                                ax_vu.grid(axis='y', linestyle='--', alpha=0.7)
                                st.pyplot(fig_vu)
                            
                            with chart_col2:
                                # Tạo biểu đồ cột cho "Số tiền" với màu gradient
                                fig_tien, ax_tien = plt.subplots(figsize=(10, 6))
                                # Tạo màu gradient
                                colors = cm.viridis(np.linspace(0, 1, len(kpi_df['Số tiền'])))
                                ax_tien.bar(kpi_df['Ngày'], kpi_df['Số tiền'], color=colors)
                                ax_tien.set_title("Tổng số tiền theo ngày")
                                ax_tien.set_xlabel("Ngày")
                                ax_tien.set_ylabel("Số tiền (triệu đồng)")
                                ax_tien.tick_params(axis='x', rotation=45)
                                ax_tien.grid(axis='y', linestyle='--', alpha=0.7)
                                # Định dạng y-axis
                                ax_tien.get_yaxis().set_major_formatter(
                                    plt.FuncFormatter(lambda x, p: format(int(x), ','))
                                )
                                st.pyplot(fig_tien)
                            
                        except Exception as e:
                            st.error(f"❌ Lỗi khi tạo biểu đồ: {e}")
                    else:
                        st.info("⚠️ Không có dữ liệu KPI để tạo biểu đồ.")

            # Xử lý các câu hỏi thông thường bằng fuzzy search
            with st.spinner('⏳ Đang tìm kiếm câu trả lời...'):
                best_match = None
                highest_score = 0
                
                # Iterate through all QA entries
                for index, row in qa_df.iterrows():
                    question = normalize_text(row['Câu hỏi'])
                    score = fuzz.ratio(normalize_text(user_msg), question)
                    
                    if score > highest_score:
                        highest_score = score
                        best_match = row

                # Chỉ hiển thị nếu độ khớp cao hơn ngưỡng chấp nhận
                if highest_score >= 80: # Ngưỡng 80 là hợp lý cho tiếng Việt
                    
                    # Lọc tất cả các câu trả lời tương tự (cùng độ khớp cao nhất)
                    # Điều này để xử lý trường hợp có nhiều câu hỏi tương tự với cùng một câu trả lời
                    st.session_state.qa_results = []
                    
                    for index, row in qa_df.iterrows():
                        question = normalize_text(row['Câu hỏi'])
                        score = fuzz.ratio(normalize_text(user_msg), question)
                        
                        if score == highest_score:
                            st.session_state.qa_results.append(row['Câu trả lời'])
                    
                    # Reset index và hiển thị câu trả lời đầu tiên
                    st.session_state.qa_index = 0
                    st.session_state.current_qa_display = st.session_state.qa_results[st.session_state.qa_index]
                    st.session_state.qa_index += 1
                
                    st.rerun() # Rerun để cập nhật giao diện
                else:
                    # Nếu không tìm thấy câu hỏi tương tự trong sheet "Hỏi-Trả lời", sử dụng OpenAI
                    if client_ai:
                        with st.spinner("⏳ Không tìm thấy câu trả lời trong Sổ tay, đang hỏi AI..."):
                            try:
                                # Tạo một prompt đơn giản
                                prompt = f"Dựa trên câu hỏi sau, hãy trả lời một cách ngắn gọn, súc tích và chỉ tập trung vào thông tin cần thiết: '{user_msg}'"
                                response = client_ai.chat.completions.create(
                                    model="gpt-3.5-turbo",
                                    messages=[{"role": "user", "content": prompt}]
                                )
                                # Xử lý và hiển thị phản hồi từ OpenAI
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

    # Xử lý khi người dùng nhấn nút "Xóa"
    if clear_button_pressed:
        st.session_state.user_input_value = ""
        st.session_state.qa_results = []
        st.session_state.qa_index = 0
        st.session_state.current_qa_display = ""
        st.session_state.audio_processed = False # Reset trạng thái audio
        st.rerun()

    # Hiển thị kết quả tìm kiếm từ Google Sheets
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

    # --- Tải ảnh chứa câu hỏi ---
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
                st.warning("⚠️ Không thể trích xuất văn bản từ ảnh. Vui lòng thử lại với ảnh khác rõ hơn.")
        except Exception as e:
            st.error(f"❌ Lỗi khi xử lý ảnh: {e}")
        finally:
            if temp_image_path.exists():
                os.remove(temp_image_path)
