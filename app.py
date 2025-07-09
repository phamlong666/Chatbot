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
# KHUYẾN NGHỊ: KHÔNG NÊN ĐẶT KEY TRỰC TIẾP NHƯ THẾ NÀY TRONG MÃ NGUỒN CÔNG KHAI HOẶC MÔI TRƯỜNG SẢN XUẤT.
# HÃY DÙNG st.secrets HOẶC BIẾN MÔI TRƯỜNG ĐỂ BẢO MẬT.
# Ví dụ sử dụng st.secrets:
# openai_api_key_direct = st.secrets.get("openai_api_key")
# Hoặc giữ nguyên nếu bạn đang test cục bộ và đã paste key vào đây
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
        # Thay thế URL này bằng URL Google Sheet của bạn
        spreadsheet_url = "https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit"
        sheet = client.open_by_url(spreadsheet_url).worksheet(sheet_name)
        return sheet.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Không tìm thấy sheet '{sheet_name}'. Vui lòng kiểm tra tên sheet.")
        return None
    except Exception as e:
        st.error(f"❌ Lỗi khi mở Google Sheet '{sheet_name}': {e}")
        return None

# Thêm logo vào giao diện chính
# URL trực tiếp của logo từ GitHub
# Đây là URL trực tiếp (Raw URL) từ GitHub của logo của bạn.
# Nó có dạng https://raw.githubusercontent.com/your_username/your_repo_name/main/your_image.png
public_logo_url = "https://raw.githubusercontent.com/phamlong666/Chatbot/main/logo_hinh_tron.png" # <= Đã cập nhật URL logo chính xác của bạn

try:
    # Cố gắng hiển thị ảnh từ URL công khai với kích thước 100px
    st.image(public_logo_url, width=100) # Đã thay đổi kích thước thành 100
except Exception as e_public_url:
    st.error(f"❌ Lỗi khi hiển thị logo từ URL: {e_public_url}. Vui lòng đảm bảo URL là liên kết TRỰC TIẾP đến file ảnh (kết thúc bằng .jpg, .png, v.v.) và kiểm tra kết nối internet.")
    # Fallback về file cục bộ (chỉ để dự phòng, có thể vẫn gặp lỗi nếu file không được triển khai đúng)
    logo_path = Path(__file__).parent / "logo_hinh_tron.jpg"
    try:
        if logo_path.exists():
            st.image(str(logo_path), width=100) # Đã thay đổi kích thước thành 100
        else:
            st.error(f"❌ Không tìm thấy file ảnh logo tại: {logo_path}. Vui lòng đảm bảo file 'logo_hinh_tron.jpg' nằm cùng thư mục với file app.py của bạn khi triển khai.")
    except Exception as e_local_file:
        st.error(f"❌ Lỗi khi hiển thị ảnh logo từ file cục bộ: {e_local_file}.")


st.title("🤖 Chatbot Đội QLĐLKV Định Hóa")

user_msg = st.text_input("Bạn muốn hỏi gì?")

if st.button("Gửi"):
    user_msg_lower = user_msg.lower()

    # Xử lý truy vấn để lấy dữ liệu từ BẤT KỲ sheet nào (ƯU TIÊN HÀNG ĐẦU)
    if "lấy dữ liệu sheet" in user_msg_lower:
        # Sử dụng regex để trích xuất tên sheet
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
            # Thông báo lỗi đã được xử lý trong get_sheet_data
        else:
            st.warning("⚠️ Vui lòng cung cấp tên sheet rõ ràng. Ví dụ: 'lấy dữ liệu sheet DoanhThu'.")

    # Xử lý truy vấn liên quan đến sheet "Danh sách lãnh đạo xã, phường" (Ưu tiên cao)
    elif any(k in user_msg_lower for k in ["lãnh đạo xã", "lãnh đạo phường", "lãnh đạo định hóa", "danh sách lãnh đạo"]):
        records = get_sheet_data("Danh sách lãnh đạo xã, phường") # Tên sheet chính xác từ hình ảnh
        if records:
            df_lanhdao = pd.DataFrame(records)
            
            # Logic để tìm tên xã/phường/địa điểm trong câu hỏi của người dùng
            location_name = None
            # Regex để bắt "xã/phường [Tên Xã/Phường]" hoặc "Định Hóa"
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
            
            # Logic để tìm tên đường dây trong câu hỏi của người dùng
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

            # Logic lọc theo tên người cụ thể
            person_name = None
            # Regex để bắt tên người sau "thông tin" hoặc "của" và trước các từ khóa khác hoặc kết thúc chuỗi
            name_match = re.search(r"(?:thông tin|của)\s+([a-zA-Z\s]+?)(?:\s+trong|\s+tổ|\s+phòng|\s+đội|\s+cbcnv|$)", user_msg_lower)
            if name_match:
                person_name = name_match.group(1).strip()

            # Logic lọc theo bộ phận (vẫn giữ nếu người dùng hỏi cả tên và bộ phận)
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
                # Lọc theo tên người - SỬ DỤNG SO SÁNH CHÍNH XÁC (==)
                filtered_df = filtered_df[filtered_df['Họ và tên'].astype(str).str.lower() == person_name.lower()]
            
            if bo_phan and 'Bộ phận công tác' in filtered_df.columns:
                # Lọc theo bộ phận (nếu có cả tên người và bộ phận)
                filtered_df = filtered_df[filtered_df['Bộ phận công tác'].str.lower().str.contains(bo_phan.lower(), na=False)]

            if not filtered_df.empty:
                st.subheader(f"Thông tin CBCNV {'của ' + person_name.title() if person_name else ''} {'thuộc ' + bo_phan.title() if bo_phan else ''}:")
                # Hiển thị danh sách chi tiết
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

                        # Tăng kích thước figure để có thêm không gian cho nhãn trục hoành
                        fig, ax = plt.subplots(figsize=(12, 7)) 
                        
                        # Tạo danh sách màu sắc duy nhất cho mỗi bộ phận
                        colors = cm.get_cmap('tab10', len(bo_phan_counts.index)) # Sử dụng colormap 'tab10'
                        
                        # Vẽ biểu đồ cột với màu sắc riêng cho từng cột
                        bars = ax.bar(bo_phan_counts.index, bo_phan_counts.values, color=colors.colors)
                        
                        # Hiển thị giá trị trên đỉnh mỗi cột với màu đen
                        for bar in bars:
                            yval = bar.get_height()
                            ax.text(bar.get_x() + bar.get_width()/2, yval + 0.1, round(yval), ha='center', va='bottom', color='black') # Màu chữ đen

                        ax.set_xlabel("Bộ phận công tác")
                        ax.set_ylabel("Số lượng nhân viên")
                        ax.set_title("Biểu đồ số lượng CBCNV theo Bộ phận")
                        plt.xticks(rotation=45, ha='right') # Xoay nhãn trục hoành 45 độ
                        plt.tight_layout() # Tự động điều chỉnh layout để tránh chồng chéo
                        st.pyplot(fig, dpi=400) # Tăng DPI để biểu đồ nét hơn
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
            st.warning("⚠️ Không có API key OpenAI. Vui lòng thêm vào st.secrets để sử dụng chatbot cho các câu hỏi tổng quát.")
