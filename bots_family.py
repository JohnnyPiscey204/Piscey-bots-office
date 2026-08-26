import os
import time
from datetime import datetime, timedelta
import gspread
import telebot
from telebot import types
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from bs4 import BeautifulSoup
import re
import traceback
import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import threading
from flask import Flask
import random
import string
import requests
import base64
from dateutil.relativedelta import relativedelta
from concurrent.futures import ThreadPoolExecutor

# =========================================================================
# KHU VỰC 0: CẤU HÌNH HỆ THỐNG & KẾT NỐI CHUNG
# =========================================================================
load_dotenv()

# --- KHỞI TẠO WEB SERVER (GIỮ BOT THỨC) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Trạm vũ trụ 3-in-1 của Piscey đang trực chiến 24/7!"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- QUYỀN TRUY CẬP GOOGLE CHUNG ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# =========================================================================
# KHU VỰC 1: BOT CÔNG TÁC PHÍ
# =========================================================================
TOKEN_CONGTAC = os.getenv("TOKEN_CONGTAC")
bot_congtac = telebot.TeleBot(TOKEN_CONGTAC)

SPREADSHEET_ID_CONGTAC = os.getenv("SPREADSHEET_ID_CONGTAC")
DRIVE_FOLDER_ID_CONGTAC = os.getenv("DRIVE_FOLDER_ID_CONGTAC")
GAS_WEB_APP_URL_CONGTAC = os.getenv("GAS_WEB_APP_URL_CONGTAC")
FILE_KEY_JSON_CONGTAC = 'creds_congtac.json'

creds_congtac = ServiceAccountCredentials.from_json_keyfile_name(FILE_KEY_JSON_CONGTAC, scope)
client_congtac = gspread.authorize(creds_congtac)
sheet_congtac = client_congtac.open_by_key(SPREADSHEET_ID_CONGTAC)

ws_info = sheet_congtac.worksheet("1. Thông Tin Chung")
ws_log = sheet_congtac.worksheet("2. Nhật Ký Chi Tiêu")
ws_sheet3 = sheet_congtac.worksheet("3. Theo Dõi Định Mức")

waiting_bills = {}

def parse_money_congtac(s):
    s = s.replace(' ', '').lower()
    s = s.replace('tỷ', 'ty').replace('củ', 'tr').replace('lít', 'lit').replace('loét', 'lit').replace('rưỡi', '5').replace('ruoi', '5')
    try:
        if 'ty' in s:
            parts = s.split('ty')
            val = float(parts[0].replace(',', '.')) if parts[0] else 0
            return int(val * 1000000000)
        elif 'tr' in s:
            parts = s.split('tr')
            left_val = float(parts[0].replace(',', '.')) if parts[0] else 0
            right_val = 0
            if len(parts) > 1 and parts[1]:
                right_digits = re.sub(r'[^\d]', '', parts[1])
                if right_digits:
                    right_val = float(f"0.{right_digits}") * 1000000
            return int((left_val * 1000000) + right_val)
        elif 'lit' in s:
            parts = s.split('lit')
            val = float(parts[0].replace(',', '.')) if parts[0] else 0
            return int(val * 100000)
        elif 'k' in s:
            parts = s.split('k')
            left_val = float(parts[0].replace(',', '.')) if parts[0] else 0
            right_val = 0
            if len(parts) > 1 and parts[1]:
                right_digits = re.sub(r'[^\d]', '', parts[1])
                if right_digits:
                    right_val = float(f"0.{right_digits}") * 1000
            return int((left_val * 1000) + right_val)
        else:
            clean_s = re.sub(r'(đ|d|vnd)$', '', s)
            if re.search(r'[a-z]', clean_s): return 0
            val = float(clean_s.replace(',', '.'))
            return int(val)
    except:
        clean_s = re.sub(r'[^\d]', '', s)
        return int(clean_s) if clean_s else 0

def parse_expense_congtac(text: str) -> dict:
    result = {"amount": 0, "content": "", "category": "", "time": "", "has_bill": False, "note": "", "region": None}
    now = datetime.now()
    text = re.sub(r'(\d+(?:[.,]\d+)?)\s+(tỷ|ty|tr|củ|cu|lít|lit|loét|k|đ|d|vnd)\b', r'\1\2', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(tỷ|ty|tr|củ|cu|lít|lit|loét|k)\s+(rưỡi|ruoi|\d+)\b', r'\1\2', text, flags=re.IGNORECASE)

    if "*hd" in text.lower():
        result["has_bill"] = True
        text = re.sub(r'\*hd', '', text, flags=re.IGNORECASE).strip()
        
    note_match = re.search(r'note:(.*)', text, re.IGNORECASE)
    if note_match:
        result["note"] = note_match.group(1).strip()
        text = re.sub(r'note:.*', '', text, flags=re.IGNORECASE).strip()

    if "nội tỉnh" in text.lower():
        result["region"] = "Nội tỉnh"
        text = re.sub(r'nội tỉnh', '', text, flags=re.IGNORECASE).strip()
    elif "ngoại tỉnh" in text.lower():
        result["region"] = "Ngoại tỉnh"
        text = re.sub(r'ngoại tỉnh', '', text, flags=re.IGNORECASE).strip()
        
    tag_match = re.search(r'#(\w+)', text)
    if tag_match:
        result["category"] = tag_match.group(1).strip()
        text = text.replace(tag_match.group(0), '', 1).strip()
        
    parsed_date = now.strftime("%d/%m")
    parsed_time = now.strftime("%H:%M")
    
    date_match = re.search(r'\b(\d{1,2})/(\d{1,2})\b', text)
    if date_match:
        d, m = date_match.groups()
        parsed_date = f"{int(d):02d}/{int(m):02d}"
        text = text.replace(date_match.group(0), '', 1).strip()
        
    time_match = re.search(r'\b(\d{1,2})[h:](\d{2})?\b', text, re.IGNORECASE)
    if time_match:
        h = time_match.group(1)
        m = time_match.group(2) if time_match.group(2) else "00"
        parsed_time = f"{int(h):02d}:{m}"
        text = text.replace(time_match.group(0), '', 1).strip()
        
    result["time"] = f"{parsed_date} {parsed_time}"
    
    words = text.split()
    for word in words:
        val = parse_money_congtac(word)
        if val > 0:
            result["amount"] = val
            text = text.replace(word, '', 1).strip()
            break
            
    result["content"] = re.sub(r'\s+', ' ', text).strip()
    return result

def get_active_trip_info():
    records = ws_info.get_all_values()
    for i in range(len(records)-1, 0, -1):
        if records[i][2] == "[Đang Chạy]":
            return i + 1, {
                "Trip ID": records[i][0], "Tên Chuyến": records[i][1],
                "Trạng Thái": records[i][2], "Nhân Sự": records[i][4],
                "Khu Vực Mặc Định": records[i][5], "Tổng Tạm Ứng": records[i][6],
                "Số Ngày": int(records[i][7]) if len(records[i]) > 7 and records[i][7].isdigit() else 1
            }
    return None, None

def get_next_short_id(trip_id):
    records = ws_log.get_all_values()
    count = sum(1 for r in records[1:] if r[1] == str(trip_id))
    return f"#{count + 1}"

def sync_drive_delete(action, trip_id, short_id=None):
    try:
        payload = {"action": action, "parentFolderId": DRIVE_FOLDER_ID_CONGTAC, "tripId": trip_id}
        if short_id: payload["shortId"] = short_id
        requests.post(GAS_WEB_APP_URL_CONGTAC, json=payload) 
    except Exception as e:
        print(f"Lỗi đồng bộ xoá trên Drive: {e}")

def is_cancel_command(text):
    if not text: return False
    t = text.strip().lower()
    cancel_keywords = ['huỷ', 'hủy', 'cancel', 'thoát', 'hủy bỏ', 'huỷ bỏ', 'x']
    menu_buttons = ['📝 tạo khoản chi', '✏️ sửa khoản chi', '🗑️ xóa khoản chi', '📋 thông tin chuyến', '📖 hướng dẫn sử dụng']
    return t in cancel_keywords or t in menu_buttons or t.startswith('/')

def main_menu_congtac():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton('📝 Tạo Khoản Chi'), types.KeyboardButton('✏️ Sửa Khoản Chi'),
        types.KeyboardButton('🗑️ Xóa Khoản Chi'), types.KeyboardButton('📋 Thông Tin Chuyến'),
        types.KeyboardButton('📖 Hướng Dẫn Sử Dụng')
    )
    return markup

def trip_inline_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🚀 Khởi Tạo", callback_data="trip_start"),
        types.InlineKeyboardButton("🛑 Kết Thúc", callback_data="trip_end"),
        types.InlineKeyboardButton("💰 Ứng Thêm", callback_data="trip_advance"),
        types.InlineKeyboardButton("📊 Báo Cáo Thu Chi", callback_data="trip_report"),
        types.InlineKeyboardButton("⚙️ Đổi Khu Vực", callback_data="trip_region"),
        types.InlineKeyboardButton("✏️ Sửa Thông Tin", callback_data="trip_edit"),
        types.InlineKeyboardButton("🗑️ Xoá Chuyến", callback_data="trip_delete")
    )
    return markup

@bot_congtac.message_handler(commands=['start'])
def send_welcome_congtac(message):
    bot_congtac.reply_to(message, "Chào sếp! Trợ lý công tác phí đã sẵn sàng. Em có thể giúp gì nào?", reply_markup=main_menu_congtac())

@bot_congtac.message_handler(func=lambda message: message.text == '📋 Thông Tin Chuyến')
def btn_trip_info(message):
    row_idx, active = get_active_trip_info()
    if active:
        tam_ung_str = str(active['Tổng Tạm Ứng'])
        tam_ung_clean = re.sub(r'[^\d]', '', tam_ung_str)
        tam_ung_tien = int(tam_ung_clean) if tam_ung_clean else 0
        msg = f"🟢 <b>Đang công tác:</b> {active['Tên Chuyến']} ({active['Trip ID']})\n📍 <b>Khu vực áp dụng:</b> {active['Khu Vực Mặc Định']}\n💰 <b>Đã ứng:</b> <code>{tam_ung_tien:,} đ</code>"
    else:
        msg = "⚪ Hiện không có chuyến công tác nào đang chạy."
    bot_congtac.send_message(message.chat.id, msg, reply_markup=trip_inline_menu(), parse_mode="HTML")

@bot_congtac.message_handler(func=lambda message: message.text == '📝 Tạo Khoản Chi')
def btn_create_expense(message):
    row_idx, active = get_active_trip_info()
    if not active:
        bot_congtac.send_message(message.chat.id, "⚠️ <b>Sếp chưa khởi tạo chuyến công tác nào!</b>\nBấm vào nút [📋 Thông Tin Chuyến] bên dưới để tạo chuyến mới trước khi ghi tiêu nhé.", parse_mode="HTML")
        return
    bot_congtac.send_message(message.chat.id, "Sếp nay tiêu gì thế? Ném cho em theo cú pháp:\n\n<code>[số tiền] #[loại chi] [tên khoản chi] [thời gian - tùy chọn] *hd note:[ghi chú]</code>\n\nVD: <code>1tr5 #NgoaiGiao tiếp khách 19h30 23/04 *hd note:bàn 5 người</code>", parse_mode="HTML")

@bot_congtac.message_handler(func=lambda message: message.text == '✏️ Sửa Khoản Chi')
def btn_edit_guide(message):
    row_idx, active = get_active_trip_info()
    if not active:
        bot_congtac.send_message(message.chat.id, "⚠️ Không có chuyến nào đang chạy!")
        return
    records = ws_log.get_all_values()
    def clean_money_display(val_str):
        if not val_str: return "0 đ"
        cleaned = re.sub(r'[\sđdVDvnd]+$', '', str(val_str), flags=re.IGNORECASE).strip()
        cleaned_num = re.sub(r'[^\d]', '', cleaned)
        if cleaned_num: return f"{int(cleaned_num):,} đ".replace(',', '.')
        return "0 đ"
    items = [r for r in records[1:] if r[1] == active['Trip ID']]
    msg = "💡 <b>Cách sửa khoản chi:</b>\nNhắn tin: <code>Sửa #[ID] [thông tin mới]</code>\nVD: <code>Sửa #2 1tr5 #AnUong Bữa tối *hd</code>\n\n"
    if items:
        msg += "📋 <b>CÁC KHOẢN CHI GẦN NHẤT:</b>\n"
        for r in items[-10:]:
            money_formatted = clean_money_display(r[6])
            msg += f"• <b>{r[0]}</b>: <code>{money_formatted}</code> - {r[4]} {r[3]}\n"
    else:
        msg += "<i>(Chưa có khoản chi nào trong chuyến này)</i>"
    bot_congtac.send_message(message.chat.id, msg, parse_mode="HTML")

@bot_congtac.message_handler(func=lambda message: message.text == '📖 Hướng Dẫn Sử Dụng')
def btn_help(message):
    bot_congtac.send_message(
        message.chat.id,
        "📖 <b>HƯỚNG DẪN SỬ DỤNG TRỢ LÝ CÔNG TÁC PHÍ</b> 📖\n\n"
        "Chào sếp! Đây là cuốn cẩm nang thu nhỏ giúp sếp ghi chép chi phí công tác siêu nhanh mà không cần nhớ nhiều.\n\n"
        "🚀 <b>BƯỚC 1: KHỞI TẠO CHUYẾN ĐI (Bắt buộc phải làm trước khi tiêu tiền)</b>\n"
        "1. Bấm vào nút <b>[📋 Thông Tin Chuyến]</b> ở menu bên dưới.\n"
        "2. Bấm tiếp nút <b>[🚀 Khởi Tạo]</b> xuất hiện trong đoạn chat.\n"
        "3. Làm theo hướng dẫn của bot: Nhập tên chuyến đi, chọn Nội/Ngoại tỉnh, điền danh sách nhân sự và số tiền công ty tạm ứng ban đầu.\n\n"
        "📝 <b>BƯỚC 2: CÁCH GHI CHÉP CHI PHÍ LÚC Đang DI CHUYỂN</b>\n"
        "Mỗi khi ăn uống, đi xe, tiếp khách xong, sếp chỉ cần nhắn tin cho bot theo đúng một dòng đơn giản:\n\n"
        "👉 <code>[Số tiền] #[Loại chi] [Nội dung] [Thời gian] *hd note:[Ghi chú]</code>\n\n"
        "💡 <b>Giải thích chi tiết từng thành phần:</b>\n"
        "• <b>[Số tiền]:</b> Viết cực kỳ ngắn gọn, ví dụ: <code>150k</code> (150 nghìn), <code>1tr5</code> hoặc <code>1.5tr</code> (1 triệu rưỡi), <code>500000</code>.\n"
        "• <b>#[Loại chi]:</b> Phải có dấu thăng ở đầu để phân loại, ví dụ: <code>#AnUong</code>, <code>#DiChuyen</code>, <code>#KhachSan</code>, <code>#NgoaiGiao</code>.\n"
        "• <b>[Nội dung]:</b> Tên quán ăn, tên hãng xe hoặc việc sếp mua gì (VD: <i>phở bò, taxi ra sân bay</i>).\n"
        "• <b>[Thời gian] (Không bắt buộc):</b> Nếu đi từ hôm qua mà hôm nay mới nhập, hãy ghi kèm giờ và ngày, VD: <code>10h 23/4</code>. Nếu tiêu xong nhập luôn thì <b>bỏ trống</b>, bot sẽ tự lấy giờ hiện tại.\n"
        "• <b>*hd (Không bắt buộc):</b> Thêm chữ này vào nếu sếp <b>đã lấy hóa đơn đỏ/biên lai</b>.\n"
        "• <b>note: [Ghi chú] (Không bắt buộc):</b> Dùng để ghi chú thêm thông tin (VD: <i>note: ăn cùng đối tác A</i>).\n\n"
        "📌 <b>Ví dụ thực tế siêu chuẩn:</b>\n"
        "<code>1tr5 #NgoaiGiao tiếp khách nhà hàng 19h30 23/4 *hd note:bàn 5 người</code>\n\n"
        "✏️ <b>BƯỚC 3: CÁCH SỬA HOẶC XOÁ KHOẢN CHI KHI LỠ NHẬP SAI</b>\n"
        "• <b>Sửa:</b> Bấm nút <b>[✏️ Sửa Khoản Chi]</b> để xem danh sách các mã (`#1`, `#2`...). Sau đó nhắn tin theo cú pháp: <code>Sửa #[Mã ID] [thông tin mới cần sửa]</code>.\n"
        "• <b>Xoá:</b> Bấm nút <b>[🗑️ Xoá Khoản Chi]</b>, bot sẽ hiện ra các nút bấm tương ứng với từng khoản chi, chỉ cần chạm vào nút khoản đó là nó tự biến mất khỏi sổ sách!\n\n"
        "🎯 <b>CÁC NÚT QUẢN LÝ KHÁC (Trong menu [📋 Thông Tin Chuyến]):</b>\n"
        "• <b>[💰 Ứng Thêm]:</b> Dùng khi giữa chuyến hết tiền và xin công ty cấp thêm.\n"
        "• <b>[⚙️ Đổi Khu Vực]:</b> Dùng khi di chuyển từ Ngoại tỉnh về Nội tỉnh (hoặc ngược lại).\n"
        "• <b>[🛑 Kết Thúc]:</b> Bấm nút này khi chuyến công tác đã hoàn thành để chốt sổ báo cáo.",
        parse_mode="HTML"
    )

