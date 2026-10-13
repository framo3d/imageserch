import cv2
import imutils
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import os
# from numba import jit, prange # Numba not used in current logic, can be removed if not planned
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def dhash(image, hash_size=8):
    """
    Compute difference hash for an image.
    This creates a hash where each bit is the result of comparing
    adjacent pixels in a grayscale image.
    """
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Resize to hash_size + 1 x hash_size
    resized = cv2.resize(gray, (hash_size + 1, hash_size))
    
    # Compute differences between adjacent pixels
    diff = resized[:, 1:] > resized[:, :-1]
    
    # Convert to hash value
    return sum([2 ** i for (i, v) in enumerate(diff.flatten()) if v])

class ColorDescriptor:
    def __init__(self, bins):
        """
        Initialize color descriptor with specified number of bins
        for each channel (hue, saturation, value).
        """
        self.bins = bins
        # self.executor = ThreadPoolExecutor(max_workers=4) # Executor not used, can be removed
        # تنظیم تشخیص‌دهنده‌های ویژگی‌ها
        self.surf = None # SURF often has patent issues, ensure it's correctly installed or disable
        self.orb = cv2.ORB_create(nfeatures=1500)
        try:
            self.sift = cv2.SIFT_create(nfeatures=300) # Ensure nfeatures is appropriate
        except AttributeError: # More specific exception for cv2.SIFT_create() not found
            try:
                self.sift = cv2.xfeatures2d.SIFT_create(nfeatures=300)
            except AttributeError: # More specific exception for cv2.xfeatures2d.SIFT_create()
                self.sift = None
                logger.warning("SIFT not available. Consider installing opencv-contrib-python if needed.")
        
        # SURF initialization (often problematic due to patents)
        if self.sift is None: # Only try SURF if SIFT is also unavailable, or based on preference
            try:
                self.surf = cv2.xfeatures2d.SURF_create(400) # Ensure this is available/needed
                logger.info("SURF detector created.")
            except AttributeError:
                self.surf = None
                logger.warning("SURF not available (cv2.xfeatures2d.SURF_create failed).")
            except cv2.error as e:
                self.surf = None
                logger.warning(f"SURF not available (cv2.error): {e}")


    def describe(self, image):
        """
        Extract features from an image by dividing it into 5 regions
        (4 corners and 1 central ellipse) and computing a color histogram for each.
        Also computes an image hash and local feature descriptors (SIFT/ORB).
        """
        if image is None or image.size == 0:
            raise ValueError("Invalid image: None or empty")
            
        if image.shape[0] < 100 or image.shape[1] < 100:
            image = cv2.resize(image, (max(100, image.shape[1]), max(100, image.shape[0])))
            
        features = []
        (h, w) = image.shape[:2]
        
        masks = self._create_masks(h, w)
        
        for mask in masks:
            hist = self.histogram(image, mask)
            features.extend(hist)
        
        image_hash = dhash(image, hash_size=16)
        
        # استخراج ویژگی‌های محلی (SIFT یا ORB)
        keypoints, local_descriptors = None, None
        gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) # SIFT/ORB work on grayscale

        try:
            if self.sift is not None:
                keypoints, local_descriptors = self.sift.detectAndCompute(gray_image, None)
            elif self.orb is not None: # Fallback to ORB if SIFT is not available or failed
                keypoints, local_descriptors = self.orb.detectAndCompute(gray_image, None)
            # Add SURF as another fallback if desired and available
            # elif self.surf is not None:
            # keypoints, local_descriptors = self.surf.detectAndCompute(gray_image, None)
        except cv2.error as e:
            logger.warning(f"Error during SIFT/ORB detectAndCompute: {e}")
            local_descriptors = None # Ensure it's None on error

        if local_descriptors is None or local_descriptors.size == 0:
            # Return a consistent empty-like descriptor if none are found or on error
            # For ORB, descriptor size is 32. For SIFT, it's 128.
            # Using a fixed small size like (1, 32) might be problematic if type matters.
            # np.array([]) or np.empty((0,N)) is safer. Let's use (0,128) as a general placeholder,
            # but BFMatcher might not like it. The compare function needs to handle this.
            # A (1, N) array of zeros is also an option.
            default_desc_len = 128 # SIFT default
            if self.orb is not None and self.sift is None: # If only ORB is active
                 default_desc_len = self.orb.getDescriptorSize() if hasattr(self.orb, 'getDescriptorSize') else 32

            local_descriptors = np.zeros((1, default_desc_len), dtype=np.float32)


        return (np.array(features, dtype=np.float32), image_hash, local_descriptors.astype(np.float32))
    
    def _create_masks(self, height, width):
        """
        Create masks for the 5 regions of the image:
        - Center ellipse
        - Top-left corner
        - Top-right corner
        - Bottom-right corner
        - Bottom-left corner
        """
        masks = []
        
        center_x, center_y = width // 2, height // 2
        # Adjust corner and ellipse sizes to be more distinct and cover different areas
        corner_width = width // 4 
        corner_height = height // 4
        ellipse_axes = (width // 4, height // 4) # Make ellipse smaller to be more central
        
        # Corner regions (clockwise from top-left)
        corners = [
            (0, 0, corner_width, corner_height),                      # Top-left
            (width - corner_width, 0, width, corner_height),          # Top-right
            (width - corner_width, height - corner_height, width, height),  # Bottom-right
            (0, height - corner_height, corner_width, height)         # Bottom-left
        ]
        
        for (x_start, y_start, x_end, y_end) in corners:
            mask = np.zeros((height, width), dtype="uint8")
            cv2.rectangle(mask, (x_start, y_start), (x_end, y_end), 255, -1)
            masks.append(mask)
        
        center_mask = np.zeros((height, width), dtype="uint8")
        cv2.ellipse(center_mask, (center_x, center_y), ellipse_axes, 0, 0, 360, 255, -1)
        masks.append(center_mask)
        
        return masks
    
    def histogram(self, image, mask=None):
        """
        Extract a 3D color histogram from the masked region of the image.
        """
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], mask, self.bins, 
                             [0, 180, 0, 256, 0, 256])
        # Normalize histogram using L2 norm for potentially better chi-squared results
        cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        # hist = cv2.normalize(hist, hist).flatten() # Original normalization
        return hist.flatten()
    
    def compare(self, features1, hash1, desc1, features2, hash2, desc2):
        """
        Compare two images based on their features (color, hash, local).
        Returns a similarity value between 0 and 1 (higher is more similar).
        """
        if features1 is None or features2 is None or hash1 is None or hash2 is None:
            logger.warning("Null input (features or hash) to compare function")
            return 0.0
            
        # 1. Hash Similarity
        hash_similarity = 0.0
        try:
            # Ensure hashes are integers for bitwise XOR
            h1_int = int(hash1)
            h2_int = int(hash2)
            hash_distance = bin(h1_int ^ h2_int).count('1')
            # Assuming hash_size=16, so 256 bits
            hash_similarity = 1.0 - (hash_distance / 256.0) 
        except Exception as e:
            logger.error(f"Error calculating hash similarity: {e}. hash1: {hash1}, hash2: {hash2}")
            hash_similarity = 0.0
        
        # 2. Color Feature Similarity (Chi-squared)
        feature_similarity = 0.0
        eps = 1e-10
        try:
            if len(features1) != len(features2):
                logger.warning(f"Feature length mismatch: {len(features1)} vs {len(features2)}")
                feature_similarity = 0.0
            elif np.any(np.isnan(features1)) or np.any(np.isnan(features2)):
                logger.warning("NaN values found in features.")
                feature_similarity = 0.0
            else:
                # Ensure features are positive for chi-squared, add eps to avoid division by zero
                f1 = np.maximum(features1, eps)
                f2 = np.maximum(features2, eps)
                
                chi_squared = 0.5 * np.sum(((f1 - f2) ** 2) / (f1 + f2)) # Denominator already has eps implicitly
                # Convert distance to similarity (closer to 0 is more similar)
                # The exp(-chi_squared) is a common way. Adjust scale if necessary.
                feature_similarity = np.exp(-chi_squared) 
                
                # Boost similarity for very close matches (low chi_squared)
                if chi_squared < 0.05: # This threshold might need tuning
                    feature_similarity = 1.0
                elif chi_squared < 0.1:
                    feature_similarity = max(feature_similarity, 0.9)


        except Exception as e:
            logger.error(f"Error comparing color features: {e}")
            feature_similarity = 0.0
        
        # 3. Local Feature Similarity (SIFT/ORB Matches)
        local_score = 0.0
        
        # Check if both descriptors are valid NumPy arrays with actual data
        # Placeholder zero arrays should not be matched.
        valid_desc1 = isinstance(desc1, np.ndarray) and desc1.ndim == 2 and desc1.shape[0] > 0 and desc1.shape[1] > 0 and not np.all(desc1 == 0)
        valid_desc2 = isinstance(desc2, np.ndarray) and desc2.ndim == 2 and desc2.shape[0] > 0 and desc2.shape[1] > 0 and not np.all(desc2 == 0)

        if valid_desc1 and valid_desc2:
            try:
                # Ensure descriptors are float32, as SIFT/ORB typically output this
                # and BFMatcher expects CV_32F or CV_8U
                d1 = desc1.astype(np.float32) if desc1.dtype != np.float32 else desc1
                d2 = desc2.astype(np.float32) if desc2.dtype != np.float32 else desc2

                # Check descriptor compatibility (e.g. SIFT vs ORB length)
                if d1.shape[1] != d2.shape[1]:
                    logger.warning(f"Local descriptor dimension mismatch: {d1.shape[1]} vs {d2.shape[1]}. Cannot match.")
                else:
                    matcher_type = cv2.DescriptorMatcher_BRUTEFORCE_HAMMING if d1.dtype == np.uint8 else cv2.DescriptorMatcher_BRUTEFORCE_L1
                    bf = cv2.BFMatcher(matcher_type, crossCheck=False) # crossCheck can be True for more robust matches
                    
                    matches = bf.knnMatch(d1, d2, k=2)
                    
                    good_matches = []
                    if matches and len(matches) > 0 and len(matches[0]) == 2: # Ensure knnMatch returned pairs
                        for m, n in matches:
                            if m.distance < 0.75 * n.distance: # Lowe's ratio test
                                good_matches.append(m)
                    
                    # Normalize score: e.g. based on a typical number of good matches (e.g., 50)
                    # or relative to the minimum number of keypoints in the two images
                    min_kps = min(d1.shape[0], d2.shape[0])
                    if min_kps > 0 :
                        local_score = min(len(good_matches) / float(min_kps) * 2.0, 1.0) # Heuristic, factor of 2.0 to boost a bit
                        if len(good_matches) > 10 : # If there are at least some strong matches
                           local_score = max(local_score, len(good_matches)/50.0) # Alternative normalization
                        local_score = min(local_score, 1.0) # Cap at 1.0
                    else:
                        local_score = 0.0
                    
                    if len(good_matches) < 5 and min_kps > 10: # Penalize if very few matches despite having keypoints
                        local_score *= 0.5


            except cv2.error as cv_err:
                logger.warning(f"OpenCV error during local feature matching: {cv_err}. desc1 shape: {desc1.shape if isinstance(desc1, np.ndarray) else 'Not ndarray'}, desc2 shape: {desc2.shape if isinstance(desc2, np.ndarray) else 'Not ndarray'}")
                local_score = 0.0
            except Exception as e_match:
                logger.warning(f"Generic error during local feature matching: {e_match}")
                local_score = 0.0
        
        # 4. Combine Similarities
        # Weights: Hash (0.3), Color Hist (0.4), Local Features (0.3) - adjust as needed
        # If local_score is meaningful (e.g., > 0.1, meaning at least a few good matches)
        # These weights are crucial and need tuning based on dataset and desired behavior.
        w_hash, w_color, w_local = 0.3, 0.4, 0.3

        if not (valid_desc1 and valid_desc2) or local_score < 0.05: # If no valid local comparison
            # Redistribute local_score's weight to hash and color
            w_hash += w_local / 2
            w_color += w_local / 2
            w_local = 0.0
            
        combined_similarity = (hash_similarity * w_hash) + \
                              (feature_similarity * w_color) + \
                              (local_score * w_local)
        
        # Ensure similarity is capped at 1.0
        combined_similarity = min(combined_similarity, 1.0)

        # if DEBUG_SEARCH or combined_similarity > 0.5: # For debugging
        #     print(f"H:{hash_similarity:.2f} C:{feature_similarity:.2f} L:{local_score:.2f} -> Comb:{combined_similarity:.2f}")

        return combined_similarity

