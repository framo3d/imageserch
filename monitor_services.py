#!/usr/bin/env python3
"""
Service Monitor for Image Search Engine
بررسی سرویس‌ها و ری‌استارت در صورت نیاز
"""

import os
import sys
import time
import logging
import subprocess
import requests
from glob import glob
import re
from collections import defaultdict

# تنظیم لاگینگ
logging.basicConfig(
    filename='service_monitor.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# پیکربندی
CHECK_INTERVAL = 180       # بررسی هر 3 دقیقه
TIMEOUT = 3                # تایم‌اوت درخواست HTTP (ثانیه)
BASE_PORT = 1950           # پورت پایه برای سرویس‌ها
STACKS_DIR = "main/stacks"
RESTART_SCRIPT = "/home/morteza/services/reboot_services.py"

# شرط مصرف رم
MAX_MEM_PERCENT = 60.0     # حداکثر 60 درصد کل رم
# تعداد دفعاتی که باید سرویس fail بشه تا ریست بشه
FAIL_THRESHOLD = 3

# مدت انتظار بعد از ری‌استارت (تا سرویس کامل بالا بیاد)
RESTART_DELAY = 120  # ثانیه (2 دقیقه)

# ذخیره تعداد دفعات fail هر سرویس
fail_counts = defaultdict(int)


def get_stack_numbers():
    """استخراج شماره تمام استک‌های موجود"""
    stack_files = glob(f"{STACKS_DIR}/stack*.npz")
    stack_nums = []

    for stack_file in stack_files:
        match = re.search(r"stack(\d+)\.npz$", stack_file)
        if match:
            stack_nums.append(int(match.group(1)))

    return sorted(stack_nums)


def check_service(stack_num):
    """بررسی وضعیت سرویس با ارسال درخواست به اندپوینت status"""
    port = BASE_PORT + stack_num
    url = f"http://127.0.0.1:{port}/status"

    try:
        response = requests.get(url, timeout=TIMEOUT)
        if response.status_code == 200:
            return True
        logging.warning(f"Service on port {port} (stack{stack_num}) returned status code {response.status_code}")
        return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Service on port {port} (stack{stack_num}) is not responding: {e}")
        return False


def restart_service(stack_num):
    """راه‌اندازی مجدد سرویس"""
    try:
        # روش 1: استفاده از اسکریپت reboot_services
        if os.path.exists(RESTART_SCRIPT):
            cmd = [sys.executable, RESTART_SCRIPT, "image_search_engine", str(stack_num)]
            subprocess.run(cmd, timeout=30)
            logging.info(f"Restarted stack{stack_num} using reboot_services.py")
        else:
            # روش 2: اجرای مستقیم
            cmd = [
                "screen", "-dm", "-S", f"image_search_engine_{stack_num}",
                sys.executable, "-m", "image_search_engine.engine", "-s", str(stack_num)
            ]
            subprocess.run(cmd, timeout=30)
            logging.info(f"Restarted stack{stack_num} directly")

        # بعد از ریست کمی صبر کنیم
        logging.info(f"Waiting {RESTART_DELAY} seconds after restarting stack{stack_num}")
        time.sleep(RESTART_DELAY)

    except Exception as e:
        logging.error(f"Failed to restart stack{stack_num}: {e}")


def check_services_memory():
    """بررسی مصرف حافظه سرویس‌ها و ری‌استارت کردن پرمصرف‌ها"""
    try:
        cmd = ["ps", "-eo", "pid,pmem,args", "--no-headers"]
        output = subprocess.check_output(cmd).decode("utf-8")

        for line in output.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3 and "image_search_engine.engine" in " ".join(parts[2:]):
                pid = parts[0]
                mem_percent = float(parts[1])

                if mem_percent > MAX_MEM_PERCENT:
                    stack_match = re.search(r"-s\s+(\d+)", " ".join(parts[2:]))
                    if stack_match:
                        stack_num = int(stack_match.group(1))
                        logging.warning(f"Stack{stack_num} using too much memory: {mem_percent:.1f}%")

                        subprocess.run(["kill", pid])
                        restart_service(stack_num)
    except Exception as e:
        logging.error(f"Error checking services memory: {e}")


def main():
    """برنامه اصلی برای مانیتورینگ و راه‌اندازی مجدد سرویس‌ها"""
    logging.info("Service monitor started")

    while True:
        try:
            stack_numbers = get_stack_numbers()
            logging.info(f"Checking {len(stack_numbers)} stacks")

            for stack_num in stack_numbers:
                if check_service(stack_num):
                    fail_counts[stack_num] = 0  # موفقیت → شمارنده صفر
                else:
                    fail_counts[stack_num] += 1
                    logging.warning(f"Stack{stack_num} failed {fail_counts[stack_num]} times")

                    if fail_counts[stack_num] >= FAIL_THRESHOLD:
                        logging.info(f"Restarting service for stack{stack_num}")
                        restart_service(stack_num)
                        fail_counts[stack_num] = 0  # شمارنده ریست بشه

            check_services_memory()

        except Exception as e:
            logging.error(f"Error in monitor loop: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