@bot_congtac.callback_query_handler(func=lambda call: call.data.startswith('trip_') or call.data.startswith('del_trip_') or call.data.startswith('confirm_del_trip_') or call.data.startswith('report_trip_'))
def handle_trip_callbacks(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    bot_congtac.answer_callback_query(call.id)
    row_idx, active = get_active_trip_info()
    
    if call.data == "trip_start":
        if active:
            bot_congtac.edit_message_text(f"⚠️ <b>TỪ CHỐI TẠO MỚI:</b> Sếp đang có chuyến <b>{active['Tên Chuyến']}</b> đang hoạt động!\n\n👉 Vui lòng mở [Thông Tin Chuyến] và ấn <b>[🛑 Kết Thúc]</b> chuyến hiện tại trước khi khởi tạo chuyến mới.", chat_id, msg_id, parse_mode="HTML")
            return
        bot_congtac.edit_message_text("⏳ Đang chuẩn bị form tạo chuyến đi...", chat_id, msg_id)
        msg = bot_congtac.send_message(chat_id, "1️⃣ Sếp nhập <b>Tên chuyến đi</b> nhé (VD: Công tác Hà Nội):", parse_mode="HTML")
        bot_congtac.register_next_step_handler(msg, process_trip_name)
        
    elif call.data == "trip_end":
        if not active:
            bot_congtac.edit_message_text("⚪ Không có chuyến nào đang chạy để kết thúc.", chat_id, msg_id)
            return
        bot_congtac.edit_message_text("⏳ Đang chốt sổ chuyến đi...", chat_id, msg_id)
        ws_info.update_cell(row_idx, 3, "[Kết Thúc]")
        bot_congtac.edit_message_text(f"🛑 Đã chốt sổ và kết thúc chuyến: <b>{active['Tên Chuyến']}</b>", chat_id, msg_id, parse_mode="HTML")
        
    elif call.data == "trip_advance":
        if not active:
            bot_congtac.edit_message_text("⚠️ Sếp phải khởi tạo chuyến đi mới ứng thêm được tiền!", chat_id, msg_id)
            return
        bot_congtac.edit_message_text("⏳ Đang mở form ứng tiền...", chat_id, msg_id)
        msg = bot_congtac.send_message(chat_id, f"💰 Nhập <b>số tiền xin ứng thêm</b> cho chuyến {active['Tên Chuyến']}:", parse_mode="HTML")
        bot_congtac.register_next_step_handler(msg, process_trip_advance, row_idx, active['Tổng Tạm Ứng'])

    elif call.data == "trip_report":
        markup = types.InlineKeyboardMarkup(row_width=1)
        if active:
            markup.add(types.InlineKeyboardButton(f"🟢 Chuyến hiện tại: {active['Tên Chuyến']}", callback_data=f"report_trip_select_{active['Trip ID']}"))
        markup.add(types.InlineKeyboardButton("📚 Chọn chuyến khác từ danh sách", callback_data="report_trip_list_0"))
        markup.add(types.InlineKeyboardButton("❌ Huỷ", callback_data="trip_report_cancel"))
        bot_congtac.edit_message_text("Sếp muốn xem báo cáo của chuyến nào?", chat_id, msg_id, reply_markup=markup)

    elif call.data.startswith('report_trip_list_'):
        page = int(call.data.split('_')[3])
        records = ws_info.get_all_values()
        trips = []
        for i, r in enumerate(records[1:], start=2):
            if r[0]: trips.append({"id": r[0], "name": r[1], "status": r[2]})
        trips.reverse()
        if not trips:
            bot_congtac.edit_message_text("⚠️ Không có chuyến công tác nào trong sổ!", chat_id, msg_id)
            return
        items_per_page = 5
        total_pages = max(1, (len(trips) - 1) // items_per_page + 1)
        page = max(0, min(page, total_pages - 1))
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        current_trips = trips[start_idx:end_idx]
        markup = types.InlineKeyboardMarkup(row_width=1)
        for t in current_trips:
            icon = "🟢" if t['status'] == "[Đang Chạy]" else "⚪"
            markup.add(types.InlineKeyboardButton(f"{icon} [{t['id']}] {t['name']}", callback_data=f"report_trip_select_{t['id']}"))
        nav_buttons = []
        if page > 0: nav_buttons.append(types.InlineKeyboardButton("⬅️ Trước", callback_data=f"report_trip_list_{page-1}"))
        if page < total_pages - 1: nav_buttons.append(types.InlineKeyboardButton("Sau ➡️", callback_data=f"report_trip_list_{page+1}"))
        if nav_buttons: markup.row(*nav_buttons)
        markup.add(types.InlineKeyboardButton("❌ Huỷ", callback_data="trip_report_cancel"))
        bot_congtac.edit_message_text(f"📊 Chọn chuyến cần xem báo cáo (Trang {page+1}/{total_pages}):", chat_id, msg_id, reply_markup=markup)

    elif call.data.startswith('report_trip_select_'):
        trip_id = call.data.split('_')[3]
        bot_congtac.edit_message_text(f"⏳ Đang tổng hợp báo cáo cho chuyến <code>{trip_id}</code>...", chat_id, msg_id, parse_mode="HTML")
        records = ws_info.get_all_values()
        selected_trip = None
        for r in records[1:]:
            if r[0] == trip_id:
                selected_trip = {
                    "Trip ID": r[0], "Tên Chuyến": r[1], "Trạng Thái": r[2], "Nhân Sự": r[4],
                    "Khu Vực Mặc Định": r[5], "Tổng Tạm Ứng": r[6],
                    "Số Ngày": int(r[7]) if len(r) > 7 and str(r[7]).isdigit() else 1
                }
                break
        if not selected_trip:
            bot_congtac.edit_message_text("⚠️ Không tìm thấy thông tin chuyến này!", chat_id, msg_id)
            return
        people = [p.strip() for p in selected_trip['Nhân Sự'].split(',') if p.strip()]
        people_count = len(people) if people else 1
        days = selected_trip['Số Ngày']
        region = selected_trip['Khu Vực Mặc Định']
        daily_rate = 620000 if region == 'Nội tỉnh' else 640000
        daily_team = people_count * daily_rate
        total_budget = daily_team * days
        tam_ung_str = str(selected_trip['Tổng Tạm Ứng'])
        tam_ung_clean = re.sub(r'[^\d]', '', tam_ung_str)
        advance = int(tam_ung_clean) if tam_ung_clean else 0
        records_log = ws_log.get_all_values()
        spent = 0
        for r in records_log[1:]:
            if r[1] == trip_id:
                val_clean = re.sub(r'[^\d]', '', str(r[6]))
                if val_clean: spent += int(val_clean)
        balance = advance - spent
        if balance >= 0: balance_text = f"🟢 DƯ {balance:,} đ (Sếp nộp lại cho Kế toán)"
        else: balance_text = f"🔴 ÂM {abs(balance):,} đ (Sếp đòi Kế toán bù)"
        msg = (
            f"📊 <b>BÁO CÁO THU CHI: {selected_trip['Tên Chuyến']}</b>\n"
            f"Trạng thái: <b>{selected_trip['Trạng Thái']}</b>\n👥 Nhân sự: {people_count} người | ⏱ Số ngày: {days} ngày\n"
            f"📍 Khu vực: {region}\n━━━━━━━━━━━━━━━━━━\n🍲 <b>Qũy định mức Ăn/Ở:</b>\n"
            f"• Cấp cho cả team/ngày: <code>{daily_team:,} đ</code>\n• Tổng định mức cả chuyến: <code>{total_budget:,} đ</code>\n\n"
            f"💰 <b>Quyết toán dòng tiền:</b>\n• Tổng tiền đã ứng: <code>{advance:,} đ</code>\n• Thực tế đã chi: <code>{spent:,} đ</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n⚖️ <b>TÌNH TRẠNG CÔNG NỢ:</b>\n👉 <b>{balance_text}</b>"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("⬅️ Quay lại danh sách", callback_data="trip_report"))
        bot_congtac.edit_message_text(msg, chat_id, msg_id, reply_markup=markup, parse_mode="HTML")

    elif call.data == 'trip_report_cancel':
        bot_congtac.edit_message_text("❌ Đã đóng menu báo cáo.", chat_id, msg_id)
        
    elif call.data == "trip_region":
        if not active:
            bot_congtac.edit_message_text("⚠️ Sếp phải khởi tạo chuyến đi mới đổi khu vực được!", chat_id, msg_id)
            return
        bot_congtac.edit_message_text("⏳ Đang mở form đổi khu vực...", chat_id, msg_id)
        msg = bot_congtac.send_message(chat_id, "📍 Sếp muốn đổi sang <b>Nội tỉnh</b> hay <b>Ngoại tỉnh</b>? (Gõ chính xác 1 trong 2):", parse_mode="HTML")
        bot_congtac.register_next_step_handler(msg, process_trip_region_change, row_idx)

    elif call.data == "trip_edit":
        if not active:
            bot_congtac.edit_message_text("⚠️ Không có chuyến nào đang chạy để sửa!", chat_id, msg_id)
            return
        bot_congtac.edit_message_text("⏳ Đang mở form sửa thông tin chuyến...", chat_id, msg_id)
        bot_congtac.send_message(
            chat_id, 
            "✏️ Nhắn tin theo cú pháp để sửa:\n• <code>Sửa tên: [Tên mới]</code>\n• <code>Sửa nhân sự: [Danh sách mới]</code>\n"
            "• <code>Sửa tạm ứng: [Số tiền mới]</code>\n• <code>Sửa số ngày: [Số mới]</code>\n\nVD: <code>Sửa tên: Công tác Hải Phòng 5 ngày</code>", 
            parse_mode="HTML"
        )

    elif call.data == "trip_delete":
        markup = types.InlineKeyboardMarkup(row_width=1)
        if active: markup.add(types.InlineKeyboardButton(f"🟢 Chuyến hiện tại: {active['Tên Chuyến']}", callback_data=f"del_trip_select_{active['Trip ID']}"))
        markup.add(types.InlineKeyboardButton("📚 Chọn chuyến khác từ danh sách", callback_data="del_trip_list_0"))
        markup.add(types.InlineKeyboardButton("❌ Huỷ", callback_data="trip_del_cancel"))
        bot_congtac.edit_message_text("Sếp muốn xoá chuyến nào?", chat_id, msg_id, reply_markup=markup)

    elif call.data.startswith('del_trip_list_'):
        page = int(call.data.split('_')[3])
        records = ws_info.get_all_values()
        trips = []
        for i, r in enumerate(records[1:], start=2):
            if r[0]: trips.append({"id": r[0], "name": r[1], "status": r[2]})
        trips.reverse()
        if not trips:
            bot_congtac.edit_message_text("⚠️ Không có chuyến công tác nào trong sổ!", chat_id, msg_id)
            return
        items_per_page = 5
        total_pages = max(1, (len(trips) - 1) // items_per_page + 1)
        page = max(0, min(page, total_pages - 1))
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        current_trips = trips[start_idx:end_idx]
        markup = types.InlineKeyboardMarkup(row_width=1)
        for t in current_trips:
            icon = "🟢" if t['status'] == "[Đang Chạy]" else "⚪"
            markup.add(types.InlineKeyboardButton(f"{icon} [{t['id']}] {t['name']}", callback_data=f"del_trip_select_{t['id']}"))
        nav_buttons = []
        if page > 0: nav_buttons.append(types.InlineKeyboardButton("⬅️ Trước", callback_data=f"del_trip_list_{page-1}"))
        if page < total_pages - 1: nav_buttons.append(types.InlineKeyboardButton("Sau ➡️", callback_data=f"del_trip_list_{page+1}"))
        if nav_buttons: markup.row(*nav_buttons)
        markup.add(types.InlineKeyboardButton("❌ Huỷ", callback_data="trip_del_cancel"))
        bot_congtac.edit_message_text(f"📚 Chọn chuyến cần xoá (Trang {page+1}/{total_pages}):", chat_id, msg_id, reply_markup=markup)

    elif call.data.startswith('del_trip_select_'):
        trip_id = call.data.split('_')[3]
        records = ws_info.get_all_values()
        trip_name, row_idx = "", -1
        for i, r in enumerate(records[1:], start=2):
            if r[0] == trip_id:
                trip_name = r[1]; row_idx = i; break
        if row_idx == -1:
            bot_congtac.edit_message_text("⚠️ Không tìm thấy chuyến này. Có thể đã bị xoá từ trước!", chat_id, msg_id)
            return
        records_log = ws_log.get_all_values()
        has_expenses = any(r[1] == trip_id for r in records_log[1:])
        if has_expenses:
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("💥 Vẫn Xoá (Xoá cả lịch sử chi)", callback_data=f"confirm_del_trip_{trip_id}"),
                types.InlineKeyboardButton("❌ Huỷ", callback_data="trip_del_cancel")
            )
            bot_congtac.edit_message_text(f"⚠️ <b>CẢNH BÁO NGUY HIỂM!</b>\nChuyến <b>{trip_name}</b> (<code>{trip_id}</code>) đang có các khoản chi tiêu ghi trong sổ.\n\nNếu xóa, <u>toàn bộ lịch sử chi tiêu liên quan sẽ bị bốc hơi vĩnh viễn</u>. Sếp chắc chắn chứ?", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
        else:
            ws_info.delete_rows(row_idx)
            try: ws_sheet3.delete_rows(row_idx)
            except: pass
            sync_drive_delete("delete_trip", trip_id)
            bot_congtac.edit_message_text(f"🗑️ Đã xoá sạch chuyến <b>{trip_name}</b> thành công vì chưa phát sinh chi tiêu nào!", chat_id, msg_id, parse_mode="HTML")

    elif call.data == 'trip_del_cancel':
        bot_congtac.edit_message_text("❌ Đã huỷ thao tác xoá chuyến đi.", chat_id, msg_id)

    elif call.data.startswith('confirm_del_trip_'):
        trip_id = call.data.split('_')[3]
        bot_congtac.edit_message_text(f"⏳ Đang dọn dẹp và xoá bỏ chuyến đi <code>{trip_id}</code>...", chat_id, msg_id, parse_mode="HTML")
        records = ws_info.get_all_values()
        for i, r in enumerate(records[1:], start=2):
            if r[0] == trip_id:
                ws_info.delete_rows(i)
                try: ws_sheet3.delete_rows(i)
                except: pass
                break
        records_log = ws_log.get_all_values()
        deleted_count = 0
        for i in range(len(records_log)-1, 0, -1):
            if records_log[i][1] == trip_id:
                ws_log.delete_rows(i + 1)
                deleted_count += 1
        sync_drive_delete("delete_trip", trip_id)
        bot_congtac.send_message(chat_id, f"💥 <b>ĐÃ XOÁ SẠCH TRIỆT ĐỂ!</b>\n• Đã xóa chuyến: <code>{trip_id}</code>\n• Đã dọn dẹp: <b>{deleted_count} khoản chi tiêu</b> liên quan ở Sheet Nhật Ký.\n✨ Bảng dữ liệu đã được làm sạch hoàn toàn!", parse_mode="HTML")

@bot_congtac.callback_query_handler(func=lambda call: call.data.startswith('confirm_del_') or call.data == 'trip_del_cancel')
def handle_confirm_delete(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    bot_congtac.answer_callback_query(call.id)
    if call.data == 'trip_del_cancel':
        bot_congtac.edit_message_text("❌ Đã huỷ thao tác xoá chuyến đi.", chat_id, msg_id)
        return
    parts = call.data.split('_')
    row_idx = int(parts[2]); trip_id = parts[3]
    ws_info.delete_rows(row_idx)
    try: ws_sheet3.delete_rows(row_idx)
    except: pass
    sync_drive_delete("delete_trip", trip_id)
    records_log = ws_log.get_all_values()
    for i in range(len(records_log)-1, 0, -1):
        if records_log[i][1] == trip_id:
            ws_log.delete_rows(i + 1)
    bot_congtac.edit_message_text(f"💥 Đã xoá vĩnh viễn chuyến <code>{trip_id}</code> cùng toàn bộ lịch sử chi tiêu đi kèm!", chat_id, msg_id, parse_mode="HTML")

def process_trip_name(message):
    if is_cancel_command(message.text):
        bot_congtac.clear_step_handler_by_chat_id(message.chat.id)
        bot_congtac.send_message(message.chat.id, "❌ Đã huỷ thao tác tạo chuyến đi.")
        return
    trip_name = message.text
    msg = bot_congtac.send_message(message.chat.id, "2️⃣ Sếp đi <b>Nội tỉnh</b> hay <b>Ngoại tỉnh</b>? (Gõ chính xác):", parse_mode="HTML")
    bot_congtac.register_next_step_handler(msg, process_trip_region, trip_name)

def process_trip_region(message, trip_name):
    if is_cancel_command(message.text):
        bot_congtac.clear_step_handler_by_chat_id(message.chat.id)
        bot_congtac.send_message(message.chat.id, "❌ Đã huỷ thao tác tạo chuyến đi.")
        return
    region = message.text
    msg = bot_congtac.send_message(message.chat.id, "3️⃣ Nhập <b>Danh sách nhân sự</b> (Mỗi người 1 dòng, hoặc gõ '1' nếu đi một mình):", parse_mode="HTML")
    bot_congtac.register_next_step_handler(msg, process_trip_personnel, trip_name, region)

def process_trip_personnel(message, trip_name, region):
    if is_cancel_command(message.text):
        bot_congtac.clear_step_handler_by_chat_id(message.chat.id)
        bot_congtac.send_message(message.chat.id, "❌ Đã huỷ thao tác tạo chuyến đi.")
        return
    personnel = message.text
    msg = bot_congtac.send_message(message.chat.id, "4️⃣ Sếp dự kiến đi <b>Mấy ngày</b>? (Chỉ gõ số, VD: 3):", parse_mode="HTML")
    bot_congtac.register_next_step_handler(msg, process_trip_days, trip_name, region, personnel)

def process_trip_days(message, trip_name, region, personnel):
    if is_cancel_command(message.text):
        bot_congtac.clear_step_handler_by_chat_id(message.chat.id)
        bot_congtac.send_message(message.chat.id, "❌ Đã huỷ thao tác tạo chuyến đi.")
        return
    try: days = int(message.text.strip())
    except: days = 1
    msg = bot_congtac.send_message(message.chat.id, "5️⃣ Công ty có ứng trước tiền không? Nhập <b>Tổng tạm ứng</b> (Gõ '0' nếu tự bỏ tiền túi):", parse_mode="HTML")
    bot_congtac.register_next_step_handler(msg, process_trip_advance_init, trip_name, region, personnel, days)

def process_trip_advance_init(message, trip_name, region, personnel, days):
    if is_cancel_command(message.text):
        bot_congtac.clear_step_handler_by_chat_id(message.chat.id)
        bot_congtac.send_message(message.chat.id, "❌ Đã huỷ thao tác tạo chuyến đi.")
        return
    advance = parse_money_congtac(message.text)
    date_str = datetime.now().strftime("%y%m%d")
    random_str = ''.join(random.choices(string.ascii_uppercase, k=4))
    trip_id = f"{date_str}-{random_str}"
    next_row_info = len(ws_info.col_values(1)) + 1
    ws_info.update(f"A{next_row_info}:H{next_row_info}", [[
        trip_id, trip_name, "[Đang Chạy]", datetime.now().strftime("%d/%m/%Y"), personnel, region, advance, days
    ]], value_input_option='USER_ENTERED')
    bot_congtac.send_message(message.chat.id, f"✅ <b>ĐÃ KHỞI TẠO THÀNH CÔNG!</b>\nMã chuyến: <code>{trip_id}</code>\nTên: {trip_name}\nNhân sự: {personnel} ({days} ngày)\nKhu vực: {region}\nTạm ứng: <code>{advance:,} đ</code>\n\nBây giờ sếp có thể bắt đầu nhắn tin ghi chép chi tiêu được rồi!", parse_mode="HTML")

def process_trip_advance(message, row_idx, current_advance):
    if is_cancel_command(message.text):
        bot_congtac.clear_step_handler_by_chat_id(message.chat.id)
        bot_congtac.send_message(message.chat.id, "❌ Đã huỷ thao tác ứng thêm tiền.")
        return
    money = parse_money_congtac(message.text)
    if money <= 0:
        bot_congtac.send_message(message.chat.id, "⚠️ Số tiền không hợp lệ. Đã huỷ thao tác.")
        return
    new_total = int(re.sub(r'[^\d]', '', str(current_advance)) if current_advance else 0) + money
    ws_info.update_cell(row_idx, 7, new_total)
    bot_congtac.send_message(message.chat.id, f"✅ Đã cộng thêm <code>{money:,} đ</code>. Tổng quỹ hiện tại: <code>{new_total:,} đ</code>", parse_mode="HTML")

def process_trip_region_change(message, row_idx):
    if is_cancel_command(message.text):
        bot_congtac.clear_step_handler_by_chat_id(message.chat.id)
        bot_congtac.send_message(message.chat.id, "❌ Đã huỷ thao tác đổi khu vực.")
        return
    ws_info.update_cell(row_idx, 6, message.text)
    bot_congtac.send_message(message.chat.id, f"✅ Đã đổi khu vực mặc định thành: <b>{message.text}</b>", parse_mode="HTML")

@bot_congtac.message_handler(func=lambda message: message.text == '🗑️ Xóa Khoản Chi')
def btn_delete_expense(message):
    show_delete_page(message.chat.id, message.message_id, page=0, is_new=True)

def show_delete_page(chat_id, msg_id, page=0, is_new=False):
    row_idx, active = get_active_trip_info()
    if not active:
        msg = "⚠️ Không có chuyến nào đang chạy để xóa chi tiêu!"
        if is_new: bot_congtac.send_message(chat_id, msg)
        else: bot_congtac.edit_message_text(msg, chat_id, msg_id)
        return
    records = ws_log.get_all_values()
    def clean_money_display(val_str):
        if not val_str: return "0 đ"
        cleaned = re.sub(r'[\sđdVDvnd]+$', '', str(val_str), flags=re.IGNORECASE).strip()
        cleaned_num = re.sub(r'[^\d]', '', cleaned)
        if cleaned_num: return f"{int(cleaned_num):,} đ".replace(',', '.')
        return "0 đ"
    items = []
    for i, r in enumerate(records[1:], start=2):
        if r[1] == active['Trip ID']:
            money_formatted = clean_money_display(r[6])
            items.append({"row": i, "id": r[0], "name": r[3], "amount": money_formatted})
    if not items:
        msg = "⚠️ Chuyến này chưa có khoản chi nào để xóa!"
        if is_new: bot_congtac.send_message(chat_id, msg)
        else: bot_congtac.edit_message_text(msg, chat_id, msg_id)
        return
    items_per_page = 5
    total_pages = max(1, (len(items) - 1) // items_per_page + 1)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    current_items = items[start_idx:end_idx]
    markup = types.InlineKeyboardMarkup(row_width=1)
    for item in current_items:
        btn_text = f"[{item['id']}] {item['name']} - {item['amount']}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"del_item_{item['row']}_{item['id']}_{page}"))
    nav_buttons = []
    if page > 0: nav_buttons.append(types.InlineKeyboardButton("⬅️ Trang trước", callback_data=f"del_page_{page-1}"))
    if page < total_pages - 1: nav_buttons.append(types.InlineKeyboardButton("Trang sau ➡️", callback_data=f"del_page_{page+1}"))
    if nav_buttons: markup.row(*nav_buttons)
    markup.add(types.InlineKeyboardButton("❌ Huỷ", callback_data="del_cancel"))
    text_content = f"Sếp muốn xoá khoản nào? (Trang {page+1}/{total_pages}, Tổng số: {len(items)} khoản):"
    if is_new: bot_congtac.send_message(chat_id, text_content, reply_markup=markup)
    else:
        try: bot_congtac.edit_message_text(text_content, chat_id, msg_id, reply_markup=markup)
        except Exception: pass 

@bot_congtac.callback_query_handler(func=lambda call: call.data.startswith('del_'))
def handle_delete_callback(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    bot_congtac.answer_callback_query(call.id)
    if call.data == "del_cancel":
        bot_congtac.edit_message_text("❌ <b>Đã huỷ thao tác xoá!</b>", chat_id, msg_id, parse_mode='HTML')
        return
    if call.data.startswith('del_page_'):
        new_page = int(call.data.split('_')[2])
        show_delete_page(chat_id, msg_id, page=new_page, is_new=False)
        return
    if call.data.startswith('del_item_'):
        parts = call.data.split('_')
        target_row = int(parts[2]); short_id = parts[3]; current_page = int(parts[4])
        bot_congtac.edit_message_text(f"⏳ Đang xoá khoản <b>{short_id}</b> khỏi sổ...", chat_id, msg_id, parse_mode='HTML')
        row_idx, active = get_active_trip_info()
        if active: sync_drive_delete("delete_expense", active['Trip ID'], short_id)
        ws_log.delete_rows(target_row)
        show_delete_page(chat_id, msg_id, page=current_page, is_new=False)

@bot_congtac.message_handler(func=lambda message: True)
def process_text_inputs_congtac(message):
    text = message.text
    if text in ["📝 Tạo Khoản Chi", "✏️ Sửa Khoản Chi", "🗑️ Xóa Khoản Chi", "📋 Thông Tin Chuyến", "📖 Hướng Dẫn Sử Dụng"] or text.startswith("/"):
        return
    row_idx, active_trip = get_active_trip_info()
    if not active_trip:
        bot_congtac.send_message(message.chat.id, "⚠️ Sếp chưa khởi tạo chuyến công tác nào! Vào [Thông Tin Chuyến] để tạo nhé.")
        return

    if text.lower().startswith('sửa tên:') or text.lower().startswith('sửa nhân sự:') or text.lower().startswith('sửa tạm ứng:') or text.lower().startswith('sửa số ngày:'):
        try:
            if text.lower().startswith('sửa tên:'):
                new_val = text.split(':', 1)[1].strip()
                ws_info.update_cell(row_idx, 2, new_val) 
                bot_congtac.send_message(message.chat.id, f"✅ Đã đổi tên chuyến thành: <b>{new_val}</b>", parse_mode="HTML")
            elif text.lower().startswith('sửa nhân sự:'):
                new_val = text.split(':', 1)[1].strip()
                ws_info.update_cell(row_idx, 5, new_val) 
                bot_congtac.send_message(message.chat.id, f"✅ Đã cập nhật danh sách nhân sự thành:\n<code>{new_val}</code>", parse_mode="HTML")
            elif text.lower().startswith('sửa tạm ứng:'):
                money_val = parse_money_congtac(text.split(':', 1)[1])
                ws_info.update_cell(row_idx, 7, money_val) 
                bot_congtac.send_message(message.chat.id, f"✅ Đã cập nhật tổng tạm ứng thành: <code>{money_val:,} đ</code>", parse_mode="HTML")
            elif text.lower().startswith('sửa số ngày:'):
                new_val = re.sub(r'[^\d]', '', text.split(':', 1)[1].strip())
                if new_val:
                    ws_info.update_cell(row_idx, 8, int(new_val)) 
                    bot_congtac.send_message(message.chat.id, f"✅ Đã cập nhật số ngày thành: <b>{new_val} ngày</b>", parse_mode="HTML")
        except Exception as e:
            bot_congtac.send_message(message.chat.id, f"❌ Lỗi sửa thông tin chuyến: {e}")
        return

    if re.match(r'(?i)^sửa\s+#', text) or re.match(r'(?i)^sua\s+#', text):
        id_match = re.search(r'#\d+', text)
        if id_match:
            short_id = id_match.group(0)
            new_info = text.replace(id_match.group(0), '').replace('Sửa', '').replace('sửa', '').strip()
            records = ws_log.get_all_values()
            target_row = -1
            for i, r in enumerate(records[1:], start=2):
                if r[1] == active_trip['Trip ID'] and r[0] == short_id:
                    target_row = i; break
            if target_row == -1:
                bot_congtac.send_message(message.chat.id, f"❓ Không tìm thấy mã <b>{short_id}</b>.", parse_mode="HTML")
                return
            parsed = parse_expense_congtac(new_info)
            msg_reply = f"✏️ Đã cập nhật khoản <b>{short_id}</b>:\n"
            if parsed['amount'] > 0: 
                ws_log.update_cell(target_row, 7, parsed['amount'])
                msg_reply += f"- Tiền mới: <code>{parsed['amount']:,}đ</code>\n"
            if parsed['content']: 
                ws_log.update_cell(target_row, 4, parsed['content'])
                msg_reply += f"- Nội dung: {parsed['content']}\n"
            if parsed['category']: 
                ws_log.update_cell(target_row, 5, parsed['category'])
                msg_reply += f"- Loại chi: {parsed['category']}\n"
            if parsed['region']: 
                ws_log.update_cell(target_row, 6, parsed['region'])
                msg_reply += f"- Khu vực: {parsed['region']}\n"
            if parsed['note']: 
                ws_log.update_cell(target_row, 9, parsed['note'])
                msg_reply += f"- Ghi chú: {parsed['note']}\n"
            if parsed['has_bill']: 
                ws_log.update_cell(target_row, 8, "TRUE")
                msg_reply += f"- Tình trạng: Đã lấy bill ✅\n\n"
                waiting_bills[message.chat.id] = {"trip_id": active_trip["Trip ID"], "short_id": short_id, "row_idx": target_row}
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(types.InlineKeyboardButton("📸 Gửi luôn", callback_data="bill_req_now"), types.InlineKeyboardButton("⏳ Để sau", callback_data="bill_req_later"))
                bot_congtac.send_message(message.chat.id, msg_reply + "🧾 Sếp vừa cập nhật trạng thái có hoá đơn. Sếp có muốn gửi ảnh/file lên luôn không?", reply_markup=markup, parse_mode="HTML")
            else:
                bot_congtac.send_message(message.chat.id, msg_reply, parse_mode="HTML")
        return

    try:
        parsed = parse_expense_congtac(text)
        if parsed["amount"] == 0 or not parsed["category"]:
            bot_congtac.send_message(message.chat.id, "❌ Cú pháp sai. Hãy kiểm tra lại Số tiền hoặc Hashtag <code>#loại_chi</code>.", parse_mode="HTML")
            return
        short_id = get_next_short_id(active_trip["Trip ID"])
        bill_status = True if parsed["has_bill"] else False
        next_row_log = len(ws_log.col_values(1)) + 1
        final_region = parsed["region"] if parsed["region"] else active_trip["Khu Vực Mặc Định"]
        ws_log.update(f"A{next_row_log}:I{next_row_log}", [[
            short_id, active_trip["Trip ID"], parsed["time"], parsed["content"], parsed["category"], final_region, 
            parsed["amount"], bill_status, parsed["note"]
        ]], value_input_option='USER_ENTERED')
        msg_text = f"✅ <b>Đã ghi nhận {short_id}</b>\n💰 Tiền: <code>{parsed['amount']:,}đ</code>\n📝 Nội dung: {parsed['content']}\n🏷️ Loại: {parsed['category']} | 📍 Khu vực: {final_region}\n"
        if parsed["has_bill"]:
            waiting_bills[message.chat.id] = {"trip_id": active_trip["Trip ID"], "short_id": short_id, "row_idx": next_row_log}
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(types.InlineKeyboardButton("📸 Gửi luôn", callback_data="bill_req_now"), types.InlineKeyboardButton("⏳ Để sau", callback_data="bill_req_later"))
            bot_congtac.send_message(message.chat.id, msg_text + "🧾 <b>Tình trạng:</b> Đã note có hoá đơn.\n\nSếp có muốn gửi ảnh/file hoá đơn lên luôn không?", reply_markup=markup, parse_mode="HTML")
        else:
            bot_congtac.send_message(message.chat.id, msg_text + "🧾 <b>Tình trạng:</b> ⚠️ CHƯA LẤY BILL", parse_mode="HTML")
    except Exception as e:
        bot_congtac.send_message(message.chat.id, f"❌ Có lỗi kỹ thuật xảy ra: {str(e)}")

@bot_congtac.callback_query_handler(func=lambda call: call.data.startswith('bill_req_'))
def handle_bill_request(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    bot_congtac.answer_callback_query(call.id)
    if call.data == "bill_req_later":
        if chat_id in waiting_bills: del waiting_bills[chat_id]
        bot_congtac.edit_message_text(call.message.text + "\n\n<i>-> Đã chọn: Gửi hoá đơn sau.</i>", chat_id, msg_id, parse_mode="HTML")
    elif call.data == "bill_req_now":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ Huỷ (Không gửi nữa)", callback_data="bill_req_cancel"))
        bot_congtac.edit_message_text(call.message.text + "\n\n⏳ <b>ĐANG CHỜ HÓA ĐƠN...</b>\nSếp hãy gửi ảnh hoặc file (PDF) vào chat ngay bây giờ nhé!", chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
        if chat_id in waiting_bills: waiting_bills[chat_id]['prompt_msg_id'] = msg_id
    elif call.data == "bill_req_cancel":
        if chat_id in waiting_bills: del waiting_bills[chat_id]
        bot_congtac.edit_message_text(call.message.text.replace("⏳ ĐANG CHỜ HÓA ĐƠN...", "❌ Đã huỷ chế độ chờ hoá đơn."), chat_id, msg_id, parse_mode="HTML")

@bot_congtac.message_handler(content_types=['photo', 'document'])
def handle_docs_photo(message):
    chat_id = message.chat.id
    if chat_id not in waiting_bills: return 
    session = waiting_bills[chat_id]
    processing_msg = bot_congtac.send_message(chat_id, "⏳ Đang nén và đẩy file lên Google Drive, sếp đợi tí...")
    try:
        if message.photo:
            file_info = bot_congtac.get_file(message.photo[-1].file_id) 
            mimetype = 'image/jpeg'
        elif message.document:
            file_info = bot_congtac.get_file(message.document.file_id)
            mimetype = message.document.mime_type
        downloaded_file = bot_congtac.download_file(file_info.file_path)
        base64_data = base64.b64encode(downloaded_file).decode('utf-8')
        payload = {"parentFolderId": DRIVE_FOLDER_ID_CONGTAC, "tripId": session['trip_id'], "filename": session['short_id'], "mimeType": mimetype, "base64": base64_data}
        response = requests.post(GAS_WEB_APP_URL_CONGTAC, json=payload)
        result = response.json()
        if not result.get("success"): raise Exception(result.get("error"))
        link = result.get("url")
        current_link = ws_log.cell(session['row_idx'], 10).value
        new_link = f"{current_link}\n{link}" if current_link else link
        ws_log.update_cell(session['row_idx'], 10, new_link)
        bot_congtac.edit_message_text(f"✅ <b>Xong!</b> Đã lưu hoá đơn cho khoản {session['short_id']}.\n🔗 <a href='{link}'>Xem file gốc tại đây</a>", chat_id, processing_msg.message_id, parse_mode="HTML", disable_web_page_preview=True)
        prompt_msg_id = session.get('prompt_msg_id')
        if prompt_msg_id:
            try: bot_congtac.edit_message_reply_markup(chat_id, prompt_msg_id, reply_markup=None)
            except: pass
        del waiting_bills[chat_id]
    except Exception as e:
        bot_congtac.edit_message_text(f"❌ Lỗi tải file: {e}", chat_id, processing_msg.message_id)


# =========================================================================
# =========================================================================
# KHU VỰC 2: BOT CÀO GIÁ PC (NÂNG CẤP AUTO & SMART RETRY)
# =========================================================================
TOKEN_CAOGIA = os.getenv("TOKEN_CAOGIA")
bot_caogia = telebot.TeleBot(TOKEN_CAOGIA)

SHEET_URL_CAOGIA = os.getenv("SHEET_URL_CAOGIA")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "ee811480c36ac839eadfda36dca4b6f1")
FILE_KEY_JSON_CAOGIA = 'creds_caogia.json'

creds_caogia = ServiceAccountCredentials.from_json_keyfile_name(FILE_KEY_JSON_CAOGIA, scope)
client_caogia = gspread.authorize(creds_caogia)
spreadsheet_caogia = client_caogia.open_by_url(SHEET_URL_CAOGIA)

is_scraping = False
cancel_scraping = False
auto_config = {"interval_days": 0, "chat_id": None} # Biến lưu trạng thái hẹn giờ

SHEET_CONFIG = {
    "PC_components": {"start_row_index": 0, "block_size": 13, "date_cell": "B1"},
    "Laptop_Gaming": {"start_row_index": 0, "block_size": 8, "date_cell": "B1"}
}

def clean_price(price_text):
    # Dùng Regex thông minh: Lọc lấy cụm số tiền đầu tiên (bỏ qua giá cũ gạch ngang)
    match = re.search(r'\d+(?:[.,]\d+)*', price_text)
    if match:
        num_str = re.sub(r'[^\d]', '', match.group(0))
        return int(num_str) if num_str else 0
    return 0

def duplicate_and_push_down(sheet_name):
    if sheet_name not in SHEET_CONFIG: return
    target_sheet = spreadsheet_caogia.worksheet(sheet_name)
    sheet_id = target_sheet.id
    date_cell = SHEET_CONFIG[sheet_name]["date_cell"]
    today_format_1 = datetime.now().strftime("%Y-%m-%d") 
    today_format_2 = datetime.now().strftime("%d/%m/%Y") 
    current_date_val = str(target_sheet.acell(date_cell).value).strip()
    if current_date_val in [today_format_1, today_format_2]:
        return 
    start_idx = SHEET_CONFIG[sheet_name]["start_row_index"]
    block_size = SHEET_CONFIG[sheet_name]["block_size"]
    requests_batch = [
        {"insertDimension": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": start_idx, "endIndex": start_idx + block_size}, "inheritFromBefore": False}},
        {"copyPaste": {"source": {"sheetId": sheet_id, "startRowIndex": start_idx + block_size, "endRowIndex": start_idx + block_size * 2}, "destination": {"sheetId": sheet_id, "startRowIndex": start_idx, "endRowIndex": start_idx + block_size}, "pasteType": "PASTE_NORMAL"}}
    ]
    spreadsheet_caogia.batch_update({'requests': requests_batch})
    target_sheet.update_acell(date_cell, today_format_1)

def run_scraper_process(chat_id, scan_type="all", is_auto=False):
    global is_scraping, cancel_scraping
    if is_scraping:
        if not is_auto: bot_caogia.send_message(chat_id, "⚠️ Đang có một tiến trình cào giá khác chạy rồi sếp!")
        return
    is_scraping = True
    cancel_scraping = False
    campaign_name = "CẤU HÌNH PC" if scan_type == "pc" else ("LAPTOP GAMING" if scan_type == "laptop" else "TẤT CẢ TÀI NGUYÊN")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🛑 Hủy Cào Giá", callback_data="cancel_scrape"))
    
    prefix = "🤖 [AUTO TỰ ĐỘNG] " if is_auto else "🚀 "
    progress_msg = bot_caogia.send_message(chat_id, f"{prefix}Bắt đầu chiến dịch: **{campaign_name}**...", reply_markup=markup, parse_mode="Markdown")
    
    try:
        link_sheet = spreadsheet_caogia.worksheet("Data_Links")
        tasks = link_sheet.get_all_records()
        valid_tasks = []
        for t in tasks:
            if not str(t.get('URL')).strip() or not str(t.get('Cell')).strip(): continue
            target = str(t.get('Target_Sheet')).strip()
            if scan_type == "pc" and target != "PC_components": continue
            if scan_type == "laptop" and target != "Laptop_Gaming": continue
            valid_tasks.append(t)
            
        if len(valid_tasks) == 0:
            bot_caogia.edit_message_text(f"❌ Không tìm thấy link nào phù hợp!", chat_id, progress_msg.message_id)
            is_scraping = False; return
            
        unique_sheets = set(str(t.get('Target_Sheet')).strip() for t in valid_tasks)
        for s_name in unique_sheets: duplicate_and_push_down(s_name)
        
        tasks_to_run = valid_tasks.copy()
        max_retries = 3      # Số vòng quét tối đa (Cào 1 lần + Vét lỗi 2 lần)
        current_round = 1
        
        while tasks_to_run and current_round <= max_retries and not cancel_scraping:
            failed_tasks = []
            if current_round > 1:
                bot_caogia.send_message(chat_id, f"♻️ **VÒNG {current_round} (VÉT LỖI):** Quét lại {len(tasks_to_run)} shop gặp sự cố...", parse_mode="Markdown")
                
            report_lines = []
            for i, task in enumerate(tasks_to_run, start=1):
                if cancel_scraping: break
                
                target_sheet_name = str(task.get('Target_Sheet')).strip()
                cell = str(task.get('Cell')).strip()
                url = str(task.get('URL')).strip()
                css = str(task.get('CSS_Selector')).strip()
                item_name = str(task.get('Ten_Linh_Kien', 'Sản phẩm')).strip()
                shop_name = url.split("/")[2] if "//" in url else url[:20]
                target_sheet = spreadsheet_caogia.worksheet(target_sheet_name)
                
                status_icon, result_text = "⏳", "Đang xử lý..."
                is_success = False
                
                try:
                    # GỌI QUA MÁY CHỦ CỦA SCRAPERAPI (Phiên bản tiết kiệm)
                    payload = {
                        'api_key': SCRAPER_API_KEY,
                        'url': url,
                        'render': 'true' # Lệnh chí mạng: Bắt ScraperAPI bật trình duyệt ngầm giải CAPTCHA & render giá
                    }
                    
                    # Chờ tối đa 45s vì API phải tải trình duyệt và vượt tường lửa
                    response = requests.get('http://api.scraperapi.com/', params=payload, timeout=45)
                    
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, 'html.parser')
                        price_element = soup.select_one(css)
                        
                        if price_element:
                            price = clean_price(price_element.text)
                            he_so = task.get('He_So', 1) 
                            try: he_so = int(he_so) if str(he_so).strip() != "" else 1
                            except: he_so = 1
                            price = price * he_so 
                            
                            val = "LIÊN HỆ" if price == 0 else price
                            target_sheet.update_acell(cell, val)
                            status_icon = "✅"
                            price_str = f"{val:,}".replace(",", ".") + " đ" if isinstance(val, int) else val
                            result_text = f"Xong ({price_str})"
                            is_success = True
                        else:
                            target_sheet.update_acell(cell, "LỖI CSS")
                            status_icon, result_text = "❌", "Lỗi CSS"
                    else:
                        target_sheet.update_acell(cell, "LỖI MẠNG")
                        status_icon, result_text = "⚠️", f"Bị chặn (Lỗi API: {response.status_code})"
                except Exception as e:
                    target_sheet.update_acell(cell, "LỖI MẠNG")
                    status_icon, result_text = "⚠️", "Lỗi Kết Nối API"
                
                # Nếu cào thất bại, ném link đó vào danh sách để vòng sau cào lại
                if not is_success:
                    failed_tasks.append(task)
                    
                report_lines.append(f"{status_icon} [{item_name}] {shop_name}: {result_text}")
                recent_reports = "\n".join(report_lines[-5:])
                status_text = f"🔄 TIẾN TRÌNH VÒNG {current_round}: [{i}/{len(tasks_to_run)}]\n\nTrạng thái gần nhất:\n{recent_reports}"
                try: bot_caogia.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=status_text, reply_markup=markup)
                except: pass
                
            if failed_tasks and not cancel_scraping:
                current_round += 1
                tasks_to_run = failed_tasks
                if current_round <= max_retries:
                    time.sleep(15) # Mạng lắc thì cho máy chủ nghỉ thở 15 giây trước khi vét vòng tiếp theo
            else:
                break
                
        if not cancel_scraping:
            final_text = f"✅ **BÁO CÁO SẾP:** Đã chốt xong {campaign_name}!\n\nSố vòng quét đã chạy: {min(current_round, max_retries)}\nSố lượng shop bị xịt hoàn toàn: {len(failed_tasks)}\nBảng giá đã được cập nhật thành công!"
            
            # 1. Chuyển tin nhắn Loading trên cùng thành thông báo đã xong (cho đỡ rối)
            try: bot_caogia.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=f"🏁 Chiến dịch **{campaign_name}** đã hoàn tất! (Xem báo cáo bên dưới 👇)", parse_mode="Markdown")
            except: pass
            
            # 2. Bắn hẳn một tin nhắn Báo Cáo mới toanh xuống dưới cùng của đoạn chat
            bot_caogia.send_message(chat_id, final_text, parse_mode="Markdown")
    except Exception as e:
         error_detail = traceback.format_exc()
         bot_caogia.send_message(chat_id, f"❌ Sếp ơi code gãy rồi! Chi tiết:\n\n```python\n{error_detail[-3500:]}\n```", parse_mode="Markdown")
    finally:
        is_scraping = False

# --- (ĐOẠN CODE VẼ BIỂU ĐỒ GIỮ NGUYÊN) ---
# --- (ĐOẠN CODE VẼ BIỂU ĐỒ NÂNG CẤP) ---
def generate_and_send_chart(chat_id, item_name):
    bot_caogia.send_message(chat_id, f"⏳ Đang lục lọi lịch sử và vẽ biểu đồ cho: [{item_name}]...")
    try:
        link_sheet = spreadsheet_caogia.worksheet("Data_Links")
        target_sheet_name = next((str(t.get('Target_Sheet')).strip() for t in link_sheet.get_all_records() if str(t.get('Ten_Linh_Kien')).strip() == item_name), None)
        if not target_sheet_name:
            bot_caogia.send_message(chat_id, "❌ Sếp ơi không tìm thấy linh kiện này trong Data_Links.")
            return
        all_values = spreadsheet_caogia.worksheet(target_sheet_name).get_all_values()
        history, current_date, shop_names = [], None, []
        keywords = [k for k in item_name.lower().split() if k]
        for row in all_values:
            if not row: continue
            row_clean = [str(cell).strip() for cell in row]
            row_lower = [c.lower() for c in row_clean]
            col_a = row_lower[0] if row_lower else ""
            if "ngày" in col_a and "check" in col_a:
                current_date = next((c for c in row_clean[1:3] if c), None)
            elif "loại linh kiện" in col_a or "tên laptop" in col_a:
                end_idx = row_lower.index("giá thấp nhất") if "giá thấp nhất" in row_lower else len(row_clean)
                shop_names = [s for s in row_clean[2:end_idx] if s]
            elif current_date and shop_names and all(k in " ".join(row_lower) for k in keywords):
                prices = {}
                for i, shop in enumerate(shop_names):
                    idx = 2 + i
                    val = clean_price(row_clean[idx]) if idx < len(row_clean) else 0
                    prices[shop] = val if val > 0 else None 
                history.append({'date': current_date, 'prices': prices})
        if not history:
            bot_caogia.send_message(chat_id, "❌ Chưa có dữ liệu hoặc tên linh kiện không khớp.")
            return
        history.reverse()
        dates = [h['date'] for h in history]
        all_shops = list(history[0]['prices'].keys()) if history else []
        
        # 1. RÚT GỌN NGÀY THÁNG (Bỏ đi năm, chỉ giữ dd/mm)
        short_dates = []
        for d in dates:
            if '/' in d:
                parts = d.split('/')
                short_dates.append(f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else d)
            elif '-' in d:
                parts = d.split('-')
                short_dates.append(f"{parts[2]}/{parts[1]}" if len(parts) >= 3 else d)
            else:
                short_dates.append(d)

        plt.figure(figsize=(12, 7)) 
        has_data = False
        for shop in all_shops:
            shop_prices = [h['prices'].get(shop) for h in history]
            if any(p is not None for p in shop_prices):
                line = plt.plot(short_dates, shop_prices, marker='o', linewidth=2, label=shop)
                has_data = True
                
                # 2. LỌC ĐIỂM GHI CHÚ GIÁ (Chỉ in khi có thay đổi)
                prev_price = None 
                for i, p in enumerate(shop_prices):
                    if p is not None and p > 0:
                        if prev_price is None or p != prev_price:
                            price_str = f"{int(p):,}".replace(",", ".")
                            plt.annotate(price_str, (short_dates[i], p), textcoords="offset points", xytext=(0, 10), ha='center', fontsize=9, fontweight='bold', color=line[0].get_color())
                        prev_price = p # Cập nhật lại giá mốc
                        
        if not has_data:
            bot_caogia.send_message(chat_id, "❌ Toàn bộ các shop đều báo LIÊN HỆ, không có giá để vẽ.")
            plt.close(); return
            
        plt.title(f"BIỂU ĐỒ BIẾN ĐỘNG GIÁ: {item_name.upper()}", fontsize=16, fontweight='bold', pad=20)
        plt.xlabel("Ngày quét", fontsize=12, labelpad=10)
        plt.ylabel("Giá tiền (VNĐ)", fontsize=12, labelpad=10)
        plt.grid(True, linestyle='--', alpha=0.7)
        ax = plt.gca()
        ax.get_yaxis().set_major_formatter(ticker.FuncFormatter(lambda x, p: format(int(x), ',')))
        plt.legend(loc='center left', bbox_to_anchor=(1.02, 0.5), title="Các Shop")
        
        # 3. XOAY NGÀY THÁNG GÓC 45 ĐỘ CHO GỌN
        plt.xticks(rotation=45, ha='right') 
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150)
        buf.seek(0)
        plt.close()
        bot_caogia.send_photo(chat_id, photo=buf, caption=f"📊 Sếp xem biểu đồ giá của **{item_name}** nhé!", parse_mode="Markdown")
    except Exception as e:
        error_detail = traceback.format_exc()
        bot_caogia.send_message(chat_id, f"❌ Có lỗi khi vẽ biểu đồ. Chi tiết:\n\n```python\n{error_detail[-3500:]}\n```", parse_mode="Markdown")

@bot_caogia.message_handler(commands=['start', 'menu'])
def send_menu_caogia(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("🚀 Quét Giá Thị Trường"), types.KeyboardButton("📈 Xem Biểu Đồ Biến Động"))
    markup.add(types.KeyboardButton("⏰ Setup Auto Quét"), types.KeyboardButton("📊 Mở File Báo Cáo"))
    bot_caogia.send_message(message.chat.id, "🤖 Trạm vũ trụ công nghệ đã sẵn sàng. Chọn lệnh dưới menu:", reply_markup=markup)

@bot_caogia.message_handler(func=lambda message: message.text in ["🚀 Quét Giá Thị Trường", "📊 Mở File Báo Cáo", "📈 Xem Biểu Đồ Biến Động", "⏰ Setup Auto Quét"])
def handle_menu_click_caogia(message):
    text = message.text
    if text == "🚀 Quét Giá Thị Trường":
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton("🖥️ Chỉ quét cấu hình PC", callback_data="scan_pc"), types.InlineKeyboardButton("💻 Chỉ quét Laptop Gaming", callback_data="scan_laptop"), types.InlineKeyboardButton("🌍 Quét TẤT CẢ TÀI NGUYÊN", callback_data="scan_all"))
        bot_caogia.send_message(message.chat.id, "Sếp muốn lệnh cho bot đi cào ở mặt trận nào?", reply_markup=markup)
    elif text == "📊 Mở File Báo Cáo":
        bot_caogia.send_message(message.chat.id, f"Link Sheet của sếp đây: {SHEET_URL_CAOGIA}")
    elif text == "📈 Xem Biểu Đồ Biến Động":
        link_sheet = spreadsheet_caogia.worksheet("Data_Links")
        tasks = link_sheet.get_all_records()
        unique_items = list(set([str(t.get('Ten_Linh_Kien')).strip() for t in tasks if str(t.get('Ten_Linh_Kien')).strip()]))
        if not unique_items:
            bot_caogia.send_message(message.chat.id, "Chưa có linh kiện nào trong Data_Links!")
            return
        markup = types.InlineKeyboardMarkup(row_width=1)
        for item in unique_items: markup.add(types.InlineKeyboardButton(f"📉 {item}", callback_data=f"chart_{item}"))
        bot_caogia.send_message(message.chat.id, "Sếp muốn vẽ biểu đồ cho linh kiện nào?", reply_markup=markup)
    
    elif text == "⏰ Setup Auto Quét":
        try:
            target_sheet = spreadsheet_caogia.worksheet("Laptop_Gaming")
            current_days = str(target_sheet.acell('C1').value).strip()
            current_hour = str(target_sheet.acell('E1').value).strip()
            if current_days.isdigit() and int(current_days) > 0:
                hour_text = f"lúc {current_hour}h" if current_hour.isdigit() else ""
                status_text = f"🔄 Đang bật: Mỗi **{current_days} ngày** {hour_text}"
            else:
                status_text = "❌ Đang tắt chế độ Auto"
        except:
            status_text = "❌ Đang tắt chế độ Auto"
            
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton("🔄 Quét mỗi 3 ngày", callback_data="setauto_3"),
                   types.InlineKeyboardButton("🔄 Quét mỗi 5 ngày", callback_data="setauto_5"))
        markup.add(types.InlineKeyboardButton("📊 Kiểm tra trạng thái", callback_data="auto_status"),
                   types.InlineKeyboardButton("🧪 Test cào ngay", callback_data="auto_testnow"))
        markup.add(types.InlineKeyboardButton("❌ Tắt Auto", callback_data="auto_0"))
        
        bot_caogia.send_message(message.chat.id, f"⚙️ **CÀI ĐẶT LỊCH TỰ ĐỘNG**\nTrạng thái hiện tại: {status_text}\n\n**BƯỚC 1:** Sếp chọn chu kỳ quét trước nhé:", reply_markup=markup, parse_mode="Markdown")

@bot_caogia.callback_query_handler(func=lambda call: call.data.startswith('setauto_'))
def callback_setauto_days(call):
    bot_caogia.answer_callback_query(call.id) # Vá lỗi chớp UI
    days = call.data.split('_')[1]
    markup = types.InlineKeyboardMarkup(row_width=4)
    markup.add(
        types.InlineKeyboardButton("🌅 8h", callback_data=f"auto_{days}_8"),
        types.InlineKeyboardButton("☀️ 12h", callback_data=f"auto_{days}_12"),
        types.InlineKeyboardButton("🌇 16h", callback_data=f"auto_{days}_16"),
        types.InlineKeyboardButton("🌙 20h", callback_data=f"auto_{days}_20")
    )
    bot_caogia.edit_message_text(f"Đã chốt chu kỳ **{days} ngày**.\n\n**BƯỚC 2:** Sếp muốn bot xách dao đi cào vào **khung giờ nào** trong ngày đó?", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

@bot_caogia.callback_query_handler(func=lambda call: call.data.startswith('auto_'))
def callback_auto_config(call):
    action = call.data.replace('auto_', '')
    chat_id = call.message.chat.id
    target_sheet = spreadsheet_caogia.worksheet("Laptop_Gaming")
    
    if action == "status":
        bot_caogia.answer_callback_query(call.id, "Đã cập nhật trạng thái!")
        try:
            days = target_sheet.acell('C1').value
            last_date = target_sheet.acell('B1').value
            hour = target_sheet.acell('E1').value
            if days and str(days).isdigit() and int(days) > 0:
                h_text = f"{hour}:00" if hour else "Không rõ"
                msg = f"📊 **TRẠNG THÁI AUTO-PILOT:**\n• Chu kỳ: Cứ **{days} ngày** quét 1 lần.\n• Khung giờ chốt: **{h_text}**\n• Ngày quét gần nhất: `{last_date}`\n• Trạng thái: Đang tàng hình chờ đến giờ."
            else:
                msg = "📊 **TRẠNG THÁI AUTO-PILOT:** Đang tắt."
        except Exception as e:
            msg = f"❌ Lỗi đọc trạng thái: {e}"
        bot_caogia.send_message(chat_id, msg, parse_mode="Markdown")
        return
        
    if action == "testnow":
        bot_caogia.answer_callback_query(call.id, "Kích hoạt test thủ công...")
        bot_caogia.delete_message(chat_id, call.message.message_id)
        bot_caogia.send_message(chat_id, "🧪 **CHẾ ĐỘ TEST THỦ CÔNG:** Đang kích hoạt...", parse_mode="Markdown")
        # Gửi cờ is_auto=False để nếu bận nó nhả tin nhắn cảnh báo ra chat
        threading.Thread(target=run_scraper_process, args=(chat_id, "all", False)).start()
        return

    if action == "0":
        bot_caogia.answer_callback_query(call.id, "Đã tắt Auto!")
        target_sheet.update_acell('C1', "0")
        bot_caogia.edit_message_text("❌ Đã tắt chế độ cào giá tự động!", chat_id, call.message.message_id, parse_mode="Markdown")
        return
        
    bot_caogia.answer_callback_query(call.id, "Lưu cấu hình thành công!")
    parts = action.split('_')
    if len(parts) == 2:
        days, hour = parts[0], parts[1]
        target_sheet.update_acell('C1', str(days))
        target_sheet.update_acell('D1', str(chat_id))
        target_sheet.update_acell('E1', str(hour))
        bot_caogia.edit_message_text(f"✅ **CHỐT ĐƠN!**\nBot sẽ tự động đi cào giá cứ **{days} ngày 1 lần** vào đúng **{hour}:00**.\n*(Mọi dữ liệu đã được lưu cứng, server sập cũng không quên lịch!)*", chat_id, call.message.message_id, parse_mode="Markdown")

@bot_caogia.callback_query_handler(func=lambda call: call.data.startswith('chart_'))
def callback_chart_query(call):
    item_name = call.data.replace('chart_', '')
    bot_caogia.answer_callback_query(call.id, "Đang vẽ biểu đồ...") 
    bot_caogia.delete_message(call.message.chat.id, call.message.message_id) 
    generate_and_send_chart(call.message.chat.id, item_name)

@bot_caogia.callback_query_handler(func=lambda call: call.data.startswith('scan_'))
def callback_scan_query(call):
    bot_caogia.answer_callback_query(call.id, "Đang khởi động trạm quét...") # Vá lỗi chớp UI
    scan_type = call.data.replace('scan_', '')
    bot_caogia.delete_message(call.message.chat.id, call.message.message_id) 
    threading.Thread(target=run_scraper_process, args=(call.message.chat.id, scan_type)).start()

@bot_caogia.callback_query_handler(func=lambda call: call.data == 'cancel_scrape')
def callback_cancel_scrape(call):
    global cancel_scraping
    bot_caogia.answer_callback_query(call.id, "Đã nhận lệnh phanh gấp!")
    if is_scraping:
        cancel_scraping = True
        bot_caogia.send_message(call.message.chat.id, "🛑 **ĐÃ NHẬN LỆNH HỦY!**\nĐang tiến hành phanh gấp các luồng quét, sếp chờ vài giây nhé...")
    else:
        bot_caogia.send_message(call.message.chat.id, "⚪ Hiện không có tiến trình cào giá nào đang chạy.")

# --- LUỒNG CHẠY AUTO ĐÃ ĐƯỢC CHUẨN HOÁ KHUNG GIỜ ---
def auto_scan_worker():
    while True:
        try:
            target_sheet = spreadsheet_caogia.worksheet("Laptop_Gaming")
            interval_str = str(target_sheet.acell('C1').value).strip()
            chat_id_str = str(target_sheet.acell('D1').value).strip()
            hour_str = str(target_sheet.acell('E1').value).strip()
            
            if interval_str.isdigit() and int(interval_str) > 0 and chat_id_str.isdigit():
                interval_days = int(interval_str)
                chat_id = int(chat_id_str)
                target_hour = int(hour_str) if hour_str.isdigit() else 8
                
                now = datetime.now()
                
                if now.hour == target_hour:
                    date_val = target_sheet.acell('B1').value
                    if date_val:
                        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                            try:
                                last_date = datetime.strptime(date_val, fmt)
                                delta = (now.date() - last_date.date()).days
                                
                                if delta >= interval_days:
                                    bot_caogia.send_message(chat_id, f"⏰ **ĐẾN HẸN LẠI LÊN!**\nĐúng {target_hour}h rồi sếp. Hệ thống Auto-pilot kích hoạt...", parse_mode="Markdown")
                                    run_scraper_process(chat_id, scan_type="all", is_auto=True)
                                break 
                            except: pass
        except Exception as e:
            pass
        time.sleep(3600)

# --- THUẬT TOÁN ĐỘNG CƠ LAI (HYBRID) TỐI THƯỢNG ---
def run_scraper_process(chat_id, scan_type="all", is_auto=False):
    global is_scraping, cancel_scraping
    if is_scraping:
        if not is_auto: 
            bot_caogia.send_message(chat_id, "⚠️ Máy chủ đang kẹt một tiến trình quét khác. Sếp đợi lát hoặc ấn nút Hủy Cào Giá nhé!")
        return
    is_scraping = True
    cancel_scraping = False
    campaign_name = "CẤU HÌNH PC" if scan_type == "pc" else ("LAPTOP GAMING" if scan_type == "laptop" else "TẤT CẢ TÀI NGUYÊN")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🛑 Hủy Cào Giá", callback_data="cancel_scrape"))
    
    prefix = "🤖 [AUTO TỰ ĐỘNG] " if is_auto else "🚀 "
    progress_msg = bot_caogia.send_message(chat_id, f"{prefix}Bắt đầu chiến dịch: **{campaign_name}**\n*(Sử dụng Hybrid Engine - Quét chay Tốc độ cao)*", reply_markup=markup, parse_mode="Markdown")
    
    try:
        link_sheet = spreadsheet_caogia.worksheet("Data_Links")
        tasks = link_sheet.get_all_records()
        valid_tasks = []
        for t in tasks:
            if not str(t.get('URL')).strip() or not str(t.get('Cell')).strip(): continue
            target = str(t.get('Target_Sheet')).strip()
            if scan_type == "pc" and target != "PC_components": continue
            if scan_type == "laptop" and target != "Laptop_Gaming": continue
            valid_tasks.append(t)
            
        if len(valid_tasks) == 0:
            bot_caogia.edit_message_text(f"❌ Không tìm thấy link nào phù hợp!", chat_id, progress_msg.message_id)
            is_scraping = False; return
            
        unique_sheets = set(str(t.get('Target_Sheet')).strip() for t in valid_tasks)
        for s_name in unique_sheets: duplicate_and_push_down(s_name)
        
        tasks_to_run = valid_tasks.copy()
        max_retries = 3
        current_round = 1
        
        while tasks_to_run and current_round <= max_retries and not cancel_scraping:
            failed_tasks = []
            use_api = (current_round > 1) # Quyết định: Vòng 1 quét chay siêu tốc, Vòng 2+ dùng API
            
            if current_round > 1:
                bot_caogia.send_message(chat_id, f"♻️ **VÒNG {current_round} (VÉT LỖI):** Bot chuyển qua API hạng nặng để vượt tường lửa {len(tasks_to_run)} shop khó tính...", parse_mode="Markdown")
                
            report_lines = []
            completed_count = 0
            report_lock = threading.Lock()
            
            def scrape_single_task(task):
                nonlocal completed_count
                if cancel_scraping: return # Phanh gấp lập tức nếu có cờ Hủy
                
                target_sheet_name = str(task.get('Target_Sheet')).strip()
                cell = str(task.get('Cell')).strip()
                url = str(task.get('URL')).strip()
                css = str(task.get('CSS_Selector')).strip()
                item_name = str(task.get('Ten_Linh_Kien', 'Sản phẩm')).strip()
                shop_name = url.split("/")[2] if "//" in url else url[:20]
                target_sheet = spreadsheet_caogia.worksheet(target_sheet_name)
                
                status_icon, result_text = "⏳", "Đang xử lý..."
                is_success = False
                
                try:
                    if use_api:
                        # [PHỤC HỒI TỪ BẢN CŨ] Không dùng render, gọi qua HTTPS
                        payload = {'api_key': SCRAPER_API_KEY, 'url': url}
                        # Giữ timeout 90s để chống đứt gánh giữa chừng
                        response = requests.get('https://api.scraperapi.com/', params=payload, timeout=90)
                    else:
                        # Quét chay trực tiếp siêu tốc (Hybrid Engine)
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                        }
                        response = requests.get(url, headers=headers, timeout=15)
                    
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, 'html.parser')
                        price_element = soup.select_one(css)
                        
                        if price_element:
                            # [PHỤC HỒI TỪ BẢN CŨ] Dùng get_text(strip=True) bóc giá chuẩn xác
                            price = clean_price(price_element.get_text(strip=True))
                            he_so = task.get('He_So', 1) 
                            try: he_so = int(he_so) if str(he_so).strip() != "" else 1
                            except: he_so = 1
                            price = price * he_so
                            
                            val = "LIÊN HỆ" if price == 0 else price
                            target_sheet.update_acell(cell, val)
                            status_icon, price_str = "✅", f"{val:,}".replace(",", ".") + " đ" if isinstance(val, int) else val
                            result_text = f"Xong ({price_str})"
                            is_success = True
                        else:
                            target_sheet.update_acell(cell, "LỖI CSS")
                            status_icon, result_text = "❌", "Lỗi CSS"
                    else:
                        target_sheet.update_acell(cell, "LỖI MẠNG")
                        status_icon, result_text = "⚠️", f"Bị chặn (Lỗi {response.status_code})"
                except Exception as e:
                    target_sheet.update_acell(cell, "LỖI MẠNG")
                    status_icon, result_text = "⚠️", "Lỗi Kết Nối"
                
                with report_lock:
                    if not is_success:
                        failed_tasks.append(task)
                    
                    completed_count += 1
                    report_lines.append(f"{status_icon} [{item_name}] {shop_name}: {result_text}")
                    
                    if completed_count % 3 == 0 or completed_count == len(tasks_to_run) or cancel_scraping:
                        recent_reports = "\n".join(report_lines[-5:])
                        status_text = f"🔄 TIẾN TRÌNH VÒNG {current_round}: [{completed_count}/{len(tasks_to_run)}]\n\nTrạng thái gần nhất:\n{recent_reports}"
                        try: bot_caogia.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=status_text, reply_markup=markup)
                        except: pass
            
            # Vòng 1 quét siêu tốc mở 5 luồng. Vòng 2 dùng API thì chạy 1 luồng để tránh nghẽn.
            workers = 5 if not use_api else 1
            with ThreadPoolExecutor(max_workers=workers) as executor:
                executor.map(scrape_single_task, tasks_to_run)
                
            if failed_tasks and not cancel_scraping:
                current_round += 1
                tasks_to_run = failed_tasks
                if current_round <= max_retries:
                    time.sleep(5)
            else:
                break
                
        if not cancel_scraping:
            final_text = f"✅ **BÁO CÁO SẾP:** Đã chốt xong {campaign_name}!\n\nSố vòng quét đã chạy: {min(current_round, max_retries)}\nSố lượng shop bị xịt hoàn toàn: {len(failed_tasks)}\nBảng giá đã được cập nhật thành công!"
            try: bot_caogia.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=final_text, parse_mode="Markdown")
            except: bot_caogia.send_message(chat_id, final_text, parse_mode="Markdown")
    except Exception as e:
         error_detail = traceback.format_exc()
         bot_caogia.send_message(chat_id, f"❌ Sếp ơi code gãy rồi! Chi tiết:\n\n```python\n{error_detail[-3500:]}\n```", parse_mode="Markdown")
    finally:
        is_scraping = False


