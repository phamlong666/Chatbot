import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI
import pandas as pd # Thêm thư viện pandas
import matplotlib.pyplot as plt # Thêm thư viện matplotlib

# Kết nối Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

if "google_service_account" in st.secrets:
    info = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
else:
    st.error("❌ Không tìm thấy google_service_account trong secrets.")

# Lấy API key OpenAI từ secrets (ĐÃ SỬA ĐỂ GÁN TRỰC TIẾP)
# KHUYẾN NGHỊ: KHÔNG NÊN ĐẶT KEY TRỰC TIẾP NHƯ THẾ NÀY TRONG MÃ NGUỒN CÔNG KHAI HOẶC MÔI TRƯỜNG SẢN XUẤT.
# HÃY DÙNG st.secrets HOẶC BIẾN MÔI TRƯỜNG ĐỂ BẢO MẬT.
openai_api_key_direct = "sk-proj-3SkFtE-6W2yUYFL2wj3kxlD6epI7ZIeDaInlwYfjwLjBzbrr4jC02GkQEqZ1CwlAxRIrv7iv0T3BlbkFJEQxDvv9kGtpJ5an9AZGMJpftDxMx-u21snU1qiqLitRmqzyakhkRKO366_xZqczo4Ghw3JoeoA"


if openai_api_key_direct:
    client_ai = OpenAI(api_key=openai_api_key_direct)
    st.success("✅ Đã kết nối OpenAI API key.")
else:
    client_ai = None
    st.warning("⚠️ Chưa cấu hình API key OpenAI. Vui lòng thêm vào st.secrets.")

# Hàm để lấy dữ liệu từ một sheet cụ thể
def get_sheet_data(sheet_name):
    try:
        sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/13MqQzvV3Mf9bLOAXwICXclYVQ-8WnvBDPAR8VJfOGJg/edit").worksheet(sheet_name)
        return sheet.get_all_records()
    except Exception as e:
        st.error(f"❌ Không mở được Google Sheet '{sheet_name}': {e}")
        return None

st.title("🤖 Trợ lý Điện lực Định Hóa")

user_msg = st.text_input("Bạn muốn hỏi gì?")

