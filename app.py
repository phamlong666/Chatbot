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
        encrypted_gdrive_key = st.secrets["gdrive_service_account"].get("gdrive_key")
        
        if encryption_key_for_decryption and encrypted_gdrive_key:
            cipher_suite = Fernet(encryption_key_for_decryption.encode())
            decrypted_key = cipher_suite.decrypt(encrypted_gdrive_key.encode()).decode()
            
            creds_json = json.loads(decrypted_key)
            creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
            gc = gspread.authorize(creds)
            
            st.session_state.gc = gc
    except Exception as e:
        st.error(f"❌ Lỗi: Không thể kết nối đến Google Sheets. Vui lòng kiểm tra lại cấu hình. Chi tiết lỗi: {e}")

# Kết nối OpenAI
if "openai_api_key" in st.secrets:
    try:
        st.session_state.client = OpenAI(api_key=st.secrets["openai_api_key"])
    except Exception as e:
        st.error(f"❌ Lỗi: Không thể kết nối đến OpenAI. Vui lòng kiểm tra lại API Key. Chi tiết lỗi: {e}")

# ID của Google Sheet
SHEET_ID = "15i27J_g1x1oXfO_H2-59zX64B4DqV9D6F5Q7hQ"


# --- CÁC HÀM HỖ TRỢ ---
def get_sheet_data(sheet_name):
    try:
        gc = st.session_state.get('gc')
        if gc is None:
            st.warning("⚠️ Không thể kết nối Google Sheets. Vui lòng thử lại sau.")
            return None
        
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.worksheet(sheet_name)
        data = worksheet.get_all_values()
        return data
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Lỗi: Không tìm thấy sheet có tên '{sheet_name}'.")
        return None
    except Exception as e:
        st.error(f"❌ Lỗi khi lấy dữ liệu từ sheet '{sheet_name}'. Chi tiết: {e}")
        return None

def find_column_name(df, possible_names):
    for name in possible_names:
        if name in df.columns:
            return name
    return None

def clean_text(text):
    if text is None:
        return ""
    text = re.sub(r'[\s\W_]+', ' ', text)  # Loại bỏ ký tự đặc biệt và dấu gạch dưới
    return text.strip().lower()

def get_most_similar_question(user_question, qa_data):
    user_q = clean_text(user_question)
    
    questions = [clean_text(item['Câu hỏi']) for item in qa_data]
    
    if not questions:
        return None
        
    best_match = get_close_matches(user_q, questions, n=1, cutoff=0.6)
    
    if best_match:
        index = questions.index(best_match[0])
        return qa_data[index]
    
    return None

def extract_text_from_image(image_path):
    reader = easyocr.Reader(['vi'])
    result = reader.readtext(image_path, detail=0)
    text = " ".join(result)
    return text

def normalize_text(text):
    # Chuyển đổi thành chữ thường và loại bỏ dấu tiếng Việt để so sánh chính xác hơn
    # Dùng regex để loại bỏ dấu
    text = text.lower()
    text = re.sub(r'[àáạảã]', 'a', text)
    text = re.sub(r'[èéẹẻẽ]', 'e', text)
    text = re.sub(r'[ìíịỉĩ]', 'i', text)
    text = re.sub(r'[òóọỏõ]', 'o', text)
    text = re.sub(r'[ùúụủũ]', 'u', text)
    text = re.sub(r'[ỳýỵỷỹ]', 'y', text)
    text = re.sub(r'[đ]', 'd', text)
    text = re.sub(r'[^a-z0-9\s]', '', text)
    return text

def display_full_answer(qa_item):
    st.markdown(f"**Câu hỏi:** {qa_item['Câu hỏi']}")
    st.markdown("---")
    st.markdown(f"**Nội dung chi tiết:**\n{qa_item['Câu trả lời']}")
    
    # Hiển thị các câu hỏi tương tự nếu có
    if 'SimilarQuestions' in qa_item and qa_item['SimilarQuestions']:
        with st.expander("Các câu hỏi tương tự"):
            for q in qa_item['SimilarQuestions']:
                st.write(f"- {q}")

# --- XỬ LÝ CHÍNH TRONG APP ---
st.title("🤖 HỆ THỐNG TRỢ LÝ ẢO NỘI BỘ")

# Khởi tạo session state
if "qa_results" not in st.session_state:
    st.session_state.qa_results = []
if "current_qa_display" not in st.session_state:
    st.session_state.current_qa_display = 0
if "user_input_value" not in st.session_state:
    st.session_state.user_input_value = ""