# =========================================================================
# KHU VỰC 3: BOT LƯƠNG JOHNNY
# =========================================================================
TOKEN_JOHNNY = os.getenv("TOKEN_JOHNNY", "8611295413:AAFhA75QnwPR6zWvuouHDZEZKeRKkHEA_d4")
bot_johnny = telebot.TeleBot(TOKEN_JOHNNY)

FILE_SHEET_NAME_JOHNNY = os.getenv("FILE_SHEET_NAME_JOHNNY", "Piscey_Salary_Tracker")
FILE_KEY_JSON_JOHNNY = 'creds_chamcong.json'

creds_chamcong = ServiceAccountCredentials.from_json_keyfile_name(FILE_KEY_JSON_JOHNNY, scope)
client_johnny = gspread.authorize(creds_chamcong)
spreadsheet_johnny = client_johnny.open(FILE_SHEET_NAME_JOHNNY)

sheet_data = spreadsheet_johnny.worksheet("Data")
sheet_dash = spreadsheet_johnny.worksheet("Dashboard")
sheet_hist = spreadsheet_johnny.worksheet("History")
sheet_budget = spreadsheet_johnny.worksheet("Budget") 
sheet_goals = spreadsheet_johnny.worksheet("Goals")

pending_add = {}

def format_vnd(amount):
    return f"{amount:,}".replace(',', '.')

