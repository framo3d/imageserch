import requests
import logging
import time
import os
import psutil
import subprocess
from glob import glob

# تنظیم لاگر
logging.basicConfig(
    filename='/home/morteza/services/image_service_status.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('image_service_status')

def check_service(port):
    try:
        response = requests.get(f"http://127.0.0.1:{port}/", timeout=2)
        return response.status_code == 200
    except:
        return False

def get_running_stack_services():
    services = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['name'] in ['python', 'python3']:
                cmdline = ' '.join(proc.info['cmdline'] if proc.info['cmdline'] else [])
                if 'image_search_engine.engine' in cmdline:
                    stack_num = None
                    for arg in proc.info['cmdline']:
                        if arg.isdigit():
                            stack_num = int(arg)
                            break
                    if stack_num is not None:
                        services.append((stack_num, proc.info['pid'], 1950 + stack_num))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return services

def main():
    logger.info("Starting service check")
    
    # تعداد فایل‌های استک موجود
    stack_files = glob("/home/morteza/services/main/stacks/*")
    logger.info(f"Found {len(stack_files)} stack files")
    
    # بررسی سرویس‌های در حال اجرا
    running_services = get_running_stack_services()
    logger.info(f"Found {len(running_services)} running services")
    
    # چک کردن هر سرویس
    for stack_num, pid, port in running_services:
        status = "RESPONDING" if check_service(port) else "NOT RESPONDING"
        memory_usage = psutil.Process(pid).memory_info().rss / (1024 * 1024)  # MB
        logger.info(f"Stack {stack_num} (PID: {pid}, Port: {port}): {status}, Memory: {memory_usage:.2f} MB")
    
    # چک کردن سرویس‌های گمشده
    expected_stacks = set(range(len(stack_files)))
    running_stacks = set(s[0] for s in running_services)
    missing_stacks = expected_stacks - running_stacks
    
    if missing_stacks:
        logger.warning(f"Missing stack services: {missing_stacks}")
        
    return len(missing_stacks) == 0

if __name__ == "__main__":
    if main():
        print("All services are running")
    else:
        print("Some services are missing")
