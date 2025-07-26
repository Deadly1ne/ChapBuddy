import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import os

def trim_watermark(img):
    """
    Advanced watermark detection and trimming using OpenCV.
    Uses template matching for precise detection combined with pattern analysis.
    Only trims when confident watermarks are detected.
    """
    try:
        # Convert PIL image to OpenCV format
        img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        height, width = img_cv.shape[:2]
        
        # Method 1: Template matching for known watermarks (most accurate)
        template_top_trim, template_bottom_trim = _detect_template_watermark(img_cv)
        
        if template_top_trim > 0 or template_bottom_trim > 0:
            # Template matching found watermarks - use precise cropping
            crop_top = template_top_trim
            crop_bottom = height - template_bottom_trim
            
            # Safety check: preserve at least 60% of content
            if (crop_bottom - crop_top) >= int(height * 0.6):
                cropped_img = img.crop((0, crop_top, width, crop_bottom))
                print(f"Template watermark detected and trimmed: top={crop_top}px, bottom={template_bottom_trim}px")
                return cropped_img
        
        # Method 2: Fallback to pattern detection for unknown watermarks
        top_search_height = int(height * 0.2)
        bottom_search_height = int(height * 0.2)
        
        top_region = img_cv[0:top_search_height, :]
        bottom_region = img_cv[height-bottom_search_height:height, :]
        
        top_trim, top_confidence = _detect_watermark_opencv(top_region, 'top')
        bottom_trim, bottom_confidence = _detect_watermark_opencv(bottom_region, 'bottom')
        
        crop_top = min(top_trim, int(height * 0.15))
        crop_bottom = max(height - bottom_trim, int(height * 0.85))
        
        # EXTREMELY strict criteria: require MAXIMUM confidence and VERY LARGE watermark size
        should_trim_top = crop_top > 80 and top_confidence >= 3  # All 3 methods must agree AND large watermark
        should_trim_bottom = (height - crop_bottom) > 80 and bottom_confidence >= 3
        
        if should_trim_top or should_trim_bottom:
            if (crop_bottom - crop_top) >= int(height * 0.9):  # Preserve 90% of content
                cropped_img = img.crop((0, crop_top, width, crop_bottom))
                print(f"MAXIMUM-CONFIDENCE watermark detected and trimmed: top={crop_top}px (conf:{top_confidence}), bottom={height-crop_bottom}px (conf:{bottom_confidence})")
                return cropped_img
            else:
                print(f"Watermark detected but trimming would remove too much content. Skipping trim.")
        else:
            print(f"No maximum-confidence watermark detected. Top: {crop_top}px (conf:{top_confidence}), Bottom: {height-crop_bottom}px (conf:{bottom_confidence})")
        
        return img
        
    except Exception as e:
        print(f"Error in OpenCV watermark trimming: {e}")
        return img