def parse_money_johnny(s):
    s = s.replace(',', '.').replace(' ', '').lower()
    s = s.replace('tỷ', 'ty').replace('củ', 'tr').replace('lít', 'lit').replace('loét', 'lit').replace('rưỡi', '5').replace('ruoi', '5') 
    if 'ty' in s:
        parts = s.split('ty')
        ty_val = int(re.sub(r'[^\d]', '', parts[0])) * 1000000000 if parts[0] else 0
        after_ty = re.sub(r'[^\d]', '', parts[1])
        after_val = int(after_ty.ljust(9, '0')[:9]) if after_ty else 0
        return ty_val + after_val
    elif 'tr' in s:
        parts = s.split('tr')
        tr_val = int(re.sub(r'[^\d]', '', parts[0])) * 1000000 if parts[0] else 0
        after_tr = re.sub(r'[^\d]', '', parts[1])
        after_val = int(after_tr.ljust(6, '0')[:6]) if after_tr else 0
        return tr_val + after_val
    elif 'lit' in s:
        parts = s.split('lit')
        lit_val = int(re.sub(r'[^\d]', '', parts[0])) * 100000 if parts[0] else 0
        after_lit = re.sub(r'[^\d]', '', parts[1])
        after_val = int(after_lit.ljust(5, '0')[:5]) if after_lit else 0
        return lit_val + after_val
    elif 'k' in s:
        parts = s.split('k')
        k_val = int(re.sub(r'[^\d]', '', parts[0])) * 1000 if parts[0] else 0
        after_k = re.sub(r'[^\d]', '', parts[1])
        after_val = int(after_k.ljust(3, '0')[:3]) if after_k else 0
        return k_val + after_val
    else:
        clean_s = re.sub(r'(đ|d|vnd)$', '', s)
        if re.search(r'[a-z]', clean_s): return 0
        val = re.sub(r'[^\d]', '', clean_s)
        return int(val) if val else 0