def monitor_performance():
    from threadpoolctl import threadpool_info
    import psutil
    print(f"Active Threads: {len(threadpool_info())}")
    print(f"CPU Usage: {psutil.cpu_percent(percpu=True)}")

def adjust_permissions():
    file_path = os.path.abspath(__file__)
    os.chmod(file_path, 0o644)  # Read/write for owner, read for others
    logger.info("Adjusted file permissions for %s", file_path)

# اضافه کردن کتابخانه‌های مورد نیاز
try:
    from scipy import spatial
except ImportError:
    # در صورت عدم نصب scipy، پیاده‌سازی ساده فاصله کسینوسی
    def cosine_distance(u, v):
        dot_product = np.dot(u, v)
        norm_u = np.linalg.norm(u)
        norm_v = np.linalg.norm(v)
        if norm_u == 0 or norm_v == 0:
            return 1.0  # حداکثر فاصله
        return 1.0 - (dot_product / (norm_u * norm_v))
    
    # کلاس جعلی برای جایگزینی
    class SpatialMock:
        class distance:
            @staticmethod
            def cosine(u, v):
                return cosine_distance(u, v)
    
    # جایگزینی با پیاده‌سازی موقت
    spatial = SpatialMock()

# تست سریع برای اطمینان از عملکرد درست
def test_descriptor():
    import traceback # For detailed error in test
    try:
        # ساخت یک تصویر آزمایشی
        test_image_flat = np.ones((200, 200, 3), dtype=np.uint8) * 128 # Flat image
        test_image_texture = np.random.randint(0, 256, (200, 200, 3), dtype=np.uint8) # Textured

        cd_test = ColorDescriptor((8, 12, 3))
        
        print("Testing with flat image...")
        features1, hash1, descriptors1 = cd_test.describe(test_image_flat)
        similarity1 = cd_test.compare(features1, hash1, descriptors1, features1, hash1, descriptors1)
        print(f"Self-similarity (flat image): {similarity1}")
        if abs(similarity1 - 1.0) < 0.05: # Allow some tolerance
            print("Self-similarity test (flat image) passed!")
        else:
            print(f"Self-similarity test (flat image) failed! (Expected ~1.0, got {similarity1})")

        print("\nTesting with textured image...")
        features2, hash2, descriptors2 = cd_test.describe(test_image_texture)
        similarity2 = cd_test.compare(features2, hash2, descriptors2, features2, hash2, descriptors2)
        print(f"Self-similarity (textured image): {similarity2}")
        if abs(similarity2 - 1.0) < 0.05: # Allow some tolerance
            print("Self-similarity test (textured image) passed!")
        else:
            print(f"Self-similarity test (textured image) failed! (Expected ~1.0, got {similarity2})")
            
        # Test with two different images
        features_diff, hash_diff, descriptors_diff = cd_test.describe(np.random.randint(0,255, (200,200,3), dtype=np.uint8))
        similarity_diff = cd_test.compare(features1, hash1, descriptors1, features_diff, hash_diff, descriptors_diff)
        print(f"Similarity between flat and random image: {similarity_diff} (expected low)")


    except Exception as e:
        print(f"Test failed with error: {e}")
        traceback.print_exc()

if __name__ == '__main__':
    # test_descriptor() # You can run this to test
    pass


