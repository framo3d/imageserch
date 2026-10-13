#!/usr/bin/env python3
"""
اسکریپت راه‌اندازی لود بالانسر
"""
import os
import sys

# اجرای لود بالانسر
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from webservice.load_balancer import main

if __name__ == "__main__":
    main() 
