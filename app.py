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
from fuzzywuzzy import fuzz # Import fuzzywuzzy để so sánh chuỗi

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
openai_api_key_direct = "sk-proj-3SkFtE-6W2yUYFL2wj3kxlD6epI7ZIeDaInlwYfjwLjBzbr4jC02GkQEqZ1CwlAxRIrv7ivq0T3BlbkFJEQxDvv9kGtpJ5an9AZGMJpftDxMx-u21snU1qiqLitRmqzyakhkRKO366_xZqczo4Ghw3JoeoA"


if openai_api_key_direct:
    client_ai = OpenAI(api_key=openai_api_key_direct)
    st.success("✅ Đã kết nối OpenAI API key.")
else:
    client_ai = None
    # Đã sửa lỗi: Xóa ký tự emoji '⚠️' vì gây lỗi SyntaxError
    st.warning("Chưa cấu hình API key OpenAI. Vui lòng thêm vào st.secrets.")

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

# Hàm chuẩn hóa chuỗi để so sánh chính xác hơn (loại bỏ dấu cách thừa, chuyển về chữ thường)
def normalize_text(text):
    if isinstance(text, str):
        # Chuyển về chữ thường, loại bỏ dấu cách thừa ở đầu/cuối và thay thế nhiều dấu cách bằng một dấu cách
        return re.sub(r'\s+', ' ', text).strip().lower()
    return ""