def reindex_budget_sheet(target_ky_luong):
    all_rows = sheet_budget.get_all_values()
    if len(all_rows) <= 1: return
    matching_rows = []
    for idx, row in enumerate(all_rows[1:], start=2):
        if len(row) >= 2 and row[1] == target_ky_luong: matching_rows.append((idx, row))
    for stt, (original_idx, row) in enumerate(matching_rows, start=1):
        if not row[0]: continue
        year_prefix = row[0][:2] 
        month_part = target_ky_luong.replace("Tháng ", "").split('/')[0]
        new_id = f"{year_prefix}{month_part}-{stt:02d}" 
        if row[0] != new_id: sheet_budget.update_cell(original_idx, 1, f"'{new_id}")

def main_menu_johnny():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(types.KeyboardButton('📊 Báo Cáo Tài Chính'), types.KeyboardButton('💸 Tình Hình Thu Chi'), types.KeyboardButton('📈 Thống Kê & Mục Tiêu'), types.KeyboardButton('🗑️ Xoá Khoản Chi'), types.KeyboardButton('ℹ️ Hướng dẫn'))
    return markup

@bot_johnny.message_handler(commands=['start'])
def send_welcome_johnny(message):
    bot_johnny.reply_to(message, "🌟 Chào Hoàn! Tôi đã sẵn sàng trợ giúp ông quản lý, theo dõi giờ làm, tiền lương và kế hoạch thu chi.", reply_markup=main_menu_johnny())

@bot_johnny.message_handler(func=lambda message: message.text in ['📊 Báo Cáo Tài Chính', '📊 Xem Lương Dự Kiến', '/check'])
def check_salary(message):
    try:
        now = datetime.now()
        b1_val = sheet_dash.acell('B1').value 
        b2_val = sheet_dash.acell('B2').value 
        d1, m1 = map(int, b1_val.split('/'))
        d2, m2 = map(int, b2_val.split('/'))
        y1 = now.year
        y2 = now.year if m2 >= m1 else now.year + 1
        start_date = datetime(y1, m1, d1)
        end_date = datetime(y2, m2, d2)
        try:
            cell_tong_luong = sheet_dash.find("Tổng lương thực nhận sau BHXH")
            luong_raw = sheet_dash.cell(cell_tong_luong.row, 2).value
        except: luong_raw = "0"
        if now.date() > end_date.date():
            ten_ky_luong = f"Tháng {end_date.month:02d} ({start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')})"
            luong_du_tinh = int(re.sub(r'[^\d]', '', str(luong_raw))) if luong_raw else 0
            col_a = sheet_hist.col_values(1)
            next_row = len(col_a) + 1
            row_to_write = next_row
            for i, val in enumerate(col_a):
                if val == ten_ky_luong:
                    row_to_write = i + 1; break
            sheet_hist.update_cell(row_to_write, 1, ten_ky_luong)
            sheet_hist.update_cell(row_to_write, 2, luong_du_tinh) 
            if row_to_write == next_row: sheet_hist.update_cell(row_to_write, 5, "Chờ xác nhận ⏳")
            new_start = end_date + timedelta(days=1)
            new_end = new_start + relativedelta(months=1) - timedelta(days=1)
            sheet_dash.update_cell(1, 2, new_start.strftime("%d/%m"))
            sheet_dash.update_cell(2, 2, new_end.strftime("%d/%m"))
            bot_johnny.send_message(message.chat.id, f"🎊 **KẾT THÚC KỲ LƯƠNG!**\n✅ Đã tự động chốt {ten_ky_luong} vào sổ cái. Trạng thái: Chờ ting ting!", parse_mode='Markdown')
            start_date, end_date = new_start, new_end
            b2_val = new_end.strftime("%d/%m")
            time.sleep(2)
            try:
                cell_tong_luong = sheet_dash.find("Tổng lương thực nhận sau BHXH")
                thuc_nhan = sheet_dash.cell(cell_tong_luong.row, 2).value
            except: thuc_nhan = "0 đ"
        else: thuc_nhan = luong_raw 
        luong_ky_truoc = sheet_dash.acell('E3').value
        def get_payday(target_month, target_year):
            payday = datetime(target_year, target_month, 10).date()
            if payday.weekday() == 5: payday -= timedelta(days=1)
            elif payday.weekday() == 6: payday += timedelta(days=1)
            return payday
        thang_nay = end_date.month
        thang_truoc = thang_nay - 1 if thang_nay > 1 else 12
        payday_truoc = get_payday(end_date.month, end_date.year) 
        next_month = end_date.month + 1 if end_date.month < 12 else 1
        next_year = end_date.year if end_date.month < 12 else end_date.year + 1
        payday_nay = get_payday(next_month, next_year) 
        ngay_chot_luong = max(0, (end_date.date() - now.date()).days)
        delta_nhan_nay = (payday_nay - now.date()).days
        try:
            clean_luong_truoc = int(re.sub(r'[^\d]', '', str(luong_ky_truoc))) if luong_ky_truoc else 0
            all_hist = sheet_hist.get_all_values()
            for i in range(len(all_hist)-1, 0, -1):
                row = all_hist[i]
                if row[0].startswith(f"Tháng {thang_truoc} ") or row[0].startswith(f"Tháng 0{thang_truoc} "):
                    current_du_tinh_in_hist = int(re.sub(r'[^\d]', '', str(row[1]))) if row[1] else 0
                    if current_du_tinh_in_hist != clean_luong_truoc: sheet_hist.update_cell(i + 1, 2, clean_luong_truoc)
                    break
        except: pass 
        response = "💰 **BÁO CÁO TÀI CHÍNH**\n━━━━━━━━━━━━━━━━━━\n"
        if now.date() <= payday_truoc:
            delta_nhan_truoc = (payday_truoc - now.date()).days
            txt_ngay_ve_truoc = f"🎉 **Hôm nay lương về đấy!** ({payday_truoc.strftime('%d/%m/%Y')})" if delta_nhan_truoc == 0 else f"Còn {delta_nhan_truoc} ngày ({payday_truoc.strftime('%d/%m/%Y')})"
            response += f"📦 **Lương Tháng {thang_truoc}:** `{luong_ky_truoc}`\n📅 **Ngày lương về:** {txt_ngay_ve_truoc}\n━━━━━━━━━━━━━━━━━━\n"
        txt_chot = f"⚠️ **Hôm nay là hạn chốt sổ công rồi nhé! ({b2_val})**" if ngay_chot_luong == 0 else f"⏳ Còn {ngay_chot_luong} ngày nữa là tới ngày chốt lương! ({b2_val})"
        txt_du_kien = f"🎉 **Hôm nay nhận lương tháng này rồi!** ({payday_nay.strftime('%d/%m/%Y')})" if delta_nhan_nay == 0 else f"Còn {delta_nhan_nay} ngày ({payday_nay.strftime('%d/%m/%Y')})"
        response += f"🏃 **Lương Tháng {thang_nay}:** `{thuc_nhan}`\n{txt_chot}\n📅 **Dự kiến nhận:** {txt_du_kien}\n━━━━━━━━━━━━━━━━━━\n🚀 *Cố gắng lên, sắp đến ngày 'lúa về' rồi!*"
        bot_johnny.send_message(message.chat.id, response, parse_mode='Markdown', reply_markup=main_menu_johnny())
    except Exception as e:
        bot_johnny.send_message(message.chat.id, f"❌ Lỗi: {e}")