def _detect_template_watermark(img_cv):
    """
    Template matching for known watermarks using cv2.matchTemplate().
    Loads real watermark templates from assets folder for precise detection.
    Returns (top_trim, bottom_trim) in pixels.
    """
    try:
        height, width = img_cv.shape[:2]
        
        # Load watermark templates from assets folder
        watermark_templates = _load_watermark_templates()
        
        # Add synthetic templates as fallback
        synthetic_templates = [
            ("synthetic_包子漫画", _create_text_template("包子漫画", width)),
            ("synthetic_baozi", _create_text_template("baozi", width)),
        ]
        
        # Filter out None templates and add to main list
        for name, template in synthetic_templates:
            if template is not None:
                watermark_templates.append((name, template))
        
        top_trim = 0
        bottom_trim = 0
        threshold = 0.7  # Slightly lower threshold for real templates
        
        for template_name, template in watermark_templates:
            if template is None:
                continue
                
            ref_h, ref_w = template.shape[:2]
            
            # Skip if template is larger than image
            if ref_h > height or ref_w > width:
                continue
            
            # Check top region
            search_height_top = min(ref_h + 50, height // 3)  # Search in top third
            top_area = img_cv[:search_height_top, :]
            
            if top_area.shape[0] >= ref_h and top_area.shape[1] >= ref_w:
                try:
                    res = cv2.matchTemplate(top_area, template, cv2.TM_CCOEFF_NORMED)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                    
                    if max_val >= threshold:
                        top_trim = max(top_trim, max_loc[1] + ref_h)
                        print(f"Template '{template_name}' match found at top (confidence={max_val:.2f})")
                except cv2.error:
                    continue
            
            # Check bottom region
            search_height_bottom = min(ref_h + 50, height // 3)
            bottom_area = img_cv[-search_height_bottom:, :]
            
            if bottom_area.shape[0] >= ref_h and bottom_area.shape[1] >= ref_w:
                try:
                    res = cv2.matchTemplate(bottom_area, template, cv2.TM_CCOEFF_NORMED)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                    
                    if max_val >= threshold:
                        # Calculate from bottom of image
                        match_from_bottom = search_height_bottom - max_loc[1]
                        bottom_trim = max(bottom_trim, match_from_bottom)
                        print(f"Template '{template_name}' match found at bottom (confidence={max_val:.2f})")
                except cv2.error:
                    continue
        
        return top_trim, bottom_trim
        
    except Exception as e:
        print(f"Error in template matching: {e}")
        return 0, 0

def _load_watermark_templates():
    """
    Load watermark templates from the assets folder.
    Supports multiple banner files for different watermark types.
    """
    templates = []
    assets_dir = "assets"
    
    try:
        if not os.path.exists(assets_dir):
            print(f"Assets directory not found: {assets_dir}")
            return templates
        
        # Load all image files from assets folder
        for filename in os.listdir(assets_dir):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                template_path = os.path.join(assets_dir, filename)
                template = cv2.imread(template_path)
                
                if template is not None:
                    templates.append((filename, template))
                    print(f"Loaded watermark template: {filename}")
                else:
                    print(f"Warning: Could not load template: {filename}")
        
        print(f"Total templates loaded: {len(templates)}")
        return templates
        
    except Exception as e:
        print(f"Error loading watermark templates: {e}")
        return templates

def _create_text_template(text, target_width):
    """
    Create a synthetic template for text-based watermarks.
    This helps detect text watermarks even without exact reference images.
    Uses PIL for proper Unicode/Chinese character support.
    """
    try:
        # Create a blank image for text rendering
        template_height = 80
        
        # Create PIL image (RGB format)
        pil_image = Image.new('RGB', (target_width, template_height), color=(255, 255, 255))
        draw = ImageDraw.Draw(pil_image)
        
        # Try to use a system font that supports Chinese characters
        try:
            # Try common Chinese fonts on Windows
            font_paths = [
                "C:/Windows/Fonts/msyh.ttc",  # Microsoft YaHei
                "C:/Windows/Fonts/simsun.ttc",  # SimSun
                "C:/Windows/Fonts/simhei.ttf",  # SimHei
                "C:/Windows/Fonts/arial.ttf",   # Arial (fallback)
            ]
            
            font = None
            font_size = 36
            
            for font_path in font_paths:
                try:
                    if os.path.exists(font_path):
                        font = ImageFont.truetype(font_path, font_size)
                        break
                except:
                    continue
            
            # Fallback to default font if no TrueType font found
            if font is None:
                font = ImageFont.load_default()
                
        except Exception as e:
            print(f"Font loading warning: {e}, using default font")
            font = ImageFont.load_default()
        
        # Get text bounding box for centering
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Center the text
        text_x = (target_width - text_width) // 2
        text_y = (template_height - text_height) // 2
        
        # Draw the text in black
        if text_x > 0 and text_y > 0:
            draw.text((text_x, text_y), text, fill=(0, 0, 0), font=font)
        
        # Convert PIL image back to OpenCV format (BGR)
        template = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        
        return template
        
    except Exception as e:
        print(f"Error creating text template: {e}")
        # Fallback to simple rectangle template if text rendering fails
        try:
            template_height = 80
            template = np.ones((template_height, target_width, 3), dtype=np.uint8) * 255
            # Create a simple black rectangle as fallback
            cv2.rectangle(template, (target_width//4, template_height//4), 
                         (3*target_width//4, 3*template_height//4), (0, 0, 0), 2)
            return template
        except:
            return None

def _detect_watermark_opencv(region, position):
    """
    Use OpenCV to detect watermark boundaries through multiple techniques:
    - Text detection
    - Edge detection
    - Color analysis
    Returns boundary position and confidence score (number of methods that detected watermark)
    """
    try:
        height, width = region.shape[:2]
        
        # Convert to grayscale for analysis
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        
        # Method 1: Text detection using morphological operations
        text_boundary = _detect_text_boundary(gray, position)
        
        # Method 2: Edge-based detection
        edge_boundary = _detect_edge_boundary(gray, position)
        
        # Method 3: Color uniformity detection
        color_boundary = _detect_color_boundary(region, position)
        
        # Count how many methods detected significant boundaries (confidence score)
        significant_boundaries = []
        confidence = 0
        
        if text_boundary > 100:  # VERY high threshold for text detection
            significant_boundaries.append(text_boundary)
            confidence += 1
            
        if edge_boundary > 100:  # VERY high threshold for edge detection
            significant_boundaries.append(edge_boundary)
            confidence += 1
            
        if color_boundary > 100:  # VERY high threshold for color pattern
            significant_boundaries.append(color_boundary)
            confidence += 1
        
        if significant_boundaries:
            # Use median of detected boundaries for robustness
            boundary = int(np.median(significant_boundaries))
            return boundary, confidence
        
        return 0, 0
        
    except Exception as e:
        print(f"Error in OpenCV boundary detection: {e}")
        return 0, 0

def _detect_text_boundary(gray, position):
    """
    Detect text regions using morphological operations.
    """
    try:
        height, width = gray.shape
        
        # Create morphological kernel for text detection
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        
        # Apply morphological operations to highlight text
        morph = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, kernel)
        
        # Threshold to get binary image
        _, thresh = cv2.threshold(morph, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Find contours (potential text regions)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if position == 'top':
            # Find the lowest text region from top - much stricter criteria
            max_y = 0
            text_regions = 0
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if w > 50 and h > 15:  # Much larger minimum size for text
                    max_y = max(max_y, y + h)
                    text_regions += 1
            # Only return if we found MANY substantial text regions (watermarks have lots of text)
            return max_y if text_regions >= 5 else 0
        
        elif position == 'bottom':
            # Find the highest text region from bottom - much stricter criteria
            min_y = height
            text_regions = 0
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if w > 50 and h > 15:  # Much larger minimum size for text
                    min_y = min(min_y, y)
                    text_regions += 1
            # Only return if we found MANY substantial text regions (watermarks have lots of text)
            return height - min_y if text_regions >= 5 else 0
        
        return 0
        
    except Exception as e:
        return 0

def _detect_edge_boundary(gray, position):
    """
    Detect boundaries using edge detection.
    """
    try:
        height, width = gray.shape
        
        # Apply Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Edge detection
        edges = cv2.Canny(blurred, 50, 150)
        
        # Analyze edge density by rows - EXTREMELY conservative
        if position == 'top':
            for y in range(height):
                row_edges = np.sum(edges[y, :]) / width
                if row_edges < 2:  # EXTREMELY high threshold - only completely blank areas
                    return y
        
        elif position == 'bottom':
            for y in range(height - 1, -1, -1):
                row_edges = np.sum(edges[y, :]) / width
                if row_edges < 2:  # EXTREMELY high threshold - only completely blank areas
                    return height - y
        
        return 0
        
    except Exception as e:
        return 0

def _detect_color_boundary(region, position):
    """
    Detect boundaries based on color uniformity and background detection.
    """
    try:
        height, width = region.shape[:2]
        
        # Convert to HSV for better color analysis
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        
        if position == 'top':
            for y in range(height):
                row = region[y, :, :]
                
                # Calculate color statistics
                mean_color = np.mean(row, axis=0)
                std_color = np.std(row, axis=0)
                
                # EXTREMELY strict watermark characteristics
                is_extremely_uniform = np.mean(std_color) < 2  # Almost no variation
                is_almost_white = np.mean(mean_color) > 250   # Almost pure white background
                
                # Only detect if we have EXTREMELY uniform, ALMOST WHITE watermark patterns
                # AND we hit very dark content (manga panels)
                if not (is_extremely_uniform and is_almost_white) and np.mean(mean_color) < 150:
                    return y
        
        elif position == 'bottom':
            for y in range(height - 1, -1, -1):
                row = region[y, :, :]
                
                # Calculate color statistics
                mean_color = np.mean(row, axis=0)
                std_color = np.std(row, axis=0)
                
                # EXTREMELY strict watermark characteristics
                is_extremely_uniform = np.mean(std_color) < 2  # Almost no variation
                is_almost_white = np.mean(mean_color) > 250   # Almost pure white background
                
                # Only detect if we have EXTREMELY uniform, ALMOST WHITE watermark patterns
                # AND we hit very dark content (manga panels)
                if not (is_extremely_uniform and is_almost_white) and np.mean(mean_color) < 150:
                    return height - y
        
        return 0
        
    except Exception as e:
        return 0