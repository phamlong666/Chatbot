import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.cm as cm # Thêm thư viện cm để tạo màu sắc
import re # Thêm thư thư viện regex để trích xuất tên sheet
import os # Thêm thư viện os để kiểm tra đường dẫn tệp

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

# Lấy API key OpenAI từ secrets
openai_api_key = st.secrets.get("OPENAI_API_KEY")

client_ai = None
if openai_api_key:
    client_ai = OpenAI(api_key=openai_api_key)
else:
    st.warning("⚠️ Không tìm thấy API key OpenAI trong secrets. Một số chức năng có thể bị hạn chế.")

# --- Cấu hình giao diện Streamlit ---
st.set_page_config(layout="wide")

# Sidebar
with st.sidebar:
    # Sửa lỗi tải logo và giảm kích thước 50%
    logo_path = "logo_hinh_tron.jpg"
    if os.path.exists(logo_path):
        try:
            with open(logo_path, "rb") as f:
                logo_bytes = f.read()
            st.image(logo_bytes, caption="Logo Đội QLĐLKV Định Hóa", width=75) # Giảm width từ 150 xuống 75
        except Exception as e:
            st.error(f"❌ Lỗi khi đọc tệp logo: {e}")
    else:
        st.warning(f"⚠️ Không tìm thấy tệp logo tại đường dẫn: {logo_path}")

    st.title("🤖 Chatbot Đội QLĐLKV Định Hóa")
    st.write("Chào mừng bạn đến với trợ lý ảo của chúng tôi!")
    st.write("Bạn có thể hỏi về các vấn đề kỹ thuật, nghiệp vụ, nhân sự, hoặc các câu hỏi chung.")

# Hàm lấy dữ liệu từ Google Sheet
@st.cache_data(ttl=3600) # Cache dữ liệu trong 1 giờ
def get_sheet_data(sheet_name):
    try:
        spreadsheet = client.open("Data_DienLuc") # Tên bảng tính của bạn
        sheet = spreadsheet.worksheet(sheet_name)
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"❌ Lỗi khi truy cập sheet '{sheet_name}': {e}")
        return pd.DataFrame()

# Hàm xử lý câu hỏi về nhân sự
def handle_personnel_query(user_msg, df_cbcnv):
    # Trích xuất tên bộ phận hoặc từ khóa tìm kiếm từ tin nhắn người dùng
    # Ví dụ: "nhân sự tổ công tác", "số lượng người phòng kế hoạch"
    # Cải thiện regex để bắt các từ khóa như "tổ", "phòng", "đội", "ban" đi kèm với tên
    match = re.search(r'(nhân sự|số lượng người|thông tin người|ai là).*(tổ|phòng|đội|ban|bộ phận)\s*([a-zA-Z0-9\s_ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚŨƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼỀẾỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỰỲỴÝỶỸĐđ]+)', user_msg, re.IGNORECASE | re.UNICODE)
    department_keyword = None
    if match:
        department_keyword = match.group(3).strip()
        st.write(f"Đã phát hiện từ khóa bộ phận/tổ/ban: **{department_keyword}**")
    else:
        # Thử tìm các từ khóa chung hơn nếu không tìm thấy bộ phận cụ thể
        general_keywords = ["nhân sự", "người", "số lượng", "thông tin"]
        if any(kw in user_msg.lower() for kw in general_keywords):
            st.write("Đã phát hiện câu hỏi về nhân sự chung.")

    if df_cbcnv.empty:
        st.warning("⚠️ Dữ liệu CBCNV không khả dụng.")
        return

    if department_keyword:
        # Lọc theo bộ phận công tác, tìm kiếm một phần tên
        filtered_df = df_cbcnv[df_cbcnv['Bộ phận công tác'].str.contains(department_keyword, case=False, na=False)]
        if not filtered_df.empty:
            st.subheader(f"Thông tin nhân sự cho bộ phận/tổ/ban: {department_keyword}")
            st.dataframe(filtered_df)
            st.write(f"Tổng số nhân sự: **{len(filtered_df)}**")

            # Vẽ biểu đồ nếu có dữ liệu
            if 'Bộ phận công tác' in df_cbcnv.columns:
                department_counts = filtered_df['Bộ phận công tác'].value_counts()
                if not department_counts.empty:
                    fig, ax = plt.subplots(figsize=(10, 6))
                    department_counts.plot(kind='bar', ax=ax, color=cm.viridis(department_counts.index.factorize()[0]/len(department_counts)))
                    ax.set_title(f'Biểu đồ phân bổ nhân sự theo bộ phận cho "{department_keyword}"')
                    ax.set_xlabel('Bộ phận công tác')
                    ax.set_ylabel('Số lượng nhân sự')
                    plt.xticks(rotation=45, ha='right')
                    plt.tight_layout()
                    st.pyplot(fig, dpi=400) # Tăng DPI để biểu đồ nét hơn
                else:
                    st.warning("⚠️ Không tìm thấy cột 'Bộ phận công tác' hoặc dữ liệu rỗng để vẽ biểu đồ nhân sự.")
            else:
                st.warning("⚠️ Không tìm thấy dữ liệu phù hợp với yêu cầu của bạn. Vui lòng kiểm tra tên bộ phận hoặc từ khóa.")
        else:
            st.warning(f"⚠️ Không tìm thấy nhân sự nào thuộc bộ phận/tổ/ban có từ khóa: **{department_keyword}**.")
    else:
        st.subheader("Tổng quan nhân sự Đội QLĐLKV Định Hóa")
        st.dataframe(df_cbcnv)
        st.write(f"Tổng số nhân sự toàn đội: **{len(df_cbcnv)}**")

        # Vẽ biểu đồ tổng quan
        if 'Bộ phận công tác' in df_cbcnv.columns:
            department_counts = df_cbcnv['Bộ phận công tác'].value_counts()
            if not department_counts.empty:
                fig, ax = plt.subplots(figsize=(12, 7))
                # Sử dụng colormap để tạo màu sắc khác nhau cho mỗi cột
                colors = cm.viridis(department_counts.index.factorize()[0] / len(department_counts))
                department_counts.plot(kind='bar', ax=ax, color=colors)
                ax.set_title('Biểu đồ phân bổ nhân sự theo bộ phận')
                ax.set_xlabel('Bộ phận công tác')
                ax.set_ylabel('Số lượng nhân sự')
                plt.xticks(rotation=45, ha='right')
                plt.tight_layout()
                st.pyplot(fig, dpi=400) # Tăng DPI để biểu đồ nét hơn
            else:
                st.warning("⚠️ Không tìm thấy cột 'Bộ phận công tác' hoặc dữ liệu rỗng để vẽ biểu đồ nhân sự.")


