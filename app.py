import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.cm as cm # Thêm thư viện cm để tạo màu sắc
import re # Thêm thư thư viện regex để trích xuất tên sheet
import os # Import os for path handling
from pathlib import Path # Import Path for robust path handling

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

# Lấy API key OpenAI từ secrets (ĐÃ SỬA ĐỂ GÁN TRỰC TIẾP)
openai_api_key_direct = "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"


if openai_api_key_direct:
    client_ai = OpenAI(api_key=openai_api_key_direct)
    st.success("✅ Đã kết nối OpenAI API key.")
else:
    client_ai = None
    st.warning("⚠️ Chưa cấu hình API key OpenAI. Vui lòng thêm vào st.secrets.")

# Hàm để lấy dữ liệu từ một sheet cụ thể
def get_sheet_data(sheet_name):
    try:
        spreadsheet_url = "https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit"
        sheet = client.open_by_url(spreadsheet_url).worksheet(sheet_name)
        return sheet.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Không tìm thấy sheet '{sheet_name}'. Vui lòng kiểm tra tên sheet.")
        return None
    except Exception as e:
        st.error(f"❌ Lỗi khi mở Google Sheet '{sheet_name}': {e}")
        return None

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

    user_msg = st.text_input("Bạn muốn hỏi gì?", key="user_input")

    # Kiểm tra nếu nút "Gửi" được nhấn HOẶC người dùng đã nhập tin nhắn mới và nhấn Enter
    if st.button("Gửi") or (user_msg and user_msg != st.session_state.last_processed_user_msg):
        if user_msg: # Chỉ xử lý nếu có nội dung nhập vào
            st.session_state.last_processed_user_msg = user_msg # Cập nhật tin nhắn cuối cùng đã xử lý
            user_msg_lower = user_msg.lower()

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
                        st.subheader(f"Dữ liệu từ sheet 'Danh sách lãnh đạo xã, phường' {'cho ' + location_name.title() if location_name else ''}:")
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
                    line_match = re.search(r"đường dây\s+([a-zA-Z0-9\.]+)", user_msg_lower)
                    if line_match:
                        line_name = line_match.group(1).upper()

                    filtered_df_tba = df_tba
                    if line_name and 'Tên đường dây' in df_tba.columns:
                        filtered_df_tba = df_tba[df_tba['Tên đường dây'].astype(str).str.upper() == line_name]
                        
                        if filtered_df_tba.empty:
                            st.warning(f"⚠️ Không tìm thấy TBA nào cho đường dây '{line_name}'.")
                            st.dataframe(df_tba)
                    
                    if not filtered_df_tba.empty:
                        st.subheader(f"Dữ liệu từ sheet 'Tên các TBA' {'cho đường dây ' + line_name if line_name else ''}:")
                        st.dataframe(filtered_df_tba)
                    else:
                        st.warning("⚠️ Dữ liệu từ sheet 'Tên các TBA' rỗng.")
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
            elif "cbcnv" in user_msg_lower or "danh sách" in user_msg_lower or any(k in user_msg_lower for k in ["tổ", "phòng", "đội", "nhân viên", "nhân sự", "thông tin"]):
                records = get_sheet_data("CBCNV")
                if records:
                    df_cbcnv = pd.DataFrame(records)

                    person_name = None
                    name_match = re.search(r"(?:thông tin|của)\s+([a-zA-Z\s]+?)(?:\s+trong|\s+tổ|\s+phòng|\s+đội|\s+cbcnv|$)", user_msg_lower)
                    if name_match:
                        person_name = name_match.group(1).strip()

                    bo_phan = None
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
                            break

                    filtered_df = df_cbcnv
                    if person_name and 'Họ và tên' in df_cbcnv.columns:
                        filtered_df = filtered_df[filtered_df['Họ và tên'].astype(str).str.lower() == person_name.lower()]
                    
                    if bo_phan and 'Bộ phận công tác' in filtered_df.columns:
                        filtered_df = filtered_df[filtered_df['Bộ phận công tác'].str.lower().str.contains(bo_phan.lower(), na=False)]

                    if not filtered_df.empty:
                        st.subheader(f"Thông tin CBCNV {'của ' + person_name.title() if person_name else ''} {'thuộc ' + bo_phan.title() if bo_phan else ''}:")
                        reply_list = []
                        for idx, r in filtered_df.iterrows():
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

                        if "biểu đồ" in user_msg_lower or "báo cáo" in user_msg_lower:
                            if 'Bộ phận công tác' in filtered_df.columns and not filtered_df['Bộ phận công tác'].empty:
                                st.subheader("Biểu đồ số lượng nhân viên theo Bộ phận công tác")
                                bo_phan_counts = filtered_df['Bộ phận công tác'].value_counts()

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
                                st.warning("⚠️ Không tìm thấy cột 'Bộ phận công tác' hoặc dữ liệu rỗng để vẽ biểu đồ nhân sự.")
                    else:
                        st.warning("⚠️ Không tìm thấy dữ liệu phù hợp với yêu cầu của bạn. Vui lòng kiểm tra tên bộ phận hoặc từ khóa.")
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
                        st.write(response.choices[0].message.content)
                    except Exception as e:
                        st.error(f"❌ Lỗi khi gọi OpenAI: {e}. Vui lòng kiểm tra API key hoặc quyền truy cập mô hình.")
                else:
                    st.warning("⚠️ Không có API key OpenAI. Vui lòng thêm vào st.secrets để sử dụng chatbot cho các câu hỏi tổng quát.")
