#!/usr/bin/env python3
"""
اسکریپت بررسی وضعیت دیتابیس
این اسکریپت برای بررسی وضعیت جداول، رکوردها و اتصال به دیتابیس استفاده می‌شود.
"""

import os
import sys
from sqlalchemy import func, inspect, text

# افزودن مسیر پروژه به سیستم
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    from main.models import *
    print("✅ مدل‌های دیتابیس با موفقیت وارد شدند")
except ImportError as e:
    print(f"❌ خطا در وارد کردن مدل‌های دیتابیس: {str(e)}")
    sys.exit(1)

def check_database_connection():
    """بررسی اتصال به دیتابیس"""
    try:
        with Images().__ss__() as ss:
            # بررسی اتصال با یک کوئری ساده - استفاده از text()
            result = ss.execute(text("SELECT 1")).scalar()
            if result == 1:
                print("✅ اتصال به دیتابیس برقرار است")
                return True
            else:
                print("❌ اتصال به دیتابیس با مشکل مواجه شد")
                return False
    except Exception as e:
        print(f"❌ خطا در اتصال به دیتابیس: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def check_tables():
    """بررسی جداول موجود در دیتابیس"""
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"📊 جداول موجود در دیتابیس: {', '.join(tables)}")
        
        # بررسی ستون‌های مهم
        for table in tables:
            columns = [col['name'] for col in inspector.get_columns(table)]
            print(f"   - جدول {table}: {', '.join(columns)}")
            
        return True
    except Exception as e:
        print(f"❌ خطا در بررسی جداول: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def check_records():
    """بررسی رکوردهای موجود در جداول اصلی"""
    try:
        with Images().__ss__() as ss:
            # تعداد کل تصاویر
            total_images = ss.query(Images).count()
            print(f"📊 تعداد کل تصاویر: {total_images}")
            
            if total_images > 0:
                # نمونه‌هایی از داده‌ها
                sample_images = ss.query(Images.id, Images.URL, Images.stack_num).limit(5).all()
                print("📸 نمونه تصاویر:")
                for id, url, stack_num in sample_images:
                    print(f"   - ID: {id}, URL: {url}, stack_num: {stack_num}")
                
                # توزیع stack_num
                stack_distribution = ss.query(Images.stack_num, func.count(Images.id)).group_by(Images.stack_num).all()
                print("📊 توزیع stack_num:")
                for stack_num, count in stack_distribution:
                    print(f"   - stack_num={stack_num}: {count} تصویر")
                    
                # بررسی URL های خالی
                null_urls = ss.query(func.count(Images.id)).filter(Images.URL == None).scalar()
                if null_urls > 0:
                    print(f"⚠️ {null_urls} تصویر با URL خالی یافت شد")
            else:
                print("⚠️ هیچ تصویری در دیتابیس یافت نشد")
            
            # بررسی تگ‌ها
            try:
                total_tags = ss.query(Tag).count()
                print(f"🏷️ تعداد کل تگ‌ها: {total_tags}")
                
                if total_tags > 0:
                    sample_tags = ss.query(Tag.id, Tag.name).limit(5).all()
                    print("🏷️ نمونه تگ‌ها:")
                    for id, name in sample_tags:
                        print(f"   - ID: {id}, Name: {name}")
            except Exception as e:
                print(f"⚠️ خطا در بررسی تگ‌ها: {str(e)}")
                
            # بررسی Info
            try:
                total_info = ss.query(Info).count()
                print(f"ℹ️ تعداد کل اطلاعات تصاویر: {total_info}")
                
                if total_info > 0:
                    sample_info = ss.query(Info.id, Info.title).limit(5).all()
                    print("ℹ️ نمونه اطلاعات:")
                    for id, title in sample_info:
                        print(f"   - ID: {id}, Title: {title}")
            except Exception as e:
                print(f"⚠️ خطا در بررسی اطلاعات: {str(e)}")
                
        return True
    except Exception as e:
        print(f"❌ خطا در بررسی رکوردها: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def fix_stack_nums(target_stack=0):
    """تنظیم stack_num تصاویر به یک مقدار مشخص"""
    try:
        with Images().__ss__() as ss:
            # تعداد رکوردهای قبل از تغییر
            before_count = ss.query(Images).filter(Images.stack_num == target_stack).count()
            print(f"📊 تعداد تصاویر با stack_num={target_stack} قبل از تغییر: {before_count}")
            
            # تغییر stack_num برای تصاویری که stack_num آنها متفاوت است
            updated = ss.query(Images).filter(Images.stack_num != target_stack).update({"stack_num": target_stack})
            ss.commit()
            print(f"✅ {updated} تصویر به stack_num={target_stack} تغییر یافت")
            
            # بررسی مجدد بعد از تغییر
            after_count = ss.query(Images).filter(Images.stack_num == target_stack).count()
            print(f"📊 تعداد تصاویر با stack_num={target_stack} بعد از تغییر: {after_count}")
            
            return True
    except Exception as e:
        print(f"❌ خطا در تغییر stack_num: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """تابع اصلی برنامه"""
    print("🔍 بررسی وضعیت دیتابیس")
    
    # بررسی اتصال
    if not check_database_connection():
        print("❌ عدم امکان ادامه بررسی به دلیل مشکل در اتصال به دیتابیس")
        return
    
    # بررسی جداول
    check_tables()
    
    # بررسی رکوردها
    check_records()
    
    # پرسش برای تغییر stack_num
    answer = input("\nآیا می‌خواهید تمام تصاویر به stack_num=0 تغییر یابند؟ (y/n): ")
    if answer.lower() == 'y':
        fix_stack_nums(0)
    
    print("\n✅ بررسی دیتابیس با موفقیت به پایان رسید")

if __name__ == "__main__":
    main() 
