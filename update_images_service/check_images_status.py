#!/usr/bin/env python3
"""
اسکریپت بررسی وضعیت تصاویر در دیتابیس
این اسکریپت آمار دقیقی از وضعیت تصاویر در دیتابیس ارائه می‌دهد
"""

import os
import sys
import glob
import logging
from collections import defaultdict

# Add the main directory to Python path
sys.path.append('/home/morteza/services')
from main.models import Images, Base, engine

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/morteza/services/main/image_processing.log'),
        logging.StreamHandler()
    ]
)

def check_stacks_directory():
    """Check the stacks directory and count files"""
    stacks_dir = "/home/morteza/services/main/stacks/"
    if not os.path.exists(stacks_dir):
        logging.error(f"Stacks directory not found: {stacks_dir}")
        return {}
    
    # Count stack files and get their sizes
    stack_files = glob.glob(os.path.join(stacks_dir, "stack*.npz"))
    stack_info = {}
    
    for stack_file in stack_files:
        try:
            stack_num = int(os.path.basename(stack_file).replace("stack", "").replace(".npz", ""))
            stack_size = os.path.getsize(stack_file) / (1024 * 1024)  # Size in MB
            stack_info[stack_num] = stack_size
        except ValueError:
            continue
    
    return stack_info

def main():
    try:
        logging.info("Checking images status...")
        
        # First, check stacks directory
        stack_info = check_stacks_directory()
        
        if stack_info:
            max_stack_num = max(stack_info.keys())
            total_stacks = len(stack_info)
            total_size_mb = sum(stack_info.values())
            avg_size_mb = total_size_mb / total_stacks if total_stacks > 0 else 0
            
            logging.info(f"Found {total_stacks} stack files (0 to {max_stack_num})")
            logging.info(f"Total size of all stacks: {total_size_mb:.2f} MB")
            logging.info(f"Average stack size: {avg_size_mb:.2f} MB")
        else:
            logging.warning("No stack files found")
        
        # Check images in database
        with Images().__ss__() as session:
            # Count total images
            total_images = session.query(Images).count()
            logging.info(f"Total images in database: {total_images}")
            
            # Count processed images
            processed_images = session.query(Images).filter(Images.processed == True).count()
            logging.info(f"Processed images: {processed_images} ({processed_images/total_images*100:.1f}%)")
            
            # Count images with errors
            error_images = session.query(Images).filter(Images.have_error == True).count()
            logging.info(f"Images with errors: {error_images} ({error_images/total_images*100:.1f}%)")
            
            # Count unprocessed images
            unprocessed_images = session.query(Images).filter(Images.processed == False, Images.have_error == False).count()
            logging.info(f"Unprocessed images: {unprocessed_images} ({unprocessed_images/total_images*100:.1f}%)")
            
            # Count by stack number
            images_by_stack = defaultdict(int)
            stack_nums = session.query(Images.stack_num).filter(Images.stack_num != None).distinct()
            for (stack_num,) in stack_nums:
                count = session.query(Images).filter(Images.stack_num == stack_num).count()
                images_by_stack[stack_num] = count
            
            logging.info(f"Images with assigned stack numbers: {sum(images_by_stack.values())}")
            
            # Check for inconsistencies
            inconsistent = session.query(Images).filter(
                Images.processed == True, 
                Images.stack_num == None
            ).count()
            if inconsistent > 0:
                logging.warning(f"Found {inconsistent} images marked as processed but without a stack number")
            
            # Sample some problematic images for inspection
            if error_images > 0:
                sample_errors = session.query(Images).filter(Images.have_error == True).limit(5).all()
                logging.info("Sample error images:")
                for img in sample_errors:
                    logging.info(f"  - ID: {img.id}, URL: {img.URL}")
            
            # Output summary
            logging.info("\nSUMMARY:")
            logging.info(f"Total images: {total_images}")
            logging.info(f"Processed successfully: {processed_images - error_images}")
            logging.info(f"Processed with errors: {error_images}")
            logging.info(f"Not yet processed: {unprocessed_images}")
            
            # Verification
            expected_processed = sum(images_by_stack.values())
            if expected_processed != processed_images - inconsistent:
                logging.warning(f"Inconsistency detected: {expected_processed} images in stacks vs {processed_images} marked as processed")
                    
    except Exception as e:
        logging.error(f"Error checking images status: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 