# --- Main chat interface ---
st.title("💬 Trò chuyện với Trợ lý ảo")

# Khởi tạo lịch sử trò chuyện
if "messages" not in st.session_state:
    st.session_state.messages = []

# Hiển thị lịch sử trò chuyện
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Xử lý input từ người dùng
user_msg = st.chat_input("Bạn muốn hỏi gì?")
if user_msg:
    # Thêm tin nhắn người dùng vào lịch sử
    st.session_state.messages.append({"role": "user", "content": user_msg})
    with st.chat_message("user"):
        st.markdown(user_msg)

    with st.chat_message("assistant"):
        # Kiểm tra nếu câu hỏi liên quan đến nhân sự
        if any(keyword in user_msg.lower() for keyword in ["nhân sự", "người", "số lượng", "tổ", "phòng", "ban", "bộ phận", "ai là"]):
            df_cbcnv = get_sheet_data("CBCNV") # Tên sheet chứa dữ liệu CBCNV
            if not df_cbcnv.empty:
                handle_personnel_query(user_msg, df_cbcnv)
            else:
                st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet CBCNV.")

        # Xử lý các câu hỏi chung bằng OpenAI
        else:
            if client_ai:
                try:
                    response = client_ai.chat.completions.create(
                        # model="gpt-4o", # Kiểm tra lại quyền truy cập mô hình này
                        model="gpt-3.5-turbo", # Thử với gpt-3.5-turbo nếu gpt-4o không hoạt động
                        messages=[
                            {"role": "system", "content": "Bạn là trợ lý ảo của Đội QLĐLKV Định Hóa, chuyên hỗ trợ trả lời các câu hỏi kỹ thuật, nghiệp vụ, đoàn thể và cộng đồng liên quan đến ngành điện. Luôn cung cấp thông tin chính xác và hữu ích."},
                            {"role": "user", "content": user_msg}
                        ]
                    )
                    st.write(response.choices[0].message.content)
                except Exception as e:
                    st.error(f"❌ Lỗi khi gọi OpenAI: {e}. Vui lòng kiểm tra API key hoặc quyền truy cập mô hình.")
            else:
                st.warning("⚠️ Không có API key OpenAI. Vui lòng thêm vào st.secrets để sử dụng chức năng này.")