if st.button("Gửi"):
    user_msg_lower = user_msg.lower()

    # Xử lý truy vấn liên quan đến nhân sự (sheet CBCNV)
    if "cbcnv" in user_msg_lower or "danh sách" in user_msg_lower or any(k in user_msg_lower for k in ["tổ", "phòng", "đội", "nhân viên", "nhân sự"]):
        records = get_sheet_data("CBCNV")
        if records:
            reply_list = []
            bo_phan = None
            for keyword in ["tổ ", "phòng ", "đội "]:
                if keyword in user_msg_lower:
                    # Cần cải thiện việc tách bộ phận để lấy chính xác tên
                    parts = user_msg_lower.split(keyword, 1)
                    if len(parts) > 1:
                        bo_phan = parts[1].split(' ')[0].strip() # Lấy từ đầu tiên sau từ khóa
                        if not bo_phan: # Nếu không có từ nào sau đó
                            bo_phan = user_msg_lower.split(keyword)[1].strip()
                            # Cố gắng lấy bộ phận đầy đủ hơn nếu có thể
                            if "năm" in bo_phan: bo_phan = bo_phan.split("năm")[0].strip()
                            if "sinh" in bo_phan: bo_phan = bo_phan.split("sinh")[0].strip()
                            if "trình độ" in bo_phan: bo_phan = bo_phan.split("trình độ")[0].strip()
                            if "chức danh" in bo_phan: bo_phan = bo_phan.split("chức danh")[0].strip()
                    break

            filtered_records = []
            for r in records:
                if bo_phan:
                    if bo_phan.lower() in r.get('Bộ phận công tác', '').lower():
                        filtered_records.append(r)
                else:
                    filtered_records.append(r) # Nếu không có bộ phận cụ thể, trả về tất cả

            if filtered_records:
                for r in filtered_records:
                    reply_list.append(
                        f"Họ và tên: {r.get('Họ và tên', 'N/A')}\n"
                        f"Ngày sinh: {r.get('Ngày sinh CBCNV', 'N/A')}\n"
                        f"Trình độ chuyên môn: {r.get('Trình độ chuyên môn', 'N/A')}\n"
                        f"Tháng năm vào ngành: {r.get('Tháng năm vào ngành', 'N/A')}\n"
                        f"Bộ phận công tác: {r.get('Bộ phận công tác', 'N/A')}\n"
                        f"Chức danh: {r.get('Chức danh', 'N/A')}\n"
                        f"---"
                    )
                reply_text = "\n".join(reply_list)
                st.text_area("Kết quả", value=reply_text, height=300)
            else:
                st.warning("⚠️ Không tìm thấy dữ liệu phù hợp với yêu cầu của bạn. Vui lòng kiểm tra tên bộ phận hoặc từ khóa.")
        else:
            st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet CBCNV.")

    # Xử lý truy vấn liên quan đến doanh thu và biểu đồ (ví dụ: giả sử có sheet "DoanhThu")
    elif "doanh thu" in user_msg_lower or "báo cáo tài chính" in user_msg_lower or "biểu đồ doanh thu" in user_msg_lower:
        records = get_sheet_data("DoanhThu") # Thay "DoanhThu" bằng tên sheet thực tế của bạn
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
                        fig, ax = plt.subplots(figsize=(10, 6))
                        ax.bar(df['Tháng'], df['Doanh thu'], color='skyblue')
                        ax.set_xlabel("Tháng")
                        ax.set_ylabel("Doanh thu (Đơn vị)") # Thay "Đơn vị" bằng đơn vị thực tế
                        ax.set_title("Biểu đồ Doanh thu thực tế theo tháng")
                        plt.xticks(rotation=45, ha='right')
                        plt.tight_layout()
                        st.pyplot(fig)
                    except Exception as e:
                        st.error(f"❌ Lỗi khi vẽ biểu đồ doanh thu: {e}. Vui lòng kiểm tra định dạng dữ liệu trong sheet.")
                else:
                    st.warning("⚠️ Không tìm thấy các cột 'Tháng' hoặc 'Doanh thu' trong sheet DoanhThu để vẽ biểu đồ.")
            else:
                st.warning("⚠️ Dữ liệu doanh thu rỗng, không thể hiển thị hoặc vẽ biểu đồ.")
        else:
            st.warning("⚠️ Không thể truy xuất dữ liệu từ sheet DoanhThu. Vui lòng kiểm tra tên sheet và quyền truy cập.")

    # Thêm các điều kiện 'elif' khác để xử lý các sheet khác
    # Ví dụ: elif "chi phí" in user_msg_lower: ...
    # elif "thống kê" in user_msg_lower: ...

    # Xử lý các câu hỏi chung bằng OpenAI
    else:
        if client_ai:
            try:
                response = client_ai.chat.completions.create(
                    model="gpt-3.5-turbo", # Có thể thử "gpt-4o" nếu có quyền truy cập
                    messages=[
                        {"role": "system", "content": "Bạn là trợ lý ảo của Tổng Công ty Điện lực, chuyên hỗ trợ trả lời các câu hỏi kỹ thuật, nghiệp vụ, đoàn thể và cộng đồng liên quan đến ngành điện. Luôn cung cấp thông tin chính xác và hữu ích."},
                        {"role": "user", "content": user_msg}
                    ]
                )
                st.write(response.choices[0].message.content)
            except Exception as e:
                st.error(f"❌ Lỗi khi gọi OpenAI: {e}. Vui lòng kiểm tra API key hoặc quyền truy cập mô hình.")
        else:
            st.warning("⚠️ Không có API key OpenAI. Vui lòng thêm vào st.secrets để sử dụng chatbot cho các câu hỏi tổng quát.")