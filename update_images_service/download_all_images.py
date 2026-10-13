import os
import sys
import urllib.request
import cv2
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
import pickle
import logging
from pathlib import Path
import time
import concurrent.futures
import glob

# Add the main directory to Python path
sys.path.append('/home/morteza/services')
from main.models import Images, Base, engine
from main.colordescriptor import AdvancedImageDescriptor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/morteza/services/main/image_processing.log'),
        logging.StreamHandler()
    ]
)

# Constants
BASE_URL = "http://boomilia.com/media/media/"
STACKS_DIR = "/home/morteza/services/main/stacks/"
MAX_WORKERS = 10
TIMEOUT = 30
MAX_RETRIES = 3
STACK_SIZE = 1000

# Initialize descriptor
descriptor = AdvancedImageDescriptor()

def ensure_dir(directory):
    """Ensure directory exists with proper permissions"""
    try:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        # Set permissions to 755
        os.chmod(directory, 0o755)
        logging.info(f"Directory {directory} created/verified")
    except Exception as e:
        logging.error(f"Error creating directory {directory}: {str(e)}")
        raise

def check_database():
    """Check if database exists and has data"""
    try:
        # Use the session from models module
        with Images().__ss__() as session:
            # Count images
            count = session.query(Images).count()
            logging.info(f"Found {count} images in database")
            
            # Check a sample image
            sample = session.query(Images).first()
            if sample:
                logging.info(f"Sample image found: ID={sample.id}, URL={sample.URL}")
            else:
                logging.warning("No sample image found in database")
            
            return True
            
    except Exception as e:
        logging.error(f"Error checking database: {str(e)}")
        return False

def process_image(image_id, url):
    """Process image and extract features without saving the image"""
    for attempt in range(MAX_RETRIES):
        try:
            # Determine if URL is complete or needs BASE_URL
            if not url.startswith('http'):
                full_url = BASE_URL + url
            else:
                full_url = url

            # Download image
            req = urllib.request.Request(full_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                img_data = response.read()
                
            # Convert to numpy array
            img_array = np.asarray(bytearray(img_data), dtype=np.uint8)
            image = cv2.imdecode(img_array, -1)
            
            if image is None:
                raise Exception("Could not decode image")

            # Create a dictionary to store multiple feature types
            features_dict = {}
            
            # Extract features using advanced descriptor
            features_dict['advanced'] = descriptor.describe(image)
            
            # Extract neural features if neural network is available
            if neural_net is not None:
                neural_features = extract_neural_features(image, neural_net)
                if neural_features is not None:
                    features_dict['neural'] = neural_features
            
            return True, image_id, features_dict
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                logging.error(f"Error processing {url} after {MAX_RETRIES} attempts: {str(e)}")
                return False, image_id, None
            logging.warning(f"Attempt {attempt + 1} failed for {url}: {str(e)}")
            continue

def encode(num, alphabet="0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    """تبدیل عدد به رشته با الفبای مشخص"""
    if num == 0:
        return alphabet[0]
    arr = []
    base = len(alphabet)
    while num:
        num, rem = divmod(num, base)
        arr.append(alphabet[rem])
    return ''.join(arr[::-1])

def save_stack(stack_num, features_dict):
    """Save features to a stack file using an extensible format with metadata"""
    try:
        # Determine what feature types are available in the first image
        first_id = next(iter(features_dict))
        first_features = features_dict[first_id]
        available_feature_types = first_features.keys()
        
        # Create a structured dictionary that includes metadata
        stack_data = {
            "metadata": {
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "version": "1.0.0",
                "feature_types": list(available_feature_types),
                "descriptors": {
                    "advanced": {
                        "type": "AdvancedImageDescriptor",
                        "params": {
                            "color_bins": getattr(descriptor, "color_bins", (8, 12, 3)),
                            "lbp_radius": getattr(descriptor, "lbp_radius", 3),
                            "lbp_points": getattr(descriptor, "lbp_points", 24)
                        }
                    },
                    "neural": {
                        "type": "MobileNetV2",
                        "available": neural_net is not None
                    } if neural_net is not None else None
                },
                "dimensions": {
                    ftype: first_features[ftype].shape[0] for ftype in available_feature_types
                }
            },
            "images": {}
        }
        
        # Add features for each image
        for id, img_features in features_dict.items():
            encoded_id = encode(id)
            stack_data["images"][encoded_id] = {
                "features": img_features,
                "original_id": id  # Keep the original ID for reference
            }
            
        # Save as npz file
        stack_path = os.path.join(STACKS_DIR, f"stack{stack_num}.npz")
        np.savez(stack_path, np.array(stack_data, dtype=np.object_))
        
        # Also save a JSON metadata file for easy inspection
        json_path = os.path.join(STACKS_DIR, f"stack{stack_num}_meta.json")
        with open(json_path, 'w') as f:
            import json
            # Create a simpler version of metadata for JSON
            json_metadata = stack_data["metadata"].copy()
            json_metadata["image_count"] = len(stack_data["images"])
            json_metadata["image_ids"] = list(stack_data["images"].keys())[:10] + ["..."] if len(stack_data["images"]) > 10 else list(stack_data["images"].keys())
            json.dump(json_metadata, f, indent=2)
            
        # Set permissions
        os.chmod(stack_path, 0o644)
        os.chmod(json_path, 0o644)
        
        logging.info(f"Stack {stack_num} saved successfully with {len(features_dict)} images")
    except Exception as e:
        logging.error(f"Error saving stack {stack_num}: {str(e)}")
        raise

def init_neural_network():
    """Initialize a pre-trained neural network for feature extraction that works on CPU"""
    try:
        # Check if OpenCV's DNN module is available
        if hasattr(cv2, 'dnn'):
            logging.info("Initializing neural network feature extractor...")
            
            # Use a lightweight model appropriate for CPU
            # MobileNet is a good choice for CPU - small and efficient
            model_file = "/home/morteza/services/main/models/mobilenet_v2.caffemodel"
            config_file = "/home/morteza/services/main/models/mobilenet_v2.prototxt"
            
            # Create directory for models if it doesn't exist
            os.makedirs(os.path.dirname(model_file), exist_ok=True)
            
            # Check if model exists, if not, download it
            if not os.path.exists(model_file) or not os.path.exists(config_file):
                logging.warning("Neural network model files not found. Using fallback method.")
                return None
            
            # Load the network
            try:
                net = cv2.dnn.readNetFromCaffe(config_file, model_file)
                logging.info("Neural network initialized successfully")
                return net
            except Exception as e:
                logging.error(f"Failed to load neural network: {str(e)}")
                return None
        else:
            logging.warning("OpenCV DNN module not available")
            return None
    except Exception as e:
        logging.error(f"Error initializing neural network: {str(e)}")
        return None

def extract_neural_features(image, net):
    """Extract features using a neural network"""
    if net is None:
        return None
        
    try:
        # Prepare the image (resize, normalize, etc.)
        blob = cv2.dnn.blobFromImage(image, 1.0/255, (224, 224), (0, 0, 0), swapRB=True, crop=False)
        
        # Set the input and perform forward pass
        net.setInput(blob)
        features = net.forward()
        
        # Normalize the features
        features = features.flatten()
        norm = np.linalg.norm(features)
        if norm > 0:
            features = features / norm
            
        return features
    except Exception as e:
        logging.error(f"Error extracting neural features: {str(e)}")
        return None

# Try to initialize neural network
neural_net = init_neural_network()

def main():
    try:
        # Check database first
        if not check_database():
            logging.error("Database check failed. Please make sure the database exists and has data.")
            return

        # Ensure stacks directory exists
        ensure_dir(STACKS_DIR)
        
        # Also ensure models directory exists
        models_dir = "/home/morteza/services/main/models"
        ensure_dir(models_dir)

        # Find the last saved stack number
        stack_files = glob.glob(os.path.join(STACKS_DIR, "stack*.npz"))
        last_stack_num = -1
        if stack_files:
            for stack_file in stack_files:
                try:
                    stack_num = int(os.path.basename(stack_file).replace("stack", "").replace(".npz", ""))
                    last_stack_num = max(last_stack_num, stack_num)
                except ValueError:
                    continue
        
        logging.info(f"Last saved stack found: {last_stack_num if last_stack_num >= 0 else 'None'}")
        current_stack_num = last_stack_num + 1 if last_stack_num >= 0 else 0
        
        # Log what feature types are being extracted
        logging.info("Feature extraction configuration:")
        logging.info(f"  - Advanced descriptor: Enabled")
        logging.info(f"  - Neural network: {'Enabled' if neural_net is not None else 'Disabled (models not found)'}")
        logging.info(f"  - Resuming from stack {current_stack_num}")

        # Get all images from database
        logging.info("Fetching images from database...")
        with Images().__ss__() as session:
            # Get only unprocessed images or images that were in the last stack (might be incomplete)
            images = session.query(Images).filter(
                (Images.processed == False) | 
                ((Images.stack_num == last_stack_num) & (Images.processed == True))
            ).all()
            
            total_images = len(images)
            logging.info(f"Found {total_images} images to process")

            if total_images == 0:
                logging.info("No new images to process. All images have been processed.")
                return

            # Process images in parallel
            logging.info("Processing images and creating stacks...")
            success_count = 0
            failed_count = 0
            current_stack = {}
            
            # Create a progress bar with more information
            progress_bar = tqdm(
                total=total_images, 
                desc="Processing images",
                bar_format="{l_bar}{bar} | {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"
            )
            
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {}
                
                # Submit all tasks
                for image in images:
                    future = executor.submit(process_image, image.id, image.URL)
                    futures[future] = image.id
                
                # Process results as they complete
                for future in concurrent.futures.as_completed(futures):
                    img_id = futures[future]
                    try:
                        success, image_id, features_dict = future.result()
                        
                        if success:
                            success_count += 1
                            current_stack[image_id] = features_dict
                            
                            # Update image as processed
                            img = session.query(Images).filter(Images.id == image_id).first()
                            if img:
                                img.processed = True
                                img.have_error = False
                            
                            # Save stack if it's full
                            if len(current_stack) >= STACK_SIZE:
                                save_stack(current_stack_num, current_stack)
                                
                                # Update stack numbers for these images
                                for id in current_stack.keys():
                                    img = session.query(Images).filter(Images.id == id).first()
                                    if img:
                                        img.stack_num = current_stack_num
                                
                                current_stack = {}
                                current_stack_num += 1
                                
                                # Commit changes for this batch
                                session.commit()
                                logging.info(f"Committed changes for stack {current_stack_num-1}")
                        else:
                            failed_count += 1
                            # Mark image as having error
                            img = session.query(Images).filter(Images.id == image_id).first()
                            if img:
                                img.have_error = True
                    
                    except Exception as e:
                        logging.error(f"Error processing image {img_id}: {str(e)}")
                        failed_count += 1
                        
                        # Mark image as having error
                        img = session.query(Images).filter(Images.id == img_id).first()
                        if img:
                            img.have_error = True
                    
                    # Update progress bar
                    progress_bar.update(1)
                    
                    # Periodically commit changes
                    if (success_count + failed_count) % 1000 == 0:
                        session.commit()
                        logging.info(f"Committed changes after processing {success_count + failed_count} images")
            
            # Close progress bar
            progress_bar.close()

            # Save remaining images in the last stack
            if current_stack:
                save_stack(current_stack_num, current_stack)
                
                # Update stack numbers for remaining images
                for id in current_stack.keys():
                    img = session.query(Images).filter(Images.id == id).first()
                    if img:
                        img.stack_num = current_stack_num

            # Commit all changes
            session.commit()

            logging.info(f"\nProcessing complete:")
            logging.info(f"Successfully processed: {success_count}")
            logging.info(f"Failed to process: {failed_count}")
            logging.info(f"Created stacks from {last_stack_num + 1 if last_stack_num >= 0 else 0} to {current_stack_num}")

    except Exception as e:
        logging.error(f"Critical error in main process: {str(e)}")
        raise

if __name__ == "__main__":
    main() 