# Load data Question-Answer
qa_sheet_data = get_sheet_data("QA")
if qa_sheet_data:
    st.session_state.qa_data = [
        {'Câu hỏi': row[0], 'Câu trả lời': row[1]} for row in qa_sheet_data[1:]
    ]

# Giao diện nhập liệu
st.markdown("### 💬 Nhập câu hỏi của bạn")
user_input = st.text_area(
    "Gõ câu hỏi vào đây...",
    key="user_input_key",
    value=st.session_state.user_input_value,
    placeholder="Ví dụ: Lấy thông tin KPI của các đơn vị tháng 6 năm 2025 và sắp xếp theo thứ tự giảm dần"
)

col1, col2 = st.columns([1, 1])

with col1:
    if st.button("Gửi câu hỏi", use_container_width=True, type="primary"):
        st.session_state.user_input_value = user_input
        st.session_state.qa_results = []
        if user_input:
            # Xử lý các câu hỏi đặc biệt có đồ thị
            normalized_user_msg = normalize_text(user_input)
            is_handled = False
            
            # --- ĐOẠN MÃ XỬ LÝ CÂU HỎI VÀ TẠO BIỂU ĐỒ ---
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
                        # Chuyển đổi cột KPI, Năm, Tháng sang dạng số, thay thế lỗi bằng NaN
                        df[kpi_col] = pd.to_numeric(df[kpi_col], errors='coerce')
                        df[nam_col] = pd.to_numeric(df[nam_col], errors='coerce')
                        df[thang_col] = pd.to_numeric(df[thang_col], errors='coerce')
                        
                        # Điền giá trị NaN bằng 0 để có thể hiển thị trên biểu đồ
                        df[kpi_col].fillna(0, inplace=True)

                        # Lọc dữ liệu
                        df_filtered = df[(df[nam_col] == 2025) & (df[thang_col] == 6)]
                        
                        # Sắp xếp theo thứ tự giảm dần
                        df_sorted = df_filtered.sort_values(by=kpi_col, ascending=False)
                        df_sorted = df_sorted[[donvi_col, kpi_col]].reset_index(drop=True)
                        
                        st.subheader("Bảng điểm KPI của các đơn vị tháng 6 năm 2025")
                        st.dataframe(df_sorted)

                        # Vẽ biểu đồ
                        plt.figure(figsize=(12, 6))
                        sns.barplot(x=df_sorted[donvi_col], y=df_sorted[kpi_col], palette="viridis")
                        plt.title("Biểu đồ KPI tháng 6 năm 2025 theo đơn vị")
                        plt.xlabel("Đơn vị")
                        plt.ylabel("Điểm KPI")
                        plt.xticks(rotation=45, ha='right')
                        plt.tight_layout()
                        st.pyplot(plt)
                    else:
                        st.warning("❗ Không tìm thấy các cột cần thiết ('Năm', 'Tháng', 'Đơn vị', 'Điểm KPI') trong sheet KPI.")
                else:
                    st.warning("❗ Sheet 'KPI' không có dữ liệu hoặc không thể đọc được.")
                is_handled = True
            
            # --- XỬ LÝ SỰ CỐ THEO LOẠI SỰ CỐ ---
            if "lấy thông tin sự cố năm 2025 so sánh với cùng kỳ" in normalized_user_msg and "loại sự cố" in normalized_user_msg:
                sheet_name = "Quản lý sự cố"
                sheet_data = get_sheet_data(sheet_name)
                if sheet_data:
                    df = pd.DataFrame(sheet_data)
                    nam_col = find_column_name(df, ['Năm'])
                    thang_col = find_column_name(df, ['Tháng'])
                    loai_col = find_column_name(df, ['Loại sự cố'])  # cột E

                    if nam_col and thang_col and loai_col:
                        df[nam_col] = pd.to_numeric(df[nam_col], errors='coerce')
                        df[thang_col] = pd.to_numeric(df[thang_col], errors='coerce')

                        df_filtered = df[df[nam_col].isin([2024, 2025])]
                        df_grouped = df_filtered.groupby([nam_col, loai_col]).size().reset_index(name='Số sự cố')

                        st.subheader("📊 So sánh số sự cố theo loại sự cố (năm 2025 và cùng kỳ 2024)")
                        st.dataframe(df_grouped)

                        plt.figure(figsize=(12, 6))
                        sns.barplot(data=df_grouped, x='Số sự cố', y=loai_col, hue=nam_col, palette='viridis', orient='h')
                        plt.title('Số sự cố theo loại sự cố (2025 và cùng kỳ 2024)')
                        plt.xlabel('Số lượng sự cố')
                        plt.ylabel('Loại sự cố')
                        plt.tight_layout()
                        st.pyplot(plt)
                    else:
                        st.warning("❗ Không tìm thấy các cột cần thiết ('Năm', 'Tháng', 'Loại sự cố') trong sheet Quản lý sự cố.")
                else:
                    st.warning("❗ Sheet 'Quản lý sự cố' không có dữ liệu hoặc không thể đọc được.")
                is_handled = True

            # --- CBCNV: Biểu đồ theo trình độ chuyên môn ---
            if "cbcnv" in normalized_user_msg and "trình độ chuyên môn" in normalized_user_msg:
                sheet_name = "CBCNV"
                sheet_data = get_sheet_data(sheet_name)
                if sheet_data:
                    df = pd.DataFrame(sheet_data)
                    trinhdo_col = find_column_name(df, ['Trình độ chuyên môn', 'Trình độ', 'Trinh do'])

                    if trinhdo_col:
                        df_grouped = df[trinhdo_col].value_counts().reset_index()
                        df_grouped.columns = ['Trình độ chuyên môn', 'Số lượng']
                        
                        st.subheader("📊 Phân bố CBCNV theo trình độ chuyên môn")
                        st.dataframe(df_grouped)
                        
                        # Biểu đồ cột
                        plt.figure(figsize=(12, 6))
                        sns.barplot(data=df_grouped, x='Số lượng', y='Trình độ chuyên môn', palette='crest', orient='h')
                        plt.title("Phân bố CBCNV theo trình độ chuyên môn")
                        plt.xlabel("Số lượng")
                        plt.ylabel("Trình độ chuyên môn")
                        st.pyplot(plt)
                        
                        # Biểu đồ hình tròn
                        plt.figure(figsize=(8, 8))
                        plt.pie(
                            df_grouped['Số lượng'], 
                            labels=df_grouped['Trình độ chuyên môn'], 
                            autopct='%1.1f%%', 
                            startangle=140, 
                            colors=sns.color_palette("Set2")
                        )
                        plt.title("Tỷ lệ CBCNV theo trình độ chuyên môn")
                        plt.tight_layout()
                        st.pyplot(plt)
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

                        # Biểu đồ cột
                        plt.figure(figsize=(8, 5))
                        ax = sns.barplot(data=df_grouped, x='Nhóm tuổi', y='Số lượng', palette='flare')
                        plt.title("Phân bố CBCNV theo độ tuổi")
                        for p in ax.patches:
                            ax.annotate(f'{int(p.get_height())}', (p.get_x() + p.get_width() / 2., p.get_height()),
                                        ha='center', va='center', fontsize=12, color='black', xytext=(0, 5),
                                        textcoords='offset points')
                        st.pyplot(plt)
                        
                        # Biểu đồ hình tròn
                        plt.figure(figsize=(8, 8))
                        plt.pie(
                            df_grouped['Số lượng'],
                            labels=df_grouped['Nhóm tuổi'],
                            autopct='%1.1f%%',
                            startangle=140,
                            colors=sns.color_palette("Set3")
                        )
                        plt.title("Tỷ lệ CBCNV theo độ tuổi")
                        plt.tight_layout()
                        st.pyplot(plt)
                    else:
                        st.warning("❗ Không tìm thấy cột 'Độ tuổi' trong sheet CBCNV")
                else:
                    st.warning("❗ Sheet 'CBCNV' không có dữ liệu hoặc không thể đọc được.")
                is_handled = True

            # Nếu không phải câu hỏi có biểu đồ, xử lý bằng QA
            if not is_handled:
                qa_item = get_most_similar_question(user_input, st.session_state.qa_data)
                
                if qa_item:
                    st.session_state.qa_results = [qa_item]
                    st.session_state.current_qa_display = 0
                else:
                    st.warning("❗ Tôi không tìm thấy câu trả lời trực tiếp cho câu hỏi của bạn. Vui lòng thử lại với một câu hỏi khác.")
                    st.session_state.qa_results = []
                    st.session_state.current_qa_display = 0
        else:
            st.warning("❗ Vui lòng nhập câu hỏi.")

# Hiển thị kết quả QA
if st.session_state.qa_results:
    st.subheader("🔔 Kết quả tìm kiếm")
    display_full_answer(st.session_state.qa_results[st.session_state.current_qa_display])
    
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