def get_months_keyboard(months, page, prefix="del", items_per_page=6):
    markup = types.InlineKeyboardMarkup(row_width=2)
    total_pages = max(1, (len(months) - 1) // items_per_page + 1)
    start_idx = page * items_per_page; end_idx = start_idx + items_per_page
    for m in months[start_idx:end_idx]:
        markup.add(types.InlineKeyboardButton(m, callback_data=f"{prefix}month_{m.replace('Tháng ', '')}"))
    nav_buttons = []
    if page > 0: nav_buttons.append(types.InlineKeyboardButton("⬅️ Trước", callback_data=f"{prefix}page_{page-1}"))
    if page < total_pages - 1: nav_buttons.append(types.InlineKeyboardButton("Sau ➡️", callback_data=f"{prefix}page_{page+1}"))
    if nav_buttons: markup.row(*nav_buttons) 
    markup.add(types.InlineKeyboardButton("❌ Huỷ thao tác", callback_data=f"{prefix}cancel"))
    return markup

@bot_johnny.message_handler(func=lambda message: message.text == '💸 Tình Hình Thu Chi')
def prompt_budget_month(message):
    msg_loading = bot_johnny.reply_to(message, "⏳ Đợi em xíu để em tổng hợp các tháng nhé...")
    try:
        all_rows = sheet_budget.get_all_values()
        months = []
        for row in all_rows[1:]:
            if len(row) >= 2 and row[1].startswith("Tháng") and row[1] not in months: months.append(row[1])
        now = datetime.now()
        current_m_str = f"Tháng {now.month:02d}/{now.year}"
        if current_m_str not in months: months.append(current_m_str)
        def sort_key(m_str):
            try: m, y = map(int, m_str.replace("Tháng ", "").split('/')); return y, m
            except: return 0, 0
        months.sort(key=sort_key)
        page = months.index(current_m_str) // 6 if current_m_str in months else max(0, (len(months) - 1) // 6)
        markup = get_months_keyboard(months, page, prefix="view")
        bot_johnny.edit_message_text("Sếp muốn xem Kế hoạch thu chi của **kỳ chi tiêu nào**?", message.chat.id, msg_loading.message_id, reply_markup=markup, parse_mode='Markdown')
    except Exception as e:
        bot_johnny.edit_message_text(f"❌ Lỗi: {e}", message.chat.id, msg_loading.message_id)

@bot_johnny.callback_query_handler(func=lambda call: call.data.startswith('viewmonth_') or call.data.startswith('viewpage_') or call.data == 'viewcancel')
def handle_inline_view(call):
    bot_johnny.answer_callback_query(call.id)
    chat_id = call.message.chat.id; msg_id = call.message.message_id
    if call.data == 'viewcancel':
        bot_johnny.edit_message_text("❌ **Đã huỷ thao tác xem báo cáo!**", chat_id, msg_id, parse_mode='Markdown')
        return
    if call.data.startswith('viewpage_'):
        page = int(call.data.split('_')[1])
        try:
            all_rows = sheet_budget.get_all_values()
            months = []
            for row in all_rows[1:]:
                if len(row) >= 2 and row[1].startswith("Tháng") and row[1] not in months: months.append(row[1])
            now = datetime.now()
            current_m_str = f"Tháng {now.month:02d}/{now.year}"
            if current_m_str not in months: months.append(current_m_str)
            def sort_key(m_str):
                try: m, y = map(int, m_str.replace("Tháng ", "").split('/')); return y, m
                except: return 0, 0
            months.sort(key=sort_key)
            markup = get_months_keyboard(months, page, prefix="view")
            bot_johnny.edit_message_text("Sếp muốn xem Kế hoạch thu chi của **kỳ lương nào**?", chat_id, msg_id, reply_markup=markup, parse_mode='Markdown')
        except Exception as e:
            bot_johnny.edit_message_text(f"❌ Lỗi chuyển trang: {e}", chat_id, msg_id)
        return
    if call.data.startswith('viewmonth_'):
        month_val = call.data.split('_')[1] 
        bot_johnny.edit_message_text(f"⏳ Dạ sếp! Đợi em vài giây để em lôi sổ cái **Tháng {month_val}** ra báo cáo nhé...", chat_id, msg_id, parse_mode='Markdown')
        generate_budget_report(chat_id, month_val)

@bot_johnny.message_handler(func=lambda message: re.match(r'(?i)thu chi\s*(t|tháng\s*)(\d{1,2})(?:/|\s+)?(\d{4}|\d{2})?\b', message.text))
def text_budget_report(message):
    match = re.match(r'(?i)thu chi\s*(t|tháng\s*)(\d{1,2})(?:/|\s+)?(\d{4}|\d{2})?\b', message.text)
    if match:
        m_val = int(match.group(2)); y_val = match.group(3); now = datetime.now()
        if y_val:
            y = int(y_val)
            if y < 100: y += 2000
        else:
            y = now.year
            if m_val == 12 and now.month == 1: y -= 1
            elif m_val == 1 and now.month == 12: y += 1
        generate_budget_report(message.chat.id, f"{m_val:02d}/{y}")

def generate_budget_report(chat_id, month_str):
    try:
        m_part, y_part = map(int, month_str.split('/'))
        current_ky_luong = f"Tháng {m_part:02d}/{y_part}" 
        now = datetime.now()
        prev_m = m_part - 1 if m_part > 1 else 12
        prev_y = y_part if m_part > 1 else y_part - 1
        luong_thang_truoc = 0
        note_luong = ""
        all_hist = sheet_hist.get_all_values()
        for row in all_hist[1:]:
            if len(row) > 0 and (row[0].startswith(f"Tháng {prev_m:02d}") or row[0].startswith(f"Tháng {prev_m} ")):
                thuc_nhan_str = row[2] if len(row) > 2 else ""
                du_tinh_str = row[1] if len(row) > 1 else ""
                if thuc_nhan_str and str(thuc_nhan_str).strip() != "":
                    luong_thang_truoc = int(re.sub(r'[^\d]', '', str(thuc_nhan_str)))
                    note_luong = "(Đã thực nhận 💸)"
                else:
                    try: luong_thang_truoc = int(re.sub(r'[^\d]', '', str(du_tinh_str)))
                    except: luong_thang_truoc = 0
                    note_luong = "(Dự kiến từ sổ cái 📦)"
                break
        if luong_thang_truoc == 0:
            b2_val = sheet_dash.acell('B2').value
            _, m_dash = map(int, b2_val.split('/'))
            if prev_m == m_dash and prev_y == now.year:
                try:
                    cell_tong_luong = sheet_dash.find("Tổng lương thực nhận sau BHXH")
                    luong_raw = sheet_dash.cell(cell_tong_luong.row, 2).value
                    luong_thang_truoc = int(re.sub(r'[^\d]', '', str(luong_raw))) if luong_raw else 0
                    note_luong = "(Đang cày cuốc 🏃)"
                except: pass
            else: note_luong = "(Chưa có dữ liệu lương ⏳)"
        all_rows = sheet_budget.get_all_values()
        danh_sach_chi = []
        tong_du_chi = 0; da_thanh_toan = 0
        for row in all_rows[1:]:
            if len(row) >= 5 and row[1] == current_ky_luong:
                m_id = row[0].replace("'", "")
                ten = row[2]
                try: tien = int(re.sub(r'[^\d]', '', str(row[3])))
                except: tien = 0
                trang_thai = row[4]
                tong_du_chi += tien
                if "✅" in trang_thai or "xong" in trang_thai.lower():
                    da_thanh_toan += tien; icon = "🟩"
                else: icon = "🟥"
                danh_sach_chi.append(f"{icon} `[{m_id}]` {ten}: `{format_vnd(tien)} đ` ({trang_thai})")
        payday_start = datetime(y_part, m_part, 10).date()
        if payday_start.weekday() == 5: payday_start -= timedelta(days=1)
        elif payday_start.weekday() == 6: payday_start += timedelta(days=1)
        pm_end = m_part + 1 if m_part < 12 else 1
        py_end = y_part if m_part < 12 else y_part + 1
        payday_end = datetime(py_end, pm_end, 10).date()
        if payday_end.weekday() == 5: payday_end -= timedelta(days=1)
        elif payday_end.weekday() == 6: payday_end += timedelta(days=1)
        tien_tu_do = luong_thang_truoc - tong_du_chi
        response = f"💸 **KẾ HOẠCH CHI TIÊU - NGÂN SÁCH THÁNG {m_part:02d}/{y_part}**\n━━━━━━━━━━━━━━━━━━\n"
        response += f"💵 **Vốn từ Kỳ Lương T{prev_m:02d}:** `{format_vnd(luong_thang_truoc)} đ` {note_luong}\n\n"
        response += "📝 **CÁC KHOẢN DỰ CHI:**\n" + ("\n".join(danh_sach_chi) + "\n" if danh_sach_chi else "Chưa có kế hoạch chi tiêu nào.\n")
        response += "━━━━━━━━━━━━━━━━━━\n"
        response += f"➖ Tổng dự chi T{m_part}: `{format_vnd(tong_du_chi)} đ`\n➖ Đã thanh toán: `{format_vnd(da_thanh_toan)} đ`\n\n"
        response += f"💰 **TIỀN TỰ DO CÒN LẠI:** **`{format_vnd(tien_tu_do)} đ`**\n"
        if now.date() < payday_start:
            total_days = (payday_end - payday_start).days
            if tien_tu_do >= 0: response += f"*(⏳ Ngân sách này sẽ kích hoạt vào {payday_start.strftime('%d/%m')} -> Mức tiêu dự kiến: **{format_vnd(tien_tu_do // total_days)} đ/ngày**)*"
            else: response += "*(⚠️ BÁO ĐỘNG: Quỹ chi tiêu tương lai đang bị âm tiền!)*"
        elif payday_start <= now.date() < payday_end:
            total_days_in_period = (payday_end - payday_start).days 
            delta_nhan_nay = (payday_end - now.date()).days 
            if tien_tu_do >= 0:
                muc_tieu_goc = tien_tu_do // total_days_in_period
                muc_tieu_thuc_te = tien_tu_do // delta_nhan_nay
                response += f"*(💡 Mốc tiêu vặt an toàn cố định của kỳ này là: **{format_vnd(muc_tieu_goc)} đ/ngày**)*\n"
                if muc_tieu_thuc_te < muc_tieu_goc: response += f"*(⚠️ Sếp ơi, những ngày qua tiêu hơi lẹm rồi đấy! Hạn mức thực tế còn lại chỉ là: **{format_vnd(muc_tieu_thuc_te)} đ/ngày** thôi, thắt lưng buộc bụng lại nhé!)*"
                else: response += f"*(🎉 Phong độ tốt! Hạn mức thực tế còn lại của sếp vẫn đang ở mức an toàn: **{format_vnd(muc_tieu_thuc_te)} đ/ngày**)*"
            else: response += "*(⚠️ BÁO ĐỘNG ĐỎ: Quỹ chi tiêu tháng này đang vượt mức lương sếp ơi!)*"
        else: response += "*(🎉 Kỳ ngân sách này đã qua ngày thanh toán!)*"
        bot_johnny.send_message(chat_id, response, parse_mode='Markdown')
    except Exception as e:
        bot_johnny.send_message(chat_id, f"❌ Lỗi tải báo cáo thu chi: {e}")

@bot_johnny.message_handler(func=lambda message: 'xoá' in message.text.lower() or 'xóa' in message.text.lower())
def delete_process(message):
    text = message.text.strip().lower()
    if 'xoá khoản chi' in text or 'xóa khoản chi' in text:
        msg_loading = bot_johnny.reply_to(message, "⏳ Đợi em quét sổ xem có những tháng nào nhé...")
        try:
            all_rows = sheet_budget.get_all_values()
            months = []
            for row in all_rows[1:]:
                if len(row) >= 2 and row[1].startswith("Tháng") and row[1] not in months: months.append(row[1])
            if not months:
                bot_johnny.edit_message_text("Bảng thu chi đang trống trơn, không có khoản nào để xoá sếp ơi!", message.chat.id, msg_loading.message_id)
                return
            def sort_key(m_str):
                try: m, y = map(int, m_str.replace("Tháng ", "").split('/')); return y, m
                except: return 0, 0
            months.sort(key=sort_key)
            now = datetime.now()
            current_m_str = f"Tháng {now.month:02d}/{now.year}"
            page = months.index(current_m_str) // 6 if current_m_str in months else max(0, (len(months) - 1) // 6)
            markup = get_months_keyboard(months, page, prefix="del")
            bot_johnny.edit_message_text("Sếp muốn xoá khoản chi của **kỳ lương nào**?\n*(Hoặc gõ trực tiếp `Xoá [Mã ID]` nếu khoản ở trang quá xa)*", message.chat.id, msg_loading.message_id, reply_markup=markup, parse_mode='Markdown')
        except Exception as e:
            bot_johnny.edit_message_text(f"❌ Lỗi: {e}", message.chat.id, msg_loading.message_id)
        return

    if text == '🗑️ xoá ngày nhầm' or 'xoá ngày nhầm' in text or 'xóa ngày nhầm' in text:
        bot_johnny.reply_to(message, "💡 **Cách xoá ngày công:** Nhắn: `Xoá [Ngày/Tháng]` (VD: `Xoá 12/4`)\n💡 **Cách xoá khoản chi:** Nhắn: `Xoá [Mã ID]` (VD: `Xoá 2606-01`)", parse_mode='Markdown')
        return

    id_match = re.search(r'(\d{4}-?\d{2})', text)
    if id_match:
        try:
            target_id = id_match.group(1)
            if '-' not in target_id: target_id = f"{target_id[:4]}-{target_id[4:]}"
            all_rows = sheet_budget.get_all_values()
            row_index = -1; target_ky_luong = ""
            for i, row in enumerate(all_rows):
                if len(row) > 0 and row[0].replace("'", "") == target_id:
                    row_index = i + 1; target_ky_luong = row[1]; break
            if row_index == -1: bot_johnny.reply_to(message, f"❓ Không tìm thấy mã khoản chi `{target_id}` để xoá.")
            else:
                ten_khoan_chi_cu = all_rows[row_index-1][2]
                sheet_budget.delete_rows(row_index)
                reindex_budget_sheet(target_ky_luong) 
                sheet_budget.sort((1, 'asc'), range='A2:F1000') 
                bot_johnny.reply_to(message, f"🗑️ Đã xoá khoản chi **{ten_khoan_chi_cu}** `{target_id}`.\n✨ Số thứ tự các mã ID còn lại đã được tự động sắp xếp cuốn chiếu gọn gàng!", parse_mode='Markdown')
            return
        except Exception as e:
            bot_johnny.reply_to(message, f"❌ Lỗi khi xoá khoản chi: {e}")
            return

    try:
        now = datetime.now()
        date_match = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?', text)
        if 'hôm nay' in text or 'nay' in text: dt_obj = datetime(now.year, now.month, now.day)
        elif date_match:
            d, m, y = date_match.group(1), date_match.group(2), date_match.group(3)
            y = f"20{y}" if y and len(y) == 2 else (y if y else str(now.year))
            dt_obj = datetime(int(y), int(m), int(d))
        else:
            bot_johnny.reply_to(message, "⚠️ Ông muốn xoá ngày nào? Nhớ kèm ngày nhé. VD: `Xoá 15/4`")
            return
        target_date_str = dt_obj.strftime("%d/%m/%Y")
        all_dates = sheet_data.col_values(1)
        row_index = -1
        for i, d_str in enumerate(all_dates):
            if not d_str or i < 2: continue
            try:
                for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d/%m"):
                    try:
                        clean_d = d_str.split()[0]
                        if datetime.strptime(clean_d, fmt).date() == dt_obj.date(): row_index = i + 1; break
                    except: continue
                if row_index != -1: break
            except: continue
        if row_index == -1: bot_johnny.reply_to(message, f"❓ Không tìm thấy dữ liệu ngày {dt_obj.strftime('%d/%m')} để xoá.")
        else:
            sheet_data.delete_rows(row_index)
            sheet_data.sort((1, 'asc'), range='A3:I1000')
            bot_johnny.reply_to(message, f"🗑️ Đã xoá sạch dòng dữ liệu ngày **{dt_obj.strftime('%d/%m/%Y')}**.\n✨ Bảng tính đã được dọn dẹp và sắp xếp lại!", parse_mode='Markdown')
    except Exception as e:
        bot_johnny.reply_to(message, f"❌ Lỗi khi xoá: {e}")

@bot_johnny.message_handler(func=lambda message: re.match(r'(?i)lương thực nhận\s*(tháng|t)\s*\d+', message.text))
def confirm_actual_salary(message):
    try:
        text = message.text.lower()
        month_match = re.search(r'(?:tháng|t)\s*(\d{1,2})', text)
        if not month_match: return
        target_month = int(month_match.group(1))
        amount_str = text.split(':')[-1].strip() if ':' in text else text[month_match.end():].strip()
        is_clear = amount_str in ['0', 'xóa', 'xoá', 'clear', 'trống']
        actual_money = 0 if is_clear else parse_money_johnny(amount_str)
        all_rows = sheet_hist.get_all_values()
        target_row = -1
        for i in range(1, len(all_rows)):
            if all_rows[i][0].startswith(f"Tháng {target_month} ") or all_rows[i][0].startswith(f"Tháng 0{target_month} "):
                target_row = i + 1; break
        if target_row != -1:
            if is_clear:
                sheet_hist.update_cell(target_row, 3, "")
                sheet_hist.update_cell(target_row, 5, "Chờ xác nhận ⏳")
                msg = f"🧹 Đã xóa lương thực nhận Tháng {target_month}."
            else:
                sheet_hist.update_cell(target_row, 3, actual_money)
                now = datetime.now()
                payday_month = target_month + 1 if target_month < 12 else 1
                payday_year = now.year if target_month < 12 else now.year + 1
                payday = datetime(payday_year, payday_month, 10).date()
                if payday.weekday() == 5: payday -= timedelta(days=1)
                elif payday.weekday() == 6: payday += timedelta(days=1)
                trang_thai = "Đã xong ✅" if now.date() >= payday else "Chờ mùng 10 ting ting ⏳"
                sheet_hist.update_cell(target_row, 5, trang_thai)
                msg = f"✅ Đã cập nhật lương Tháng {target_month}."
        else:
            if not is_clear:
                now = datetime.now()
                end_year = now.year - 1 if target_month > now.month + 3 else now.year
                start_month = 12 if target_month == 1 else target_month - 1
                start_year = end_year - 1 if target_month == 1 else end_year
                ten_ky_luong = f"Tháng {target_month:02d} (26/{start_month:02d}/{start_year} - 25/{target_month:02d}/{end_year})"
                sheet_hist.append_row([ten_ky_luong, 0, actual_money, "", "Đã xong ✅"])
                msg = f"📝 Đã tạo mới và chốt sổ:\n`{ten_ky_luong}`\n(Lương dự tính mặc định: 0 đ)"
            else: msg = f"⚠️ Không tìm thấy Tháng {target_month} để xóa."
        total_rows = len(sheet_hist.get_all_values())
        if total_rows >= 2: sheet_hist.sort((1, 'asc'), range=f'A2:E{total_rows}')
        bot_johnny.reply_to(message, msg + "\n✨ Sổ cái đã được đồng bộ và sắp xếp lại!")
    except Exception as e:
        bot_johnny.reply_to(message, f"❌ Lỗi: {e}")

@bot_johnny.message_handler(func=lambda message: message.text == '📈 Thống Kê & Mục Tiêu')
def show_stats_menu(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("📅 Thống kê theo Tháng", callback_data="stats_list_month"), types.InlineKeyboardButton(f"📆 Thống kê Năm nay ({datetime.now().year})", callback_data=f"stats_year_{datetime.now().year}"), types.InlineKeyboardButton("🎯 Thống kê Mục tiêu & Hashtag", callback_data="stats_list_hash"), types.InlineKeyboardButton("❌ Huỷ", callback_data="stats_cancel"))
    bot_johnny.reply_to(message, "📊 Sếp muốn xuất báo cáo thống kê theo dạng nào?", reply_markup=markup)

@bot_johnny.callback_query_handler(func=lambda call: call.data.startswith('stats_') or call.data.startswith('view_hash_') or call.data.startswith('stmonth_'))
def handle_stats(call):
    bot_johnny.answer_callback_query(call.id)
    chat_id = call.message.chat.id; msg_id = call.message.message_id
    if call.data == 'stats_cancel':
        bot_johnny.edit_message_text("❌ **Đã huỷ menu thống kê!**", chat_id, msg_id, parse_mode='Markdown')
        return
    if call.data.startswith('stats_year_'):
        target_year = call.data.split('_')[2]
        bot_johnny.edit_message_text(f"⏳ Đang tổng hợp dữ liệu thu chi cả năm {target_year}...", chat_id, msg_id)
        try:
            tong_thu = 0; tong_chi_thuc = 0
            for row in sheet_hist.get_all_values()[1:]:
                if len(row) > 0 and str(target_year) in row[0]:
                    tien_str = row[2] if len(row) > 2 and row[2].strip() else (row[1] if len(row) > 1 else "0")
                    try: tong_thu += int(re.sub(r'[^\d]', '', str(tien_str)))
                    except: pass
            for row in sheet_budget.get_all_values()[1:]:
                if len(row) >= 5 and f"/{target_year}" in row[1] and ("✅" in row[4] or "xong" in row[4].lower()):
                    try: tong_chi_thuc += int(re.sub(r'[^\d]', '', str(row[3])))
                    except: pass
            msg = f"📆 **BỨC TRANH TÀI CHÍNH NĂM {target_year}**\n━━━━━━━━━━━━━━━━━━\n💵 **Tổng cày cuốc:** `{format_vnd(tong_thu)} đ`\n💸 **Đã thực chi:** `{format_vnd(tong_chi_thuc)} đ`\n"
            bot_johnny.edit_message_text(msg, chat_id, msg_id, parse_mode='Markdown')
        except Exception as e:
            bot_johnny.edit_message_text(f"❌ Lỗi tính toán năm: {e}", chat_id, msg_id)
    elif call.data == 'stats_list_month':
        bot_johnny.edit_message_text("⏳ Đang tải danh sách các tháng...", chat_id, msg_id)
        try:
            months = list(set([row[1] for row in sheet_budget.get_all_values()[1:] if len(row) >= 2 and row[1].startswith("Tháng")]))
            def sort_key(m_str):
                try: m, y = map(int, m_str.replace("Tháng ", "").split('/')); return y, m
                except: return 0, 0
            months.sort(key=sort_key, reverse=True)
            if not months:
                bot_johnny.edit_message_text("⚠️ Chưa có dữ liệu tháng nào trong sổ!", chat_id, msg_id)
                return
            markup = types.InlineKeyboardMarkup(row_width=3)
            markup.add(*[types.InlineKeyboardButton(m.replace("Tháng ", ""), callback_data=f"stmonth_{m.replace('Tháng ', '')}") for m in months[:12]])
            markup.add(types.InlineKeyboardButton("❌ Huỷ", callback_data="stats_cancel"))
            bot_johnny.edit_message_text("📅 **Chọn tháng sếp muốn xem tổng quan:**", chat_id, msg_id, reply_markup=markup, parse_mode='Markdown')
        except Exception as e:
            bot_johnny.edit_message_text(f"❌ Lỗi tải danh sách tháng: {e}", chat_id, msg_id)
    elif call.data.startswith('stmonth_'):
        target_ky = f"Tháng {call.data.replace('stmonth_', '')}"
        bot_johnny.edit_message_text(f"⏳ Đang tổng hợp dữ liệu **{target_ky}**...", chat_id, msg_id, parse_mode='Markdown')
        try:
            tong_thu = 0; tong_chi = 0
            for row in sheet_hist.get_all_values()[1:]:
                if row[0].startswith(target_ky) or row[0].startswith(target_ky.replace("Tháng ", "Tháng 0")):
                    tien_str = row[2] if len(row) > 2 and row[2].strip() else (row[1] if len(row) > 1 else "0")
                    try: tong_thu = int(re.sub(r'[^\d]', '', str(tien_str)))
                    except: pass
                    break
            for row in sheet_budget.get_all_values()[1:]:
                if len(row) >= 5 and row[1] == target_ky and ("✅" in row[4] or "xong" in row[4].lower()):
                    try: tong_chi += int(re.sub(r'[^\d]', '', str(row[3])))
                    except: pass
            msg = f"📅 **THỐNG KÊ {target_ky}**\n━━━━━━━━━━━━━━━━━━\n💵 **Thu nhập:** `{format_vnd(tong_thu)} đ`\n💸 **Đã thực chi:** `{format_vnd(tong_chi)} đ`\n"
            bot_johnny.edit_message_text(msg, chat_id, msg_id, parse_mode='Markdown')
        except Exception as e:
            bot_johnny.edit_message_text(f"❌ Lỗi báo cáo tháng: {e}", chat_id, msg_id)
    elif call.data == 'stats_list_hash':
        bot_johnny.edit_message_text("⏳ Đang quét sổ cái tìm các Hashtag sếp đã đặt ra...", chat_id, msg_id)
        try:
            hash_goals = [row[0].strip() for row in sheet_goals.get_all_values()[1:] if len(row) > 0 and row[0].strip().startswith('#')]
            hash_budget = [row[5].strip() for row in sheet_budget.get_all_values()[1:] if len(row) > 5 and row[5].strip().startswith('#')]
            hashtags = list(set(hash_goals + hash_budget))
            if not hashtags:
                bot_johnny.edit_message_text("⚠️ Sổ của sếp chưa có Hashtag nào cả!", chat_id, msg_id)
                return
            markup = types.InlineKeyboardMarkup(row_width=2)
            for ht in hashtags: markup.add(types.InlineKeyboardButton(ht, callback_data=f"view_hash_{ht}"))
            markup.add(types.InlineKeyboardButton("❌ Huỷ", callback_data="stats_cancel"))
            bot_johnny.edit_message_text("🎯 **Chọn Hashtag/Mục tiêu sếp muốn xem tiến độ:**", chat_id, msg_id, reply_markup=markup, parse_mode='Markdown')
        except Exception as e:
            bot_johnny.edit_message_text(f"❌ Lỗi lấy danh sách Hashtag: {e}", chat_id, msg_id)
    elif call.data.startswith('view_hash_'):
        target_hash = call.data.replace('view_hash_', '')
        bot_johnny.edit_message_text(f"⏳ Đang tính toán dữ liệu thu chi cho hashtag...", chat_id, msg_id)
        try:
            muc_tieu_tien = 0; ten_muc_tieu = ""
            for row in sheet_goals.get_all_values()[1:]:
                if len(row) > 2 and row[0].strip().lower() == target_hash.lower():
                    ten_muc_tieu = row[1]
                    try: muc_tieu_tien = int(re.sub(r'[^\d]', '', str(row[2])))
                    except: pass
                    break
            da_gom = 0
            for row in sheet_budget.get_all_values()[1:]:
                if len(row) >= 6 and target_hash.lower() in row[5].lower() and ("✅" in row[4] or "xong" in row[4].lower()):
                    try: da_gom += int(re.sub(r'[^\d]', '', str(row[3])))
                    except: pass
            percent = 0 
            if muc_tieu_tien > 0:
                percent = min(100, int((da_gom / muc_tieu_tien) * 100))
                if percent >= 100:
                    for i, row in enumerate(sheet_goals.get_all_values()[1:], start=2):
                        if row[0].strip().lower() == target_hash.lower():
                            sheet_goals.update_cell(i, 4, "✅ Đã xong")
                            break
            msg = f"🏷️ **THỐNG KÊ HASHTAG:** `{target_hash}`\n━━━━━━━━━━━━━━━━━━\n"
            if muc_tieu_tien > 0:
                filled = percent // 10
                bar = f"[{'▓' * filled}{'░' * (10 - filled)}]"
                con_thieu = muc_tieu_tien - da_gom
                safe_ten = ten_muc_tieu.replace('_', '\\_') 
                msg += f"📝 **Tên dự án:** {safe_ten}\n💰 **Vốn cần thiết:** `{format_vnd(muc_tieu_tien)} đ`\n✅ **Đã rót vào:** `{format_vnd(da_gom)} đ`\n🚀 **Tiến độ:** {bar} **{percent}%**\n\n"
                msg += f"*(Còn thiếu `{format_vnd(con_thieu)} đ` nữa là kết thúc dự án!)*" if con_thieu > 0 else "*(🎉 BINGO! Dự án đã hoàn tất giải ngân!)*"
            else:
                msg += "*(Đây là hạng mục phân loại chi tiêu, không có hạn mức mục tiêu cụ thể)*\n\n"
                msg += f"💸 **Tổng tiền đã chi cho `{target_hash}`:**\n👉 **`{format_vnd(da_gom)} đ`**\n"
            bot_johnny.edit_message_text(msg, chat_id, msg_id, parse_mode='Markdown')
        except Exception as e:
            bot_johnny.edit_message_text(f"❌ Lỗi xuất báo cáo Hashtag: {e}", chat_id, msg_id)

@bot_johnny.message_handler(func=lambda message: True)
def process_input_johnny(message):
    original_text = message.text
    original_text = re.sub(r'(\d+)\s+(tỷ|ty|tr|củ|cu|lít|lit|loét|k|đ|d|vnd)\b', r'\1\2', original_text, flags=re.IGNORECASE)
    original_text = re.sub(r'\b(tỷ|ty|tr|củ|cu|lít|lit|loét|k)\s+(rưỡi|ruoi|\d+)\b', r'\1\2', original_text, flags=re.IGNORECASE)
    text = original_text.lower().strip() 
    
    if 'hướng dẫn' in text:
        guide = (
            "📖 **BÍ KÍP SỬ DỤNG TRỢ LÝ JOHNNY** 📖\n\n"
            "⏰ **1. CHẤM CÔNG & LỊCH TRÌNH**\n"
            "🔹 **Báo giờ làm:** `[ngày] [giờ] đi [giờ] về`\n"
            "👉 *VD:* `8h đi 17h30 về` hoặc `15/4 8h đi`\n"
            "🔹 **Thêm/Xóa Ghi chú:** `note: [nội dung]` (Để xóa gõ: `note: xoá`)\n"
            "🔹 **Báo nghỉ:** `[ngày] nghỉ phép / nghỉ lễ: [lý do]`\n"
            "👉 *VD:* `12/4 nghỉ phép năm: Đi khám bệnh`\n"
            "🔹 **Xóa nguyên ngày:** `xoá [ngày/tháng]` (VD: `xoá 12/4`)\n\n"
            "💰 **2. QUẢN LÝ LƯƠNG BỔNG**\n"
            "🔹 **Chốt/Sửa lương:** `lương thực nhận t[X]: [số tiền]`\n"
            "👉 *VD:* `lương thực nhận t5: 10 củ rưỡi`\n"
            "🔹 **Xóa mức lương:** `lương thực nhận t[X]: 0` (hoặc gõ chữ `xoá`)\n\n"
            "💸 **3. SỔ SÁCH THU CHI (QUẢN LÝ THEO MÃ ID)**\n"
            "*(💡 Hỗ trợ đọc tiền lóng: `k`, `lít/loét`, `củ/tr`, `tỷ`, `rưỡi`...)*\n"
            "🔹 **Thêm dự chi:** `dự chi t[X] [tên khoản] [#hashtag] [số tiền]`\n"
            "👉 *VD:* `dự chi t6 tiền mạng 3 lít` hoặc `dự chi t7 Trả góp #dieuhoa 2tr`\n"
            "🔹 **Sửa khoản chi:** `sửa [mã ID] thành [tên mới] [số tiền mới]`\n"
            "👉 *VD:* `sửa 2606-01 thành Tiền điện 1 củ`\n"
            "🔹 **Gạch nợ (Đã chi):** `xong [mã ID]` hoặc `đã chi [mã ID]`\n"
            "🔹 **Xoá khoản chi:** `xoá [mã ID]` (Hoặc dùng Nút Menu)\n\n"
            "🎯 **4. QUẢN LÝ MỤC TIÊU (GOALS)**\n"
            "🔹 **Tạo/Sửa mục tiêu:** `mục tiêu [#hashtag] [số tiền] [Tên dự án]`\n"
            "👉 *VD:* `mục tiêu #mua_pc 30tr Quỹ tiết kiệm mua PC`\n\n"
            "🎮 **5. MENU NÚT BẤM (Gõ `/start` nếu bị ẩn)**\n"
            "📊 **Báo Cáo Tài Chính:** Xem tiến độ cày cuốc, đếm ngược ngày lương về.\n"
            "💸 **Tình Hình Thu Chi:** Xem chi tiết dự chi, tiền tự do (có phân trang).\n"
            "📈 **Thống Kê & Mục Tiêu:** Xem tổng kết Thu/Chi cả năm và check % tiến độ hoàn thành Mục Tiêu.\n"
            "🗑️ **Xoá Khoản Chi:** Giao diện bấm nút lật trang để xóa siêu nhanh."
        )
        bot_johnny.reply_to(message, guide, parse_mode='Markdown')
        return
    
    if text.startswith('mục tiêu') or text.startswith('muc tieu'):
        try:
            hash_match = re.search(r'(#\w+)', original_text)
            if not hash_match:
                bot_johnny.reply_to(message, "⚠️ Sếp chưa gắn hashtag cho mục tiêu rồi. VD: `Mục tiêu #PC 20tr Build máy mới`")
                return
            hashtag = hash_match.group(1)
            clean_txt = re.sub(r'(?i)mục tiêu|muc tieu', '', original_text).replace(hashtag, '').strip()
            words = clean_txt.split()
            money_val = 0; money_words = ""
            for word in words:
                val = parse_money_johnny(word)
                if val > 0:
                    money_val = val; money_words = word; break
            if money_val > 0: ten_muc_tieu = re.sub(r'\s+', ' ', clean_txt.replace(money_words, '', 1).strip())
            else: ten_muc_tieu = clean_txt
            if not ten_muc_tieu and money_val == 0:
                bot_johnny.reply_to(message, "⚠️ Sếp nhập thiếu tên hoặc số tiền rồi.")
                return
            all_goals = sheet_goals.get_all_values()
            row_idx = -1
            for i, row in enumerate(all_goals):
                if len(row) > 0 and row[0].strip().lower() == hashtag.lower():
                    row_idx = i + 1; break
            if row_idx == -1:
                if money_val == 0:
                    bot_johnny.reply_to(message, "⚠️ Mục tiêu mới cần có số tiền. VD: `mục tiêu #PC 20tr`")
                    return
                sheet_goals.append_row([hashtag, ten_muc_tieu, money_val, "🏃 Đang chạy"])
                bot_johnny.reply_to(message, f"🎯 **ĐÃ TẠO MỤC TIÊU MỚI!**\n🏷️ Hashtag: `{hashtag}`\n📝 Tên: {ten_muc_tieu}\n💰 Mục tiêu: `{format_vnd(money_val)} đ`", parse_mode='Markdown')
            else:
                if ten_muc_tieu: sheet_goals.update_cell(row_idx, 2, ten_muc_tieu)
                if money_val > 0: sheet_goals.update_cell(row_idx, 3, money_val)
                sheet_goals.update_cell(row_idx, 4, "🏃 Đang chạy")
                bot_johnny.reply_to(message, f"✏️ **ĐÃ CẬP NHẬT MỤC TIÊU `{hashtag}`!**\n📝 Tên mới: {ten_muc_tieu if ten_muc_tieu else 'Giữ nguyên'}\n💰 Tiền mới: `{format_vnd(money_val)} đ`" if money_val>0 else "Giữ nguyên", parse_mode='Markdown')
            return
        except Exception as e:
            bot_johnny.reply_to(message, f"❌ Lỗi ghi mục tiêu: {e}")
            return

    if text.startswith('dự chi') or text.startswith('du chi'):
        try:
            month_match = re.search(r'(?:t|tháng\s*)(\d{1,2})(?:/|\s+)?(\d{4}|\d{2})?\b', text)
            if not month_match:
                bot_johnny.reply_to(message, "⚠️ Gõ thiếu tháng rồi sếp ơi! VD: `dự chi t6 góp điều hoà 2tr4` hoặc `dự chi t7/2028 mua xe 100tr`")
                return
            m_val = int(month_match.group(1)); year_val = month_match.group(2)
            now = datetime.now()
            if year_val: y = int(year_val) + 2000 if int(year_val) < 100 else int(year_val)
            else:
                y = now.year
                if m_val == 12 and now.month == 1: y -= 1
                elif m_val == 1 and now.month == 12: y += 1
            target_ky_luong = f"Tháng {m_val:02d}/{y}"
            words = text.split(); money_val = 0; money_words = ""
            for word in reversed(words):
                val = parse_money_johnny(word)
                if val > 0:
                    money_val = val; money_words = word; break
            if money_val == 0:
                bot_johnny.reply_to(message, "⚠️ Không nhận diện được số tiền trong câu lệnh của sếp.")
                return
            clean_text = re.sub(r'(?i)dự chi\s*', '', original_text)
            clean_text = re.sub(r'(?i)(?:t|tháng\s*)\d{1,2}(?:/|\s+)?(?:\d{4}|\d{2})?\b', '', clean_text, count=1)
            hashtag = ""
            hashtag_match = re.search(r'#\w+', clean_text)
            if hashtag_match:
                hashtag = hashtag_match.group(0)
                clean_text = clean_text.replace(hashtag, '')
            words = clean_text.strip().split()
            ten_khoan_chi = " ".join(words[:-1]).strip()
            hashtag_match = re.search(r'(#\w+)', original_text)
            if hashtag_match:
                hashtag = hashtag_match.group(1)
                ten_khoan_chi = ten_khoan_chi.replace(hashtag, '').replace(hashtag.lower(), '').strip()
            ten_khoan_chi = re.sub(r'^[\/\-\s,:]+|[\/\-\s,:]+$', '', ten_khoan_chi)
            ten_khoan_chi = re.sub(r'\s+', ' ', ten_khoan_chi)
            if not ten_khoan_chi:
                bot_johnny.reply_to(message, "⚠️ Thiếu tên khoản chi tiêu rồi sếp.")
                return
            all_rows = sheet_budget.get_all_values()
            duplicate_row_index = -1; old_tien = 0
            for i, row in enumerate(all_rows):
                if len(row) >= 4 and row[1].strip() == target_ky_luong and row[2].strip().lower() == ten_khoan_chi.lower():
                    duplicate_row_index = i + 1 
                    try: old_tien = int(re.sub(r'[^\d]', '', str(row[3])))
                    except: old_tien = 0
                    break
            if duplicate_row_index != -1:
                pending_add[message.chat.id] = {"ky": target_ky_luong, "ten": ten_khoan_chi, "tien": money_val, "row": duplicate_row_index, "m_val": m_val, "y": y}
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(types.InlineKeyboardButton("📝 Ghi đè số tiền", callback_data="force_overwrite"), types.InlineKeyboardButton("➕ Tạo khoản mới", callback_data="force_new"), types.InlineKeyboardButton("❌ Huỷ lệnh thêm", callback_data="force_cancel"))
                bot_johnny.reply_to(message, f"⚠️ Khoản **{ten_khoan_chi}** đã tồn tại trong **{target_ky_luong}** với số tiền `{format_vnd(old_tien)} đ`.\n\nSếp muốn ghi đè bằng số tiền mới (`{format_vnd(money_val)} đ`), tạo khoản mới, hay huỷ thao tác?", parse_mode='Markdown', reply_markup=markup)
                return
            else:
                year_code = str(y)[-2:]; stt = 1
                for row in all_rows[1:]:
                    if len(row) >= 2 and row[1] == target_ky_luong: stt += 1
                m_id = f"{year_code}{m_val:02d}-{stt:02d}" 
                sheet_budget.append_row([f"'{m_id}", target_ky_luong, ten_khoan_chi, money_val, "⏳ Chờ chi", hashtag], value_input_option='USER_ENTERED')
                sheet_budget.sort((1, 'asc'), range='A2:F1000') 
                bot_johnny.reply_to(message, f"✅ **ĐÃ GHI SỔ THU CHI THÀNH CÔNG!**\n📌 Mã ID: `{m_id}`\n📅 Kỳ chi tiêu: **{target_ky_luong}**\n📝 Khoản chi: **{ten_khoan_chi}**\n💵 Số tiền: `{format_vnd(money_val)} đ`", parse_mode='Markdown')
                return
        except Exception as e:
            bot_johnny.reply_to(message, f"❌ Lỗi ghi sổ: {e}")

    if text.startswith('sửa') or text.startswith('sua'):
        id_match = re.search(r'(\d{4}-?\d{2})', text)
        if id_match:
            try:
                target_id = id_match.group(1)
                if '-' not in target_id: target_id = f"{target_id[:4]}-{target_id[4:]}"
                parts = re.split(r'(?i)thành|thanh', original_text, maxsplit=1)
                if len(parts) == 2:
                    new_content = parts[1].strip()
                    hashtag = ""
                    hashtag_match = re.search(r'(#\w+)', new_content)
                    if hashtag_match:
                        hashtag = hashtag_match.group(1)
                        new_content = new_content.replace(hashtag, '').strip()
                    money_words = new_content.split()[-1] if new_content else ""
                    new_money = parse_money_johnny(money_words)
                    new_name = new_content.rsplit(money_words, 1)[0].strip() if new_money > 0 else new_content 
                    if new_money == 0 and not new_name and not hashtag:
                        bot_johnny.reply_to(message, "⚠️ Sếp chưa nhập nội dung mới để sửa.")
                        return
                    all_rows = sheet_budget.get_all_values()
                    row_index = -1
                    for i, row in enumerate(all_rows):
                        if len(row) > 0 and row[0].replace("'", "") == target_id:
                            row_index = i + 1; break
                    if row_index == -1: bot_johnny.reply_to(message, f"❓ Không tìm thấy mã khoản chi `{target_id}` để sửa.")
                    else:
                        if new_name: sheet_budget.update_cell(row_index, 3, new_name)
                        if new_money > 0: sheet_budget.update_cell(row_index, 4, new_money)
                        if hashtag: sheet_budget.update_cell(row_index, 6, hashtag)
                        msg_reply = f"✏️ Đã cập nhật khoản `{target_id}`:\n"
                        if new_name: msg_reply += f"Tên: **{new_name}**\n"
                        if new_money > 0: msg_reply += f"Tiền: `{format_vnd(new_money)} đ`\n"
                        if hashtag: msg_reply += f"Tag: `{hashtag}`"
                        bot_johnny.reply_to(message, msg_reply, parse_mode='Markdown')
                else: bot_johnny.reply_to(message, "⚠️ Sai cú pháp sửa. VD: `sửa 2606-01 thành Mua PC #mua_pc 4tr5`")
                return
            except Exception as e:
                error_msg = str(e)
                if "502" in error_msg or "<html" in error_msg.lower() or "Bad Gateway" in error_msg:
                    bot_johnny.reply_to(message, "❌ Google Sheets vừa bị quá tải nhẹ. Sếp đợi 3 giây rồi gõ lại lệnh nhé!")
                else: bot_johnny.reply_to(message, f"❌ Lỗi sửa khoản chi: {e}")
                return

    if text.startswith('xong') or text.startswith('đã chi') or text.startswith('da chi'):
        id_match = re.search(r'(\d{4}-?\d{2}|\d{6})', text)
        if not id_match:
            bot_johnny.reply_to(message, "⚠️ Sếp chưa nhập đúng Mã ID. VD: `đã chi 2606-03`")
            return
        target_id_raw = id_match.group(1)
        target_id = f"{target_id_raw[:4]}-{target_id_raw[4:]}" if '-' not in target_id_raw else target_id_raw
        try:
            text_without_cmd = text.replace(id_match.group(0), '').replace('xong', '').replace('đã chi', '').replace('da chi', '').strip()
            thuc_chi = parse_money_johnny(text_without_cmd) if text_without_cmd else 0
            all_rows = sheet_budget.get_all_values()
            row_index = -1
            for i, row in enumerate(all_rows):
                if len(row) > 0 and row[0].replace("'", "") == target_id:
                    row_index = i + 1; break
            if row_index == -1: bot_johnny.reply_to(message, f"❓ Không tìm thấy mã khoản chi `{target_id}`.")
            else:
                ten_cu = all_rows[row_index-1][2]
                try: tien_cu = int(re.sub(r'[^\d]', '', str(all_rows[row_index-1][3])))
                except: tien_cu = 0
                if thuc_chi > 0 and thuc_chi != tien_cu:
                    ten_moi = f"{ten_cu} (Dự kiến: {format_vnd(tien_cu)}đ)"
                    sheet_budget.update_cell(row_index, 3, ten_moi)
                    sheet_budget.update_cell(row_index, 4, thuc_chi)
                    sheet_budget.update_cell(row_index, 5, "✅ Đã xong")
                    chenh_lech = tien_cu - thuc_chi
                    msg = f"✅ Khoản `{target_id}` đã thanh toán!\n💸 Thực chi: `{format_vnd(thuc_chi)} đ`"
                    msg += f"\n🎉 Tiết kiệm: `{format_vnd(chenh_lech)} đ`" if chenh_lech > 0 else f"\n⚠️ Vượt: `{format_vnd(abs(chenh_lech))} đ`"
                    bot_johnny.reply_to(message, msg, parse_mode='Markdown')
                else:
                    sheet_budget.update_cell(row_index, 5, "✅ Đã xong") 
                    bot_johnny.reply_to(message, f"✅ Khoản `{target_id}` (**{ten_cu}**) đã đánh dấu: **Đã xong**!", parse_mode='Markdown')
            return
        except Exception as e:
            bot_johnny.reply_to(message, f"❌ Lỗi gạch nợ: {e}")
            return

    try:
        is_off_work = False; type_day = ""; ghi_chu = ""; has_note = False
        if ':' in original_text and any(x in text for x in ['nghỉ', 'nghi']):
            parts = original_text.split(':', 1)
            ghi_chu = parts[1].strip()
            has_note = True if ghi_chu else False
            text = parts[0].strip().lower() 
        if 'nghỉ phép' in text or 'nghi phep' in text:
            is_off_work = True
            type_day = "Nghỉ phép năm" if 'phép năm' in text or 'phep nam' in text else "Nghỉ phép thường"
        elif 'nghỉ lễ' in text or 'nghi le' in text:
            is_off_work = True; type_day = "Nghỉ lễ"
        if not has_note:
            note_match = re.search(r'(?i)note:\s*(.*)', original_text)
            if note_match:
                has_note = True; ghi_chu = note_match.group(1).strip()
                text = text[:note_match.start()].strip() 
        matches = re.findall(r'(\d{1,2}[h:]\d{0,2})\s*([^\s\d]+)', text)
        gio_di, gio_ve = "", ""
        for time_str, keyword in matches:
            t_part = re.split(r'[h:]', time_str)
            h = t_part[0].zfill(2)
            m = t_part[1].zfill(2) if (len(t_part) > 1 and t_part[1]) else "00"
            formatted_time = f"{h}:{m}"
            if any(x in keyword for x in ['đi', 'di', 'đến', 'den', 'đê']): gio_di = formatted_time
            elif any(x in keyword for x in ['về', 've', 'tan', 'vê']): gio_ve = formatted_time
        if not gio_di and not gio_ve and not is_off_work:
            time_matches = re.findall(r'(\d{1,2})[h:](\d{0,2})', text)
            times = [f"{t[0].zfill(2)}:{t[1].zfill(2) if t[1] else '00'}" for t in time_matches]
            if times:
                gio_di = times[0]
                if len(times) >= 2: gio_ve = times[1]
            elif not has_note: 
                bot_johnny.reply_to(message, "⚠️ Nhắn thiếu thông tin rồi Hoàn ơi! (VD: `8h đi`, `note: đổi lịch` hoặc `xin nghỉ...`)")
                return
        now = datetime.now()
        date_match = re.search(r'(\d{1,2}/\d{1,2})', text)
        if date_match:
            d_p, m_p = date_match.group(1).split('/')
            target_date = f"{int(d_p)}/{int(m_p)}"
            dt_obj = datetime.strptime(f"{target_date}/{now.year}", "%d/%m/%Y")
        else:
            target_date = f"{now.day}/{now.month}"
            dt_obj = now
        if not type_day:
            is_holiday_work = any(x in text for x in ['ngày lễ', 'ngay le', 'lễ', 'le'])
            type_day = "Ngày lễ" if is_holiday_work else ("Chủ nhật" if dt_obj.weekday() == 6 else "Ngày thường")
        all_rows = sheet_data.get_all_values()
        row_index = -1; search_alt = dt_obj.strftime("%d/%m/%Y"); old_type = ""
        for i, row in enumerate(all_rows):
            d = row[0] if len(row) > 0 else ""
            if target_date == d or search_alt in d or d.startswith(target_date + "/"):
                row_index = i + 1; old_type = row[1] if len(row) > 1 else ""; break
        msg_ghi_chu = ""
        is_clearing_note = has_note and ghi_chu.lower() in ['xoá', 'xóa', 'clear', 'trống']
        if is_clearing_note: msg_ghi_chu = "\n🗑️ Đã làm sạch Ghi chú!"
        elif has_note and ghi_chu: msg_ghi_chu = f"\n📝 Note: {ghi_chu}"
        if row_index == -1: 
            if not gio_di and not gio_ve and not is_off_work:
                bot_johnny.reply_to(message, f"⚠️ Ngày {target_date} chưa có dữ liệu giờ giấc. Hãy nhập giờ đi/về trước khi gắn Ghi chú nhé!")
                return
            gio_di_val = "" if is_off_work else gio_di
            gio_ve_val = "" if is_off_work else gio_ve
            res = sheet_data.append_row([target_date, type_day, gio_di_val, gio_ve_val], value_input_option='USER_ENTERED')
            if has_note and not is_clearing_note:
                try:
                    new_row = int(re.search(r'[A-Z](\d+)', res.get('updates', {}).get('updatedRange', '')).group(1))
                    sheet_data.update_cell(new_row, 9, ghi_chu) 
                except: pass
            if is_off_work: msg = f"✅ Đã ghi nhận ngày {target_date} là: **{type_day}**{msg_ghi_chu}"
            else: msg = f"✅ Tạo ngày {target_date} ({type_day}):\n🎬 Đi: {gio_di if gio_di else '--'} | 🏁 Về: {gio_ve if gio_ve else '--'}{msg_ghi_chu}"
        else: 
            if is_off_work:
                sheet_data.update_cell(row_index, 2, type_day); sheet_data.update_cell(row_index, 3, ""); sheet_data.update_cell(row_index, 4, "") 
                msg = f"🔄 Đã cập nhật ngày {target_date} thành: **{type_day}**{msg_ghi_chu}"
            else:
                if gio_di: sheet_data.update_cell(row_index, 3, gio_di)
                if gio_ve: sheet_data.update_cell(row_index, 4, gio_ve)
                if gio_di or gio_ve or (type_day == "Ngày lễ"): sheet_data.update_cell(row_index, 2, type_day)
                if not gio_di and not gio_ve: msg = f"🔄 Đã cập nhật Ghi chú ngày {target_date}:{msg_ghi_chu}"
                else: msg = f"🔄 Cập nhật ngày {target_date} ({type_day}):\n🎬 Đi: {gio_di if gio_di else 'Giữ nguyên'} | 🏁 Về: {gio_ve if gio_ve else 'Giữ nguyên'}{msg_ghi_chu}"
            if has_note:
                if is_clearing_note: sheet_data.update_cell(row_index, 9, "") 
                else: sheet_data.update_cell(row_index, 9, ghi_chu) 
            else:
                if not is_off_work and "nghỉ" in old_type.lower() and type_day in ["Ngày thường", "Chủ nhật", "Ngày lễ"]:
                    sheet_data.update_cell(row_index, 9, "")
                    msg += "\n🧹 Đã tự động xoá lý do nghỉ cũ."
        sheet_data.sort((1, 'asc'), range='A3:I1000')
        bot_johnny.reply_to(message, msg + "\n✨ Đã đồng bộ!", parse_mode='Markdown')
    except Exception as e:
        error_msg = str(e)
        if "104" in error_msg or "Connection reset" in error_msg: bot_johnny.reply_to(message, "⚠️ Google Sheets vừa 'dập máy' đột ngột. Ông nhắn lại câu vừa rồi giúp tôi nhé!")
        else: bot_johnny.reply_to(message, f"❌ Lỗi: {e}")

@bot_johnny.callback_query_handler(func=lambda call: call.data in ["force_overwrite", "force_new", "force_cancel"])
def handle_duplicate_add(call):
    chat_id = call.message.chat.id
    if chat_id not in pending_add:
        bot_johnny.answer_callback_query(call.id, "❌ Yêu cầu đã cũ hoặc đã được xử lý!")
        return
    data = pending_add[chat_id]
    bot_johnny.answer_callback_query(call.id)
    try:
        if call.data == "force_cancel":
            bot_johnny.edit_message_text(f"❌ **Đã huỷ thao tác!**\nSếp đã huỷ việc thêm khoản chi **{data['ten']}** vào {data['ky']}.", chat_id, call.message.message_id, parse_mode='Markdown')
        elif call.data == "force_overwrite":
            bot_johnny.edit_message_text(f"⏳ Dạ sếp! Đợi em xíu để em xoá số cũ và ghi đè số tiền mới cho khoản **{data['ten']}** nhé...", chat_id, call.message.message_id, parse_mode='Markdown')
            sheet_budget.update_cell(data["row"], 4, data["tien"]); sheet_budget.update_cell(data["row"], 5, "⏳ Chờ chi") 
            bot_johnny.edit_message_text(f"📝 **Đã ghi đè thành công!**\nKhoản: **{data['ten']}** ({data['ky']}) đã được cập nhật thành mức tiền mới: `{format_vnd(data['tien'])} đ` và đặt lại trạng thái Chờ chi.", chat_id, call.message.message_id, parse_mode='Markdown')
        elif call.data == "force_new":
            bot_johnny.edit_message_text(f"⏳ Dạ sếp! Đợi em vài giây để em chèn thêm một khoản **{data['ten']}** mới tinh vào sổ nhé...", chat_id, call.message.message_id, parse_mode='Markdown')
            all_rows = sheet_budget.get_all_values()
            year_code = str(data["y"])[-2:]; stt = 1
            for row in all_rows[1:]:
                if len(row) >= 2 and row[1] == data["ky"]: stt += 1
            m_id = f"{year_code}{data['m_val']:02d}-{stt:02d}" 
            sheet_budget.append_row([f"'{m_id}", data["ky"], data["ten"], data["tien"], "⏳ Chờ chi"], value_input_option='USER_ENTERED')
            sheet_budget.sort((1, 'asc'), range='A2:F1000')
            bot_johnny.edit_message_text(f"➕ **Đã tạo thêm một khoản chi mới độc lập!**\n📌 Mã ID: `{m_id}`\n📅 Kỳ chi tiêu: **{data['ky']}**\n📝 Khoản chi: **{data['ten']}**\n💵 Số tiền: `{format_vnd(data['tien'])} đ`", chat_id, call.message.message_id, parse_mode='Markdown')
        del pending_add[chat_id]
    except Exception as e:
        bot_johnny.edit_message_text(f"❌ Lỗi cập nhật bảng: {e}", chat_id, call.message.message_id)


# =========================================================================
# KHU VỰC 4: THỰC THI ĐA LUỒNG (MULTI-THREADING)
# =========================================================================
def run_bot_congtac():
    print("🚀 [Bot 1] Công Tác Phí đang chạy...")
    bot_congtac.infinity_polling(timeout=10, long_polling_timeout=5)

def run_bot_caogia():
    print("🚀 [Bot 2] Cào Giá PC đang chạy...")
    bot_caogia.infinity_polling(timeout=10, long_polling_timeout=5)

def run_bot_johnny():
    print("🚀 [Bot 3] Trợ Lý Johnny đang chạy...")
    bot_johnny.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    # Bật Web Server (Giữ cho Render không tắt app)
    threading.Thread(target=run_server, daemon=True).start()
    
    # --- THÊM DÒNG NÀY ĐỂ BẬT TÍNH NĂNG AUTO CANH GIỜ ---
    threading.Thread(target=auto_scan_worker, daemon=True).start()
    
    # Bật các Bot chạy song song trên các luồng ngầm (Daemon Threads)
    threading.Thread(target=run_bot_congtac, daemon=True).start()
    threading.Thread(target=run_bot_caogia, daemon=True).start()
    
    # Giữ luồng chính (Main Thread) cho Bot cuối cùng để script không bị kết thúc đột ngột
    run_bot_johnny()