#!/usr/bin/env python3
"""
لود بالانسر هوشمند برای سیستم جستجوی تصویر - نسخه سازگار با موتور یکپارچه
"""

import os
import time
import requests
import threading
from flask import Flask, request, jsonify, Response
import json
import logging

# تنظیم لاگینگ
logging.basicConfig(
    filename='load_balancer.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = Flask(__name__)

# تنظیمات موتور یکپارچه
UNIFIED_ENGINE_PORT = 1950
UNIFIED_ENGINE_URL = f"http://127.0.0.1:{UNIFIED_ENGINE_PORT}"
TIMEOUT = 5  # ثانیه
CHECK_INTERVAL = 30  # بررسی سلامت سرویس هر 30 ثانیه
HEALTH_CHECK_ENDPOINT = "/status"  # اندپوینت بررسی سلامت سرویس
PROCESS_ENDPOINT = "/process/"  # اندپوینت جستجوی تصویر
CLEAN_MEMORY_ENDPOINT = "/clean_memory"  # اندپوینت پاکسازی حافظه

# وضعیت سرویس موتور یکپارچه
engine_status = {
    "is_active": False,
    "last_check": 0,
    "details": {},
    "error": None
}

# قفل برای مولتی‌تردینگ
lock = threading.Lock()

def check_unified_engine():
    """بررسی سلامت موتور یکپارچه جستجو"""
    url = f"{UNIFIED_ENGINE_URL}{HEALTH_CHECK_ENDPOINT}"
    
    try:
        response = requests.get(url, timeout=TIMEOUT)
        if response.status_code == 200:
            return True, response.json()
        return False, {"error": f"کد وضعیت نامعتبر: {response.status_code}"}
    except requests.RequestException as e:
        error_msg = f"خطا در ارتباط با موتور یکپارچه: {str(e)}"
        logging.error(error_msg)
        return False, {"error": error_msg}

def update_engine_status():
    """به روزرسانی وضعیت موتور یکپارچه"""
    global engine_status
    
    is_active, details = check_unified_engine()
    
    with lock:
        engine_status["is_active"] = is_active
        engine_status["last_check"] = time.time()
        
        if is_active:
            engine_status["details"] = details
            engine_status["error"] = None
            logging.info("موتور یکپارچه فعال است")
        else:
            engine_status["error"] = details.get("error", "خطای نامشخص")
            logging.warning(f"موتور یکپارچه غیرفعال است: {details.get('error')}")

def service_checker():
    """تابع برای بررسی مداوم سلامت موتور یکپارچه"""
    while True:
        try:
            update_engine_status()
        except Exception as e:
            logging.error(f"خطا در بررسی سلامت موتور یکپارچه: {e}")
        
        # هر 5 ساعت یکبار حافظه را پاکسازی کنید
        if int(time.time()) % (5 * 60 * 60) < 60 and engine_status["is_active"]:
            try:
                requests.get(f"{UNIFIED_ENGINE_URL}{CLEAN_MEMORY_ENDPOINT}", timeout=TIMEOUT)
                logging.info("درخواست پاکسازی حافظه ارسال شد")
            except Exception as e:
                logging.error(f"خطا در ارسال درخواست پاکسازی حافظه: {e}")
        
        time.sleep(CHECK_INTERVAL)

@app.route("/process/", methods=['POST'])
def process_image():
    """اندپوینت برای دریافت درخواست و ارسال به موتور یکپارچه"""
    with lock:
        if not engine_status["is_active"]:
            # بررسی مجدد وضعیت در صورت غیرفعال بودن
            update_engine_status()
            if not engine_status["is_active"]:
                error_msg = f"موتور یکپارچه جستجو غیرفعال است: {engine_status['error']}"
                logging.error(error_msg)
                return jsonify({"error": error_msg}), 503
    
    # ارسال درخواست به موتور یکپارچه
    service_url = f"{UNIFIED_ENGINE_URL}{PROCESS_ENDPOINT}"
    
    try:
        logging.info(f"ارسال درخواست جستجو به موتور یکپارچه: {request.values.get('fp', 'unknown')}")
        
        # ارسال تمام پارامترها به موتور یکپارچه
        response = requests.post(
            service_url, 
            data=request.values.to_dict(),
            timeout=15  # افزایش تایم‌اوت برای جستجوهای پیچیده
        )
        
        # بررسی پاسخ
        if response.status_code == 200:
            logging.info(f"جستجو با موفقیت انجام شد: {len(response.text)} بایت")
        else:
            logging.warning(f"پاسخ نامعتبر از موتور جستجو: کد {response.status_code}")
        
        # برگرداندن نتیجه به کاربر
        return Response(response.text, mimetype='application/json'), response.status_code
    except Exception as e:
        logging.error(f"خطا در ارتباط با موتور یکپارچه: {e}")
        
        # علامت‌گذاری موتور به عنوان غیرفعال
        with lock:
            engine_status["is_active"] = False
            engine_status["error"] = str(e)
        
        return jsonify({"error": f"خطا در ارتباط با موتور جستجو: {str(e)}"}), 500

@app.route("/status", methods=['GET'])
def status():
    """اندپوینت برای بررسی وضعیت لود بالانسر و موتور یکپارچه"""
    with lock:
        status_data = {
            "load_balancer": {
                "status": "ok",
                "time": time.time()
            },
            "unified_engine": {
                "is_active": engine_status["is_active"],
                "last_check": engine_status["last_check"],
                "details": engine_status["details"]
            }
        }
        
        if engine_status["error"]:
            status_data["unified_engine"]["error"] = engine_status["error"]
        
        if request.args.get("check_now") == "true":
            # بررسی مجدد وضعیت در صورت درخواست
            update_engine_status()
            status_data["unified_engine"]["is_active"] = engine_status["is_active"]
            status_data["unified_engine"]["last_check"] = engine_status["last_check"]
            status_data["unified_engine"]["details"] = engine_status["details"]
            
            if engine_status["error"]:
                status_data["unified_engine"]["error"] = engine_status["error"]
    
    return jsonify(status_data)

def main():
    logging.info("راه‌اندازی لود بالانسر سازگار با موتور یکپارچه")
    
    # شروع ترد بررسی سلامت موتور یکپارچه
    service_thread = threading.Thread(target=service_checker)
    service_thread.daemon = True
    service_thread.start()
    
    # راه‌اندازی اولیه وضعیت موتور یکپارچه
    update_engine_status()
    
    # راه‌اندازی وب‌سرور
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)

if __name__ == "__main__":
    main() 