# Tải dữ liệu từ sheet "Hỏi-Trả lời" một lần khi ứng dụng khởi động
qa_data = get_sheet_data("Hỏi-Trả lời")
qa_df = pd.DataFrame(qa_data) if qa_data else pd.DataFrame()

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
                            st.write(str(row['Câu trả lời']))
                            exact_match_found_for_safety = True
                            found_qa_answer = True
                            break # Đã tìm thấy khớp chính xác, dừng tìm kiếm
                    
                    if not exact_match_found_for_safety:
                        st.warning("⚠️ Không tìm thấy câu trả lời chính xác 100% cho yêu cầu 'An toàn:' của bạn. Vui lòng đảm bảo câu hỏi khớp hoàn toàn (có thể bỏ qua dấu cách thừa).")
                        found_qa_answer = True # Đánh dấu là đã xử lý nhánh này, dù không tìm thấy khớp đủ cao
            
            # Logic hiện có cho các câu hỏi chung (khớp tương đối)
            # Chỉ chạy nếu chưa tìm thấy câu trả lời từ nhánh "An toàn:"
            if not found_qa_answer and not qa_df.empty and 'Câu hỏi' in qa_df.columns and 'Câu trả lời' in qa_df.columns:
                best_match_score = 0
                best_answer = ""
                
                for index, row in qa_df.iterrows():
                    question_from_sheet = str(row['Câu hỏi']).lower()
                    score = fuzz.ratio(user_msg_lower, question_from_sheet)
                    
                    if score > best_match_score:
                        best_match_score = score
                        best_answer = str(row['Câu trả lời'])
                
                if best_match_score >= 80: # Nếu độ tương đồng từ 80% trở lên
                    st.write(best_answer)
                    found_qa_answer = True
                elif best_match_score >= 60: # Nếu độ tương đồng từ 60% đến dưới 80%
                    st.info(f"Có vẻ bạn đang hỏi về: '{qa_df.loc[qa_df['Câu trả lời'] == best_answer, 'Câu hỏi'].iloc[0]}'? Câu trả lời là: {best_answer}")
                    found_qa_answer = True


            if found_qa_answer:
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

                        # Nếu năm chưa được trích xuất từ "tháng MM/YYYY", cố gắng trích xuất từ "nămYYYY"
                        if not target_year:
                            year_only_match = re.search(r"năm\s+(\d{4})", user_msg_lower)
                            if year_only_match:
                                target_year = year_only_match.group(1)

                        filtered_df_suco = df_suco # Khởi tạo với toàn bộ dataframe

                        # Kiểm tra sự tồn tại của cột 'Tháng/Năm sự cố'
                        if 'Tháng/Năm sự cố' not in df_suco.columns:
                            st.warning("⚠️ Không tìm thấy cột 'Tháng/Năm sự cố' trong sheet 'Quản lý sự cố'. Không thể lọc theo tháng/năm.")
                            # Nếu cột bị thiếu, không thể lọc theo tháng/năm, hiển thị toàn bộ dữ liệu hoặc không có gì
                            if target_month or target_year:
                                st.info("Hiển thị toàn bộ dữ liệu sự cố (nếu có) do không tìm thấy cột lọc tháng/năm.")
                                # filtered_df_suco vẫn là df_suco ban đầu
                            else:
                                # Nếu không có tháng/năm cụ thể được yêu cầu, và cột cũng thiếu, vẫn hiển thị toàn bộ
                                pass # filtered_df_suco đã là df_suco
                        else:
                            # Thực hiện lọc dựa trên tháng và năm đã trích xuất
                            if target_month and target_year:
                                # Lọc chính xác theo định dạng "MM/YYYY"
                                exact_match_str = f"{int(target_month):02d}/{target_year}"
                                filtered_df_suco = filtered_df_suco[filtered_df_suco['Tháng/Năm sự cố'].astype(str) == exact_match_str]
                            elif target_month:
                                # Lọc theo tiền tố tháng "MM/"
                                month_prefix = f"{int(target_month):02d}/"
                                filtered_df_suco = filtered_df_suco[filtered_df_suco['Tháng/Năm sự cố'].astype(str).str.startswith(month_prefix)]
                            elif target_year:
                                # Lọc theo hậu tố năm "/YYYY"
                                year_suffix = f"/{target_year}"
                                filtered_df_suco = filtered_df_suco[filtered_df_suco['Tháng/Năm sự cố'].astype(str).str.endswith(year_suffix)]


                        if filtered_df_suco.empty:
                            st.warning(f"⚠️ Không tìm thấy sự cố nào {'trong tháng ' + target_month if target_month else ''} {'năm ' + target_year if target_year else ''}.")
                            # Không hiển thị toàn bộ dataframe nếu có yêu cầu tháng/năm cụ thể mà không tìm thấy
                        
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
                            # Nếu filtered_df rỗng sau tất cả các bước lọc và không có thông báo cụ thể
                            # Điều này xảy ra nếu có yêu cầu tháng/năm cụ thể nhưng không tìm thấy dữ liệu
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
                                errors='coerce' # Chuyển đổi các giá trị không phải số thành NaN
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

                        # Regex để bắt tên người sau "thông tin" hoặc "của" (tham lam)
                        name_match = re.search(r"(?:thông tin|của)\s+([a-zA-Z\s]+)", user_msg_lower)
                        if name_match:
                            person_name = name_match.group(1).strip()
                            # Loại bỏ các từ khóa có thể bị bắt nhầm vào tên
                            known_keywords = ["trong", "tổ", "phòng", "đội", "cbcnv", "tất cả"] # Thêm "tất cả"
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
                                bo_phan_counts = df_to_show['Bộ phận công tác'].value_counts()

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
                            st.write(response.choices[0].message.content)
                        except Exception as e:
                            st.error(f"❌ Lỗi khi gọi OpenAI: {e}. Vui lòng kiểm tra API key hoặc quyền truy cập mô hình.")
                    else:
                        st.warning("Không có API key OpenAI. Vui lòng thêm vào st.secrets để sử dụng chatbot cho các câu hỏi tổng quát.")
def clean_question_an_toan(text):
    return re.sub(r"Câu\s*\d+\s*[:：]", "", text, flags=re.IGNORECASE).strip()

# Đọc file Excel hoặc Google Sheet (anh thay đường dẫn file cho phù hợp)
df_an_toan = pd.read_excel("file_cau_hoi_an_toan.xlsx", sheet_name="An toàn")

# Tạo dictionary với câu hỏi chuẩn hóa
qa_an_toan_dict = {clean_question_an_toan(q): a for q, a in zip(df_an_toan["Câu hỏi"], df_an_toan["Đáp án"])}

# Hàm tra lời an toàn
def tra_loi_an_toan(user_question):
    user_clean = clean_question_an_toan(user_question)
    for question, answer in qa_an_toan_dict.items():
        if fuzz.ratio(user_clean.lower(), question.lower()) > 95:
            return answer
    return None
