import cv2
import numpy as np
from skimage.feature import hog, local_binary_pattern
from skimage.color import rgb2gray
from scipy.spatial.distance import cosine
import threading
import functools
import time
from concurrent.futures import ThreadPoolExecutor


class AdvancedImageDescriptor:
    def __init__(self):
        # پارامترهای توصیف‌کننده تصویر
        self.color_bins = (8, 12, 3)  # حفظ سازگاری با نسخه قبلی
        self.lbp_radius = 3
        self.lbp_points = 24
        self.feature_cache = {}  # کش داخلی
        self.max_cache_size = 100
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=12)  # افزایش تعداد ترد برای سرعت بیشتر
    
    def describe(self, image):
        """استخراج ویژگی‌های پیشرفته از تصویر"""
        if image is None:
            print("⚠️ تصویر ورودی خالی است")
            return np.zeros(512)  # بردار ویژگی بزرگتر برای نتایج بهتر
            
        try:
            # بهینه‌سازی اندازه تصویر
            max_dim = 400  # کاهش اندازه برای سرعت بیشتر
            h, w = image.shape[:2]
            if max(h, w) > max_dim:
                scale = max_dim / max(h, w)
                image = cv2.resize(image, (int(w * scale), int(h * scale)))
            
            # بهبود کیفیت تصویر
            image = cv2.fastNlMeansDenoisingColored(image, None, 10, 10, 7, 21)  # حذف نویز
            
            # افزایش کنتراست
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            enhanced = cv2.merge((cl, a, b))
            enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
            
            # استخراج ویژگی‌ها به صورت موازی
            future_color = self.executor.submit(self._extract_color_features, enhanced)
            future_texture = self.executor.submit(self._extract_texture_features, enhanced)
            future_hog = self.executor.submit(self._extract_hog_features, enhanced)
            future_shape = self.executor.submit(self._extract_shape_features, enhanced)
            
            # دریافت نتایج
            color_feat = future_color.result()
            texture_feat = future_texture.result()
            hog_feat = future_hog.result()
            shape_feat = future_shape.result()
            
            # ترکیب ویژگی‌ها با وزن‌دهی مناسب
            combined = np.concatenate([
                color_feat * 0.45,    # رنگ (اهمیت بالا)
                texture_feat * 0.25,  # بافت
                hog_feat * 0.2,       # لبه‌ها
                shape_feat * 0.1      # شکل
            ])
            
            # نرمال‌سازی
            norm = np.linalg.norm(combined)
            if norm > 0:
                combined = combined / norm
                
            return combined
        except Exception as e:
            print(f"❌ خطا در استخراج ویژگی: {str(e)}")
            import traceback
            traceback.print_exc()
            return np.zeros(512)  # بردار ویژگی خالی در صورت خطا
    
    def _extract_color_features(self, image):
        """استخراج ویژگی‌های رنگی با دقت بالاتر"""
        # تبدیل به HSV
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        
        # تبدیل به LAB - حساسیت بیشتر به تفاوت‌های رنگی
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        
        features = []
        
        # تقسیم تصویر به نواحی
        h, w = hsv.shape[:2]
        cx, cy = int(w * 0.5), int(h * 0.5)
        
        # مناطق شش‌گانه - افزایش دقت با تقسیم بیشتر
        regions = [
            (0, cx//2, 0, cy//2),      # بالا-چپ
            (cx//2, cx, 0, cy//2),     # بالا-وسط
            (cx, w, 0, cy//2),         # بالا-راست
            (0, cx//2, cy//2, cy),     # وسط-چپ
            (cx//2, cx, cy//2, cy),    # وسط-وسط
            (cx, w, cy//2, cy),        # وسط-راست
            (0, cx//2, cy, h),         # پایین-چپ
            (cx//2, cx, cy, h),        # پایین-وسط
            (cx, w, cy, h)             # پایین-راست
        ]
        
        # ناحیه بیضوی میانی
        ellipse_mask = np.zeros((h, w), dtype="uint8")
        ax, ay = int(w * 0.3), int(h * 0.3)  # بیضی کوچکتر برای تمرکز بیشتر روی مرکز تصویر
        cv2.ellipse(ellipse_mask, (cx, cy), (ax, ay), 0, 0, 360, 255, -1)
        
        # محاسبه هیستوگرام HSV برای هر ناحیه
        for sx, ex, sy, ey in regions:
            mask = np.zeros((h, w), dtype="uint8")
            cv2.rectangle(mask, (sx, sy), (ex, ey), 255, -1)
            mask = cv2.subtract(mask, ellipse_mask)
            
            # هیستوگرام HSV
            hsv_hist = cv2.calcHist([hsv], [0, 1, 2], mask, self.color_bins, [0, 180, 0, 256, 0, 256])
            hsv_hist = cv2.normalize(hsv_hist, hsv_hist).flatten()
            
            # هیستوگرام LAB - اضافه کردن اطلاعات رنگی بیشتر
            lab_hist = cv2.calcHist([lab], [0, 1, 2], mask, (8, 8, 8), [0, 255, 0, 255, 0, 255])
            lab_hist = cv2.normalize(lab_hist, lab_hist).flatten()
            
            features.extend(hsv_hist)
            features.extend(lab_hist)
        
        # ناحیه مرکزی
        hsv_center_hist = cv2.calcHist([hsv], [0, 1, 2], ellipse_mask, self.color_bins, [0, 180, 0, 256, 0, 256])
        hsv_center_hist = cv2.normalize(hsv_center_hist, hsv_center_hist).flatten()
        
        lab_center_hist = cv2.calcHist([lab], [0, 1, 2], ellipse_mask, (8, 8, 8), [0, 255, 0, 255, 0, 255])
        lab_center_hist = cv2.normalize(lab_center_hist, lab_center_hist).flatten()
        
        features.extend(hsv_center_hist)
        features.extend(lab_center_hist)
        
        return np.array(features)
    
    def _extract_texture_features(self, image):
        """استخراج ویژگی‌های بافت با LBP و متودهای دیگر"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # الگوی دودویی محلی (LBP) با چند مقیاس مختلف
        lbp_features = []
        
        # LBP با شعاع‌های مختلف
        for radius in [1, 2, 3]:
            points = 8 * radius
            lbp = local_binary_pattern(gray, points, radius, method='uniform')
            n_bins = points + 2
            hist, _ = np.histogram(lbp.ravel(), bins=n_bins, range=(0, n_bins), density=True)
            lbp_features.extend(hist)
        
        # محاسبه گرادیان 
        sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        magnitude = np.sqrt(sobelx**2 + sobely**2)
        
        # هیستوگرام گرادیان
        gradient_hist, _ = np.histogram(magnitude.ravel(), bins=10, density=True)
        
        # ترکیب ویژگی‌ها
        combined_texture = np.concatenate([lbp_features, gradient_hist])
        
        return combined_texture
    
    def _extract_hog_features(self, image):
        """استخراج ویژگی‌های HOG"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # پارامترهای HOG بهینه برای جستجوی تصویر
        hog_features = hog(gray, 
                          orientations=9, 
                          pixels_per_cell=(8, 8),  # سلول‌های کوچکتر برای دقت بیشتر
                          cells_per_block=(2, 2),
                          block_norm='L2-Hys',
                          feature_vector=True)
        
        return hog_features
    
    def _extract_shape_features(self, image):
        """استخراج ویژگی‌های شکل و لبه"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # تشخیص لبه با فیلترهای مختلف
        edges_canny = cv2.Canny(gray, 100, 200)
        
        # پیدا کردن کانتورها
        contours, _ = cv2.findContours(edges_canny, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # استخراج ویژگی‌های کانتور اصلی
        contour_features = []
        if contours:
            main_contour = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(main_contour)
            perimeter = cv2.arcLength(main_contour, True)
            if perimeter > 0:
                circularity = 4 * np.pi * area / (perimeter ** 2)
            else:
                circularity = 0
            contour_features.extend([area, perimeter, circularity])
        else:
            contour_features.extend([0, 0, 0])
        
        # استخراج ویژگی‌های لبه در بلوک‌ها
        h, w = edges_canny.shape
        blocks = 4
        block_h, block_w = h // blocks, w // blocks
        
        edge_features = []
        for i in range(blocks):
            for j in range(blocks):
                block = edges_canny[i*block_h:(i+1)*block_h, j*block_w:(j+1)*block_w]
                edge_count = np.count_nonzero(block) / (block_h * block_w)
                edge_features.append(edge_count)
        
        # ترکیب ویژگی‌های شکل
        shape_features = np.concatenate([contour_features, edge_features])
        
        return shape_features 
