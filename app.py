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
from datetime import datetime

# Cấu hình Streamlit page để sử dụng layout rộng
st.set_page_config(layout="wide")

# Cấu hình Matplotlib để hiển thị tiếng Việt và tăng độ nét chữ trục hoành
plt.rcParams['font.family'] = 'DejaVu Sans' # Hoặc 'Arial', 'Times New Roman' nếu có
plt.rcParams['font.size'] = 10
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['xtick.labelsize'] = 12 # Tăng cỡ chữ trục hoành để nét hơn
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
    if 'current_incident_df' not in st.session_state:
        st.session_state.current_incident_df = pd.DataFrame() # Để lưu trữ df sự cố hiện tại

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
                        st.warning(f"⚠️ Không thể truy xuất dữ liệu từ sheet '{sheet_name_from_query}'.")
                else:
                    st.warning("⚠️ Vui lòng cung cấp tên sheet rõ ràng. Ví dụ: 'lấy dữ liệu sheet DoanhThu'.")

            # Xử lý truy vấn liên quan đến sheet "Quản lý sự cố"
            elif "sự cố" in user_msg_lower or "quản lý sự cố" in user_msg_lower:
                records = get_sheet_data("Quản lý sự cố") # Tên sheet chính xác từ hình ảnh
                if records:
                    df_suco = pd.DataFrame(records)
                    
                    target_year = None
                    target_month = None

                    # Cố gắng trích xuất "tháng MM/YYYY" hoặc "tháng MM"
                    month_year_full_match = re.search(r"tháng\s+(\d{1,2})(?:/(\d{4}))?", user_msg_lower)
                    if month_year_full_match:
                        target_month = month_year_full_match.group(1)
                        target_year = month_year_full_match.group(2) # Có thể là None nếu chỉ có tháng

                    # Nếu năm chưa được trích xuất từ "tháng MM/YYYY", cố gắng trích xuất từ "năm"
                    if not target_year:
                        year_only_match = re.search(r"năm\s+(\d{4})", user_msg_lower)
                        if year_only_match:
                            target_year = year_only_match.group(1)

                    filtered_df_suco = df_suco.copy() # Make a copy to ensure independent filtering

                    # Kiểm tra sự tồn tại của cột 'Tháng/Năm sự cố' hoặc 'Tháng/Năm'
                    sheet_month_year_col = None
                    if 'Tháng/Năm sự cố' in df_suco.columns:
                        sheet_month_year_col = 'Tháng/Năm sự cố'
                    elif 'Tháng/Năm' in df_suco.columns: # Fallback to 'Tháng/Năm' if 'Tháng/Năm sự cố' not found
                        sheet_month_year_col = 'Tháng/Năm'
                    
                    if not sheet_month_year_col:
                        st.warning("⚠️ Không tìm thấy cột 'Tháng/Năm sự cố' hoặc 'Tháng/Năm' trong sheet 'Quản lý sự cố'. Không thể lọc theo tháng/năm.")
                    else:
                        # Convert the column to string type to avoid potential type issues during filtering
                        filtered_df_suco[sheet_month_year_col] = filtered_df_suco[sheet_month_year_col].astype(str)

                        # Thực hiện lọc dựa trên tháng và năm đã trích xuất
                        if target_month and target_year:
                            # Lọc chính xác theo định dạng "MM/YYYY"
                            exact_match_str = f"{int(target_month):02d}/{target_year}"
                            filtered_df_suco = filtered_df_suco[filtered_df_suco[sheet_month_year_col] == exact_match_str]
                        elif target_month:
                            # Lọc theo tiền tố tháng "MM/"
                            month_prefix = f"{int(target_month):02d}/"
                            filtered_df_suco = filtered_df_suco[filtered_df_suco[sheet_month_year_col].str.startswith(month_prefix)]
                        elif target_year:
                            # Lọc theo hậu tố năm "/YYYY"
                            year_suffix = f"/{target_year}"
                            filtered_df_suco = filtered_df_suco[filtered_df_suco[sheet_month_year_col].str.endswith(year_suffix)]

                    # Lưu DataFrame sự cố hiện tại vào session_state để dùng cho nút so sánh
                    st.session_state.current_incident_df = filtered_df_suco.copy()
                    st.session_state.current_target_month = target_month
                    st.session_state.current_target_year = target_year
                    st.session_state.current_sheet_month_year_col = sheet_month_year_col


                    if filtered_df_suco.empty:
                        st.warning(f"⚠️ Không tìm thấy sự cố nào {'trong tháng ' + target_month if target_month else ''} {'năm ' + target_year if target_year else ''}.")
                    
                    if not filtered_df_suco.empty:
                        subheader_text = "Dữ liệu từ sheet 'Quản lý sự cố'"
                        if target_month and target_year:
                            subheader_text += f" tháng {int(target_month):02d} năm {target_year}"
                        elif target_year:
                            subheader_text += f" năm {target_year}"
                        elif target_month:
                            subheader_text += f" tháng {int(target_month):02d}"
                        
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
                                    if not filtered_df_suco[col].empty and not filtered_df_suco[col].isnull().all(): # Kiểm tra dữ liệu không rỗng hoặc toàn bộ NaN
                                        st.subheader(f"Biểu đồ số lượng sự cố theo '{col}'")
                                        
                                        # Đếm số lượng các giá trị duy nhất trong cột
                                        counts = filtered_df_suco[col].value_counts()

                                        fig, ax = plt.subplots(figsize=(12, 7))
                                        colors = cm.get_cmap('tab10', len(counts.index))
                                        
                                        # Chuyển đổi index sang list of strings để đảm bảo tương thích với Matplotlib
                                        x_labels = [str(item) for item in counts.index]
                                        y_values = counts.values
                                        
                                        bars = ax.bar(x_labels, y_values, color=colors.colors) # Sử dụng x_labels đã chuyển đổi

                                        for bar in bars:
                                            yval = bar.get_height()
                                            ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, round(yval), ha='center', va='bottom', color='black')

                                        ax.set_xlabel(col)
                                        ax.set_ylabel("Số lượng sự cố")
                                        ax.set_title(f"Biểu đồ số lượng sự cố theo {col}")
                                        plt.xticks(rotation=45, ha='right')
                                        plt.tight_layout()
                                        st.pyplot(fig, dpi=400)
                                    else:
                                        st.warning(f"⚠️ Cột '{col}' không có dữ liệu để vẽ biểu đồ.")
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
                        # asType(str) để đảm bảo cột là kiểu chuỗi trước khi dùng str.lower()
                        filtered_df_lanhdao = df_lanhdao[df_lanhdao['Thuộc xã/phường'].astype(str).str.lower().str.contains(location_name.lower(), na=False)]
                        
                        if filtered_df_lanhdao.empty:
                            st.warning(f"⚠️ Không tìm thấy lãnh đạo nào cho '{location_name.title()}'.")
                            st.dataframe(df_lanhdao) # Vẫn hiển thị toàn bộ dữ liệu nếu không tìm thấy kết quả lọc
                    
                    if not filtered_df_lanhdao.empty:
                        st.subheader(f"Dữ liệu từ sheet 'Danh sách lãnh đạo xã, phường' {'cho ' + location_name.title() if location_name else ''}:")
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
                    line_match = re.search(r"đường dây\s+([a-zA-Z0-9\.]+)", user_msg_lower)
                    if line_match:
                        line_name = line_match.group(1).upper() # Lấy tên đường dây và chuyển thành chữ hoa để khớp

                    filtered_df_tba = df_tba
                    if line_name and 'Tên đường dây' in df_tba.columns:
                        # Lọc DataFrame theo tên đường dây
                        filtered_df_tba = df_tba[df_tba['Tên đường dây'].astype(str).str.upper() == line_name]
                        
                        if filtered_df_tba.empty:
                            st.warning(f"⚠️ Không tìm thấy TBA nào cho đường dây '{line_name}'.")
                            st.dataframe(df_tba) # Vẫn hiển thị toàn bộ dữ liệu nếu không tìm thấy kết quả lọc
                    
                    if not filtered_df_tba.empty:
                        st.subheader(f"Dữ liệu từ sheet 'Tên các TBA' {'cho đường dây ' + line_name if line_name else ''}:")
                        st.dataframe(filtered_df_tba) # Hiển thị dữ liệu đã lọc hoặc toàn bộ
                        
                        # Bạn có thể thêm logic vẽ biểu đồ cho TBA tại đây nếu cần
                        # Ví dụ: if "biểu đồ" in user_msg_lower: ...
                    else:
                        st.warning("⚠️ Dữ liệu từ sheet 'Tên các TBA' rỗng.")
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
                                
                                # Vẽ biểu đồ cột với màu sắc riêng cho từng cột
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
            elif "cbcnv" in user_msg_lower or "danh sách" in user_msg_lower or any(k in user_msg_lower for k in ["tổ", "phòng", "đội", "nhân viên", "nhân sự", "thông tin"]):
                records = get_sheet_data("CBCNV") # Tên sheet CBCNV
                if records:
                    df_cbcnv = pd.DataFrame(records) # Chuyển đổi thành DataFrame

                    person_name = None
                    bo_phan = None
                    is_specific_query = False # Flag để kiểm tra nếu có yêu cầu tìm kiếm cụ thể

                    # Regex để bắt tên người sau "thông tin" hoặc "của" và trước các từ khóa khác hoặc kết thúc chuỗi
                    name_match = re.search(r"(?:thông tin|của)\s+([a-zA-Z\s]+?)(?:\s+trong|\s+tổ|\s+phòng|\s+đội|\s+cbcnv|$)", user_msg_lower)
                    if name_match:
                        person_name = name_match.group(1).strip()
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

                    filtered_df = pd.DataFrame() # Khởi tạo DataFrame rỗng cho kết quả lọc

                    if person_name and 'Họ và tên' in df_cbcnv.columns:
                        # Thử tìm kiếm chính xác theo tên
                        filtered_df = df_cbcnv[df_cbcnv['Họ và tên'].astype(str).str.lower() == person_name.lower()]
                        
                        if filtered_df.empty:
                            # Nếu không tìm thấy chính xác, thử tìm kiếm gần đúng
                            st.info(f"Không tìm thấy chính xác '{person_name.title()}'. Đang tìm kiếm gần đúng...")
                            filtered_df = df_cbcnv[df_cbcnv['Họ và tên'].astype(str).str.lower().str.contains(person_name.lower(), na=False)]
                            
                            if filtered_df.empty:
                                st.warning(f"⚠️ Không tìm thấy người nào có tên '{person_name.title()}' hoặc tên gần giống.")
                                # filtered_df vẫn rỗng ở đây
                        
                        # Nếu tìm thấy tên (chính xác hoặc gần đúng) và có bộ phận được chỉ định, lọc thêm
                        if not filtered_df.empty and bo_phan and 'Bộ phận công tác' in filtered_df.columns:
                            initial_filtered_count = len(filtered_df)
                            filtered_df = filtered_df[filtered_df['Bộ phận công tác'].str.lower().str.contains(bo_phan.lower(), na=False)]
                            if filtered_df.empty and initial_filtered_count > 0:
                                st.warning(f"⚠️ Không tìm thấy kết quả cho bộ phận '{bo_phan.title()}' trong danh sách đã lọc theo tên.")
                    
                    elif bo_phan and 'Bộ phận công tác' in df_cbcnv.columns:
                        # Nếu chỉ có bộ phận được chỉ định (không có tên người)
                        filtered_df = df_cbcnv[df_cbcnv['Bộ phận công tác'].str.lower().str.contains(bo_phan.lower(), na=False)]
                        if filtered_df.empty:
                            st.warning(f"⚠️ Không tìm thấy dữ liệu cho bộ phận '{bo_phan.title()}'.")
                    
                    # Logic hiển thị kết quả
                    if not filtered_df.empty:
                        subheader_parts = ["Thông tin CBCNV"]
                        if person_name: # Chỉ thêm nếu person_name có giá trị
                            subheader_parts.append(f"của {person_name.title()}")
                        if bo_phan: # Chỉ thêm nếu bo_phan có giá trị
                            subheader_parts.append(f"thuộc {bo_phan.title()}")
                        
                        st.subheader(" ".join(subheader_parts) + ":")
                        
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

                        # --- Bổ sung logic vẽ biểu đồ CBCNV ---
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
                        # Nếu filtered_df rỗng sau tất cả các bước lọc
                        # Chỉ hiển thị toàn bộ danh sách nếu không có yêu cầu cụ thể nào được tìm thấy
                        if not is_specific_query or "toàn bộ" in user_msg_lower or "tất cả" in user_msg_lower or "danh sách" in user_msg_lower:
                            st.subheader("Toàn bộ thông tin CBCNV:")
                            st.dataframe(df_cbcnv)
                        else:
                            st.warning("⚠️ Không tìm thấy dữ liệu phù hợp với yêu cầu của bạn.")
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

    # --- Nút "So sánh cùng kỳ" (đặt ngoài khối if user_msg để luôn hiển thị) ---
    if not st.session_state.current_incident_df.empty and (st.session_state.current_target_month or st.session_state.current_target_year):
        if st.button("So sánh cùng kỳ"):
            current_df = st.session_state.current_incident_df
            current_month = st.session_state.current_target_month
            current_year = st.session_state.current_target_year
            sheet_month_year_col = st.session_state.current_sheet_month_year_col

            if current_month and current_year:
                try:
                    # Tính toán kỳ trước (cùng tháng năm trước)
                    prev_year_date = datetime(int(current_year), int(current_month), 1)
                    prev_year_date = prev_year_date.replace(year=prev_year_date.year - 1)
                    prev_month = f"{prev_year_date.month:02d}"
                    prev_year = str(prev_year_date.year)
                    
                    st.info(f"Đang so sánh với dữ liệu tháng {prev_month} năm {prev_year}.")

                    # Lấy toàn bộ dữ liệu sự cố để lọc kỳ trước
                    all_suco_records = get_sheet_data("Quản lý sự cố")
                    if all_suco_records:
                        df_all_suco = pd.DataFrame(all_suco_records)
                        df_all_suco[sheet_month_year_col] = df_all_suco[sheet_month_year_col].astype(str)

                        prev_period_match_str = f"{prev_month}/{prev_year}"
                        df_prev_period = df_all_suco[df_all_suco[sheet_month_year_col] == prev_period_match_str]

                        if not df_prev_period.empty:
                            st.subheader(f"So sánh sự cố tháng {current_month}/{current_year} và tháng {prev_month}/{prev_year}:")
                            
                            chart_columns_for_comparison = []
                            # Lấy các cột biểu đồ từ yêu cầu ban đầu của người dùng (nếu có)
                            user_msg_lower = st.session_state.last_processed_user_msg.lower()
                            if "đường dây" in user_msg_lower and 'Đường dây' in current_df.columns:
                                chart_columns_for_comparison.append('Đường dây')
                            if "tính chất" in user_msg_lower and 'Tính chất' in current_df.columns:
                                chart_columns_for_comparison.append('Tính chất')
                            if "loại sự cố" in user_msg_lower and 'Loại sự cố' in current_df.columns:
                                chart_columns_for_comparison.append('Loại sự cố')

                            if chart_columns_for_comparison:
                                for col in chart_columns_for_comparison:
                                    if col in current_df.columns and col in df_prev_period.columns:
                                        st.subheader(f"Biểu đồ so sánh số lượng sự cố theo '{col}'")
                                        
                                        counts_current = current_df[col].value_counts().rename(f'{current_month}/{current_year}')
                                        counts_prev = df_prev_period[col].value_counts().rename(f'{prev_month}/{prev_year}')
                                        
                                        # Kết hợp dữ liệu của 2 kỳ
                                        combined_counts = pd.concat([counts_current, counts_prev], axis=1).fillna(0)
                                        
                                        fig, ax = plt.subplots(figsize=(14, 8))
                                        combined_counts.plot(kind='bar', ax=ax, width=0.8) # Vẽ biểu đồ cột nhóm
                                        
                                        # Thêm giá trị lên trên các cột
                                        for container in ax.containers:
                                            ax.bar_label(container, fmt='%d', label_type='edge', fontsize=9, color='black')

                                        ax.set_xlabel(col)
                                        ax.set_ylabel("Số lượng sự cố")
                                        ax.set_title(f"So sánh số lượng sự cố theo {col} ({current_month}/{current_year} vs {prev_month}/{prev_year})")
                                        plt.xticks(rotation=45, ha='right')
                                        plt.tight_layout()
                                        st.pyplot(fig, dpi=400)
                                    else:
                                        st.warning(f"⚠️ Cột '{col}' không tồn tại trong dữ liệu của một trong hai kỳ để so sánh.")
                            else:
                                st.warning("⚠️ Không có cột nào được chỉ định để so sánh biểu đồ. Vui lòng thêm 'và vẽ biểu đồ theo [cột]' vào câu hỏi ban đầu.")

                        else:
                            st.warning(f"⚠️ Không tìm thấy dữ liệu sự cố cho tháng {prev_month} năm {prev_year} để so sánh.")
                    else:
                        st.warning("⚠️ Không thể truy xuất dữ liệu sự cố cho kỳ trước.")
                else:
                    st.warning("⚠️ Không thể lấy dữ liệu sự cố để so sánh.")
            else:
                st.warning("⚠️ Vui lòng cung cấp tháng và năm cụ thể trong câu hỏi ban đầu để có thể so sánh cùng kỳ.")
