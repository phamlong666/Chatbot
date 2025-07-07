
# Hướng dẫn chạy bot Flask "Trợ lý Điện lực"

## Bước 1: Cài thư viện
```
pip install -r requirements.txt
```

## Bước 2: Đặt file JSON key Google (sotaygpt-fba5e9b3e6fd.json) vào cùng thư mục

## Bước 3: Chạy bot
```
python app.py
```

## Bước 4: Test
Gửi POST request tới `http://localhost:5000/webhook` với JSON:
```
{
  "message": "Danh sách CBCNV bộ phận Kinh doanh"
}
```
Bot sẽ trả danh sách nhân viên Kinh doanh.
