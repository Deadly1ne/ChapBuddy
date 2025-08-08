import os
import json
import re
import random
import requests
import time
import gc
import logging
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError
from io import BytesIO
from discord_webhook import DiscordWebhook, DiscordEmbed
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
from urllib.parse import urljoin, urlparse, urlunparse
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('manga_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('MangaBot')

# Constants
MAX_PARTS = 20  # Maximum parts per chapter to prevent infinite loops

# Load configuration
def load_config():
    try:
        with open('config.json') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Config loading failed: {e}")
        raise

def load_settings():
    try:
        with open('settings.json') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Settings loading failed: {e}")
        raise

config = load_config()
settings = load_settings()

# Google Drive Setup
SCOPES = ['https://www.googleapis.com/auth/drive']
TOKEN_FILE = 'token.json'

def get_drive_service():
    """Authenticate with Google Drive using service account or local server flow"""
    creds = None
    
    try:
        # Handle CI environment with OAuth token
        if os.getenv('CI'):
            logger.info("Using CI environment OAuth flow")
            if not os.path.exists(TOKEN_FILE):
                raise Exception("token.json must be committed for CI environments")
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
            if creds and creds.expired:
                creds.refresh(Request())
            return build('drive', 'v3', credentials=creds)
        
        # Fall back to interactive authentication (for local development)
        logger.info("Using interactive authentication")
        
        # Load existing token if available
        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        
        # If no valid credentials or expired, refresh or get new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # Use local server flow for authentication
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json',
                    scopes=SCOPES
                )
                creds = flow.run_local_server(
                    port=0,
                    authorization_prompt_message='Please visit this URL to authorize access (will automatically open browser): {url}',
                    open_browser=True,
                    access_type='offline',
                    prompt='consent'
                )
                
                # Save credentials for next run
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
        
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"Drive service initialization failed: {e}")
        return None

def get_series_state(series_id):
    """Get state for a specific series"""
    try:
        if os.path.exists('state.json'):
            with open('state.json') as f:
                state = json.load(f)
                return state.get(series_id, {})
        return {}
    except Exception as e:
        logger.error(f"State loading failed for {series_id}: {e}")
        return {}

def save_series_state(series_id, state_data):
    """Save state for a specific series"""
    try:
        state = {}
        if os.path.exists('state.json'):
            with open('state.json') as f:
                state = json.load(f)
        
        # Update state for this series
        state[series_id] = state_data
        
        # Save updated state
        with open('state.json', 'w') as f:
            json.dump(state, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"State saving failed for {series_id}: {e}")
        return False

# Extract chapter number from title
def extract_chapter_number(title):
    """Extract chapter number from various title formats"""
    try:
        # Try common patterns
        patterns = [
            r'第([零一二三四五六七八九十百千万\d]+)章',  # Chinese format with 章 (chapter)
            r'第([零一二三四五六七八九十百千万\d]+)話',  # Chinese format with 話 (story/episode)
            r'第([零一二三四五六七八九十百千万\d]+)回',  # Chinese format with 回 (episode)
            r'第([零一二三四五六七八九十百千万\d]+)集',  # Chinese format with 集 (volume)
            r'Chapter\s*(\d+)', # English format
            r'Ch\.\s*(\d+)',    # Abbreviated
            r'#(\d+)',          # Number sign
            r'(\d+)'            # Plain number
        ]
        
        for pattern in patterns:
            match = re.search(pattern, title)
            if match:
                chapter_text = match.group(1)
                # Convert Chinese numerals to Arabic numerals if needed
                return convert_chinese_to_arabic(chapter_text)
        
        # Fallback: use first number found
        numbers = re.findall(r'\d+', title)
        return int(numbers[0]) if numbers else 0
    except Exception as e:
        logger.warning(f"Chapter number extraction failed for '{title}': {e}")
        return 0

def convert_chinese_to_arabic(text):
    """Convert Chinese numerals to Arabic numerals"""
    try:
        # If it's already a number, return it
        if text.isdigit():
            return int(text)
        
        # Chinese numeral mapping
        chinese_numerals = {
            '零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
            '百': 100, '千': 1000, '万': 10000
        }
        
        # Handle mixed Chinese-Arabic numerals (e.g., "五百零九")
        result = 0
        temp = 0
        i = 0
        
        while i < len(text):
            char = text[i]
            if char.isdigit():
                temp = temp * 10 + int(char)
            elif char in chinese_numerals:
                value = chinese_numerals[char]
                if value == 0:  # Handle 零 (zero)
                    # 零 is used as a placeholder, continue to next character
                    pass
                elif value >= 100:  # 百, 千, 万
                    if temp == 0:
                        temp = 1
                    result += temp * value
                    temp = 0
                elif value == 10:  # 十
                    if temp == 0:
                        temp = 1
                    result += temp * value
                    temp = 0
                else:  # 1-9
                    temp = temp * 10 + value
            i += 1
        
        result += temp
        return result if result > 0 else int(''.join(filter(str.isdigit, text)) or '0')
        
    except Exception as e:
        logger.warning(f"Chinese numeral conversion failed for '{text}': {e}")
        # Fallback: extract any digits found
        digits = ''.join(filter(str.isdigit, text))
        return int(digits) if digits else 0

# Normalize URL by removing fragments and query parameters only
def normalize_url(url):
    """Normalize URL by removing fragments and query parameters, but keep original domain"""
    parsed = urlparse(url)
    # Keep original domain, only remove fragments and query parameters
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))

# Extract part number from URL
def extract_part_number(url):
    """Extract part number from URL if possible"""
    # Extract from URL patterns like 0_226_2.html (part 2), 0_226_3.html (part 3), etc.
    # The pattern is: chapter_number_part.html
    match = re.search(r'_(\d+)_(\d+)\.html', url)
    if match:
        # Return the part number (second number)
        return int(match.group(2))
    
    # Extract from URL patterns like 0_226.html (part 1 - no part suffix)
    match = re.search(r'_(\d+)\.html', url)
    if match:
        # This is part 1 (no part suffix means first part)
        return 1
    
    # Extract from path segments as fallback
    path = urlparse(url).path
    segments = path.split('/')
    if segments:
        last_segment = segments[-1]
        if '_' in last_segment:
            parts = last_segment.split('_')
            # Check if it's in format: chapter_part.html
            if len(parts) >= 3 and parts[-1].replace('.html', '').isdigit():
                return int(parts[-1].replace('.html', ''))
            # If no part number, assume part 1
            elif len(parts) == 2 and parts[-1].replace('.html', '').isdigit():
                return 1
    
    # Check if URL contains chapter number only (part 1)
    if 'chapter' in url.lower():
        return 1
        
    return 0

def extract_chapter_number_from_url(url):
    """Extract chapter number from URL for validation."""
    # Pattern for chapter-X or chapter/X
    chapter_match = re.search(r'chapter[/-](\d+)', url)
    if chapter_match:
        return int(chapter_match.group(1))
    
    # Pattern for ch-X or ch/X
    chapter_match = re.search(r'ch[/-](\d+)', url)
    if chapter_match:
        return int(chapter_match.group(1))
    
    # Pattern for c-X or c/X
    chapter_match = re.search(r'c[/-](\d+)', url)
    if chapter_match:
        return int(chapter_match.group(1))
    
    # Pattern for 0_XX.html or 0_XX_Y.html format (common in baozimh and similar sites)
    # This handles both formats: /0_19.html and /0_19_2.html where 19 is the chapter number
    chapter_match = re.search(r'/(\d+)_(\d+)(?:_(\d+))?\.html', url)
    if chapter_match:
        return int(chapter_match.group(2))  # Return the middle number (chapter number)
    
    return 0  # Default if no chapter number found

def extract_parts_from_title(title):
    """Extract part information from chapter title using (current/total) pattern"""
    try:
        # Look for patterns like (1/4), (2/3), etc.
        match = re.search(r'\((\d+)/(\d+)\)', title)
        if match:
            current_part = int(match.group(1))
            total_parts = int(match.group(2))
            logger.info(f"Found part info in title: {current_part}/{total_parts}")
            return current_part, total_parts
        
        # If no pattern found, assume single part
        return 1, 1
        
    except Exception as e:
        logger.warning(f"Failed to extract parts from title '{title}': {e}")
        return 1, 1

def detect_total_parts(base_url, headers, chapter_title=None):
    """Dynamically detect the total number of parts for a chapter"""
    try:
        # First, try to extract from chapter title if available
        if chapter_title:
            current_part, total_parts = extract_parts_from_title(chapter_title)
            if total_parts > 1:
                logger.info(f"Using title-based part detection: {total_parts} total parts")
                return total_parts
        
        # Fallback to URL-based detection
        if '_' not in base_url or '.html' not in base_url:
            return 1
        
        base_pattern = base_url.split('.html')[0]
        
        # Check if this is already a multi-part URL (e.g., 0_226_2.html)
        if re.search(r'_(\d+)_(\d+)$', base_pattern):
            # Extract the base without part number (e.g., 0_226 from 0_226_2)
            base_pattern = re.sub(r'_(\d+)$', '', base_pattern)
        
        # Test for parts 1-10 (reasonable limit for detection)
        total_parts = 1
        for part_num in range(2, 11):  # Test parts 2-10
            test_url = f"{base_pattern}_{part_num}.html"
            try:
                response = requests.head(test_url, headers=headers, timeout=5)
                if response.status_code == 200:
                    total_parts = part_num
                else:
                    break  # Stop at first non-existent part
            except:
                break  # Stop on any error
        
        logger.info(f"URL-based detection: {total_parts} total parts")
        return total_parts
        
    except Exception as e:
        logger.warning(f"Could not detect total parts: {e}")
        return 1  # Default to 1 part if detection fails

# 1. Check for new chapters for a series
# Legacy function - kept for compatibility but now redirects to new logic
def check_new_chapter(series):
    """Legacy function - now returns the next chapter to process"""
    new_chapters = get_new_chapters(series)
    if new_chapters:
        # Return the first (lowest numbered) new chapter
        chapter = new_chapters[0]
        chapter_url = chapter['url']
        if chapter_url.startswith('/'):
            chapter_url = 'https://www.baozimh.com' + chapter_url
        
        formatted_log_title = format_chapter_title_arabic(chapter['title'], chapter['number'])
        logger.info(f"New chapter found: {series['name']} {formatted_log_title}")
        return chapter_url, chapter['number'], chapter['title']
    
    return None, None, None

# 2. Extract real chapter URL
def get_real_chapter_url(url, series_url):
    logger.info(f"Resolving: {url}")
    
    # Apply URL transformation
    url = re.sub(r'^https?:\/\/(?:[\ww-]+)\.baozicdn\.com\/(.+)$', 'https://static-tw.baozimh.com/\1', url)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Referer': series_url
    }
    
    try:
        # First request to get redirect
        response = requests.get(url, headers=headers, allow_redirects=False, timeout=15)
        
        if 300 <= response.status_code < 400:
            return response.headers.get('Location', url)
            
        # Parse JavaScript redirect
        soup = BeautifulSoup(response.text, 'html.parser')
        script = soup.find('script', string=re.compile('location.href'))
        if script:
            match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)", script.string)
            if match:
                return match.group(1)
                
        return url
    except Exception as e:
        logger.error(f"Redirect resolution failed: {e}")
        return url

# 3. Download and process images from all parts of a chapter
def process_chapter(chapter_url, series_url, chapter_title=None):
    logger.info(f"Processing: {chapter_url}")
    real_url = get_real_chapter_url(chapter_url, series_url)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Referer': real_url
    }
    
    try:
        all_images = []
        current_url = real_url
        part_count = 0
        processed_images = 0
        visited_urls = set()  # Track visited URLs to prevent loops
        processed_chunks = set()  # Track content chunks to prevent duplicates
        last_part_number = 0  # Track the last part number we processed
        
        # Dynamically detect total parts for this chapter
        expected_total_parts = detect_total_parts(real_url, headers, chapter_title)
        logger.info(f"Expected total parts for chapter: {expected_total_parts}")
        
        while current_url and part_count < MAX_PARTS:
            # Normalize URL
            normalized_url = normalize_url(current_url)
            
            # Extract path for duplicate detection (ignore domain differences)
            current_path = urlparse(current_url).path
            current_part_num = extract_part_number(current_url)
            
            # Check if we've visited this path/part combination before
            path_part_key = f"{current_path}#{current_part_num}"
            
            # For circular navigation, allow revisiting URLs but limit total parts
            # Dynamic part limit - use detected total parts or minimum safety check
            min_parts_before_loop_check = min(2, expected_total_parts)
            if path_part_key in visited_urls and part_count >= min_parts_before_loop_check:
                logger.warning(f"Path/part already processed: {path_part_key}, breaking loop")
                break
                
            visited_urls.add(path_part_key)
            logger.info(f"Processing part {part_count+1}: {current_url}")
            
            try:
                response = requests.get(current_url, headers=headers, timeout=30)
                soup = BeautifulSoup(response.text, 'html.parser')
            except Exception as e:
                logger.error(f"Failed to fetch page: {e}")
                break
            
            # Find images - using more robust selector
            images = []
            img_elements = soup.select('img')
            
            for img in img_elements:
                src = img.get('src') or img.get('data-src')
                if src and re.search(r'\.(jpg|jpeg|png|webp)$', src, re.IGNORECASE):
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif not src.startswith('http'):
                        src = urljoin(current_url, src)
                    images.append(src)
            
            # Remove duplicates
            images = list(dict.fromkeys(images))
            logger.info(f"Part {part_count+1}/{expected_total_parts}: Found {len(images)} images")
            
            # Validate we're getting reasonable number of images per part
            if len(images) == 0 and part_count > 0:
                logger.warning(f"No images found on part {part_count+1}, this might indicate navigation issues")
            elif len(images) > 50:  # Sanity check
                logger.warning(f"Unusually high number of images ({len(images)}) on part {part_count+1}, possible cross-chapter contamination")
            
            # Create content signature to detect duplicates
            content_signature = tuple(images[:10]) if images else ()
            
            # For circular navigation, allow revisiting content but limit total parts
            # Dynamic content checking - stop if we see duplicate content after processing expected parts
            min_parts_before_content_check = min(2, expected_total_parts)
            if content_signature and content_signature in processed_chunks and part_count >= min_parts_before_content_check:
                logger.warning(f"Content already processed, breaking loop to prevent duplicates")
                break
            processed_chunks.add(content_signature)
            
            # Skip duplicate images (last 4 from previous part)
            if part_count > 0:
                images = images[4:]
            
            # Download and process the images for this part
            for idx, img_url in enumerate(images):
                for attempt in range(3):  # Retry up to 3 times
                    try:
                        logger.info(f"Downloading {idx+1}/{len(images)}: {img_url[:60]}...")
                        response = requests.get(img_url + f'?t={time.time()}', 
                                                headers=headers, 
                                                timeout=20)
                        img = Image.open(BytesIO(response.content))
                        
                        # Advanced watermark removal using OpenCV detection
                        from watermark_trimmer import trim_watermark
                        img = trim_watermark(img)
                        all_images.append(img)
                        processed_images += 1
                        
                        # Delay between downloads
                        time.sleep(random.uniform(0.3, 1.0))
                        
                        # Memory management
                        if processed_images % 10 == 0:
                            gc.collect()
                        
                        break  # Break out of retry loop on success
                        
                    except (UnidentifiedImageError, OSError) as e:
                        logger.warning(f"Skipping invalid image: {e}")
                    except Exception as e:
                        logger.error(f"Image download error (attempt {attempt+1}/3): {e}")
                        time.sleep(2 ** attempt)  # Exponential backoff
            
            # Check for next part - prioritize part navigation over chapter navigation
            next_url = None
            next_part_number = 0
            
            # Extract current chapter number for validation
            current_chapter_num = extract_chapter_number_from_url(current_url)
            
            # First, try to find next part link (more specific selectors)
            next_part_selectors = [
                'a[href*="_2.html"]',  # Direct part 2 link
                'a[href*="_3.html"]',  # Direct part 3 link  
                'a[href*="_4.html"]',  # Direct part 4 link
                'div.next_page a',      # Next page within chapter
                'div.page_next a',      # Alternative next page selector
                '.next-part a',         # Next part selector
                '.page-nav .next a'     # Page navigation next
            ]
            
            next_part_div = None
            for selector in next_part_selectors:
                next_part_div = soup.select_one(selector)
                if next_part_div and next_part_div.get('href'):
                    candidate_url = next_part_div.get('href')
                    # Validate this is still the same chapter
                    if candidate_url.startswith('/'):
                        base_domain = '/'.join(current_url.split('/')[:3])
                        candidate_url = base_domain + candidate_url
                    elif not candidate_url.startswith('http'):
                        candidate_url = urljoin(current_url, candidate_url)
                    
                    candidate_chapter_num = extract_chapter_number_from_url(candidate_url)
                    # Only accept if both URLs have valid chapter numbers AND they match
                    if (candidate_chapter_num > 0 and current_chapter_num > 0 and 
                        candidate_chapter_num == current_chapter_num):
                        next_url = candidate_url
                        logger.info(f"Found same-chapter next part: {next_url}")
                        break
                    else:
                        if candidate_chapter_num == 0 or current_chapter_num == 0:
                            logger.info(f"Skipping part link due to failed chapter number extraction: {candidate_url} (candidate: {candidate_chapter_num}, current: {current_chapter_num})")
                        else:
                            logger.info(f"Skipping cross-chapter link: {candidate_url} (chapter {candidate_chapter_num} != {current_chapter_num})")
                        continue  # Try next selector
            
            # If no specific part navigation found, try general next_chapter but validate
            if not next_url:
                next_chapter_div = soup.select_one('div.next_chapter a[href*="comic/chapter"]')
                if not next_chapter_div:
                    next_chapter_div = soup.select_one('div.next_chapter a')
                
                if next_chapter_div and next_chapter_div.get('href'):
                    candidate_url = next_chapter_div.get('href')
                    logger.info(f"Checking next_chapter link: {candidate_url}")
                    
                    # Handle relative URLs
                    if candidate_url.startswith('/'):
                        base_domain = '/'.join(current_url.split('/')[:3])
                        candidate_url = base_domain + candidate_url
                    elif not candidate_url.startswith('http'):
                        candidate_url = urljoin(current_url, candidate_url)
                    
                    # Validate this is still the same chapter
                    candidate_chapter_num = extract_chapter_number_from_url(candidate_url)
                    # IMPORTANT: Only accept if both URLs have valid chapter numbers AND they match
                    # This prevents following next chapter links when chapter detection fails (returns 0)
                    if (candidate_chapter_num > 0 and current_chapter_num > 0 and 
                        candidate_chapter_num == current_chapter_num):
                        next_url = candidate_url
                        logger.info(f"Validated same-chapter next link: {next_url}")
                    else:
                        if candidate_chapter_num == 0 or current_chapter_num == 0:
                            logger.info(f"Rejecting next_chapter link due to failed chapter number extraction: {candidate_url} (candidate: {candidate_chapter_num}, current: {current_chapter_num})")
                        else:
                            logger.info(f"Rejecting cross-chapter link: {candidate_url} (chapter {candidate_chapter_num} != {current_chapter_num})")
            
            # If we couldn't find a next part through navigation, try generating the URL
            if not next_url and part_count < expected_total_parts:
                # Try to generate next part URL based on current URL pattern
                current_part_num = extract_part_number(current_url)
                if current_part_num > 0:
                    next_part_num = current_part_num + 1
                    generated_url = None
                    
                    if '_' in current_url and '.html' in current_url:
                        # Pattern: 0_226.html -> 0_226_2.html -> 0_226_3.html -> 0_226_4.html
                        base_url = current_url.split('.html')[0]
                        
                        # Extract the original chapter number (e.g., 226 from 0_226 or 0_226_2)
                        if f'_{current_part_num}' in base_url:
                            # Remove only the part suffix, keeping the chapter format (0_226)
                            chapter_base = base_url.rsplit(f'_{current_part_num}', 1)[0]
                            generated_url = chapter_base + f'_{next_part_num}.html'
                        elif current_part_num == 1 and '_' in base_url:
                            # First part (no suffix) -> add _2, _3, _4
                            generated_url = base_url + f'_{next_part_num}.html'
                    
                    # Validate generated URL is still same chapter
                    if generated_url:
                        generated_chapter_num = extract_chapter_number_from_url(generated_url)
                        if generated_chapter_num == current_chapter_num:
                            next_url = generated_url
                            logger.info(f"Generated valid same-chapter URL: {next_url}")
                        else:
                            logger.warning(f"Generated URL crosses chapters: {generated_url} (chapter {generated_chapter_num} != {current_chapter_num})")
                            logger.info(f"Stopping part processing to prevent cross-chapter issues")
            
            if next_url:
                # Remove fragments like #bottom
                next_url = next_url.split('#')[0]
                # Normalize next URL
                next_url = normalize_url(next_url)
                next_part_number = extract_part_number(next_url)
                logger.info(f"Final next URL: {next_url}, part number: {next_part_number}")
            
            
            # Create path_part_key for next URL to check duplicates
            next_path_part_key = None
            if next_url:
                next_path = urlparse(next_url).path
                next_path_part_key = f"{next_path}#{next_part_number}"
            
            # Only follow next link if:
            # 1. It exists
            # 2. We haven't processed too many parts (use detected total or safety limit)
            # 3. It's a new path/part combination (stop if we've seen this exact URL before)
            # Dynamic part limit - continue until expected parts are processed or safety limit reached
            
            # Special handling for single-page chapters: stop immediately after processing 1 part
            if expected_total_parts == 1 and part_count >= 1:
                logger.info(f"Single-page chapter completed - stopping after {part_count} part(s)")
                current_url = None
                continue
            
            max_allowed_parts = min(expected_total_parts + 1, MAX_PARTS)  # Allow 1 extra part for safety
            if next_url and part_count < max_allowed_parts:
                # Stop if we've already processed this exact path/part combination
                if next_path_part_key in visited_urls:
                    logger.info(f"Circular navigation detected - already processed {next_path_part_key}")
                    # Try to generate sequential part URLs instead
                    current_part_num = extract_part_number(current_url)
                    if current_part_num > 0 and part_count < max_allowed_parts:  # Try up to detected limit
                        next_part_num = current_part_num + 1
                        # Generate URL for next part
                        if '_' in current_url and '.html' in current_url:
                            # Pattern: 0_226.html -> 0_226_2.html -> 0_226_3.html -> 0_226_4.html
                            base_url = current_url.split('.html')[0]
                            
                            # Extract the original chapter number (e.g., 226 from 0_226 or 0_226_2)
                            if f'_{current_part_num}' in base_url:
                                # Remove only the part suffix, keeping the chapter format (0_226)
                                chapter_base = base_url.rsplit(f'_{current_part_num}', 1)[0]
                                generated_url = chapter_base + f'_{next_part_num}.html'
                            elif current_part_num == 1 and '_' in base_url:
                                # First part (no suffix) -> add _2, _3, _4
                                generated_url = base_url + f'_{next_part_num}.html'
                            else:
                                generated_url = None
                            
                            if generated_url:
                                # Check if this generated URL has been processed
                                generated_path = urlparse(generated_url).path
                                generated_path_part_key = f"{generated_path}#{next_part_num}"
                                if generated_path_part_key not in visited_urls:
                                    logger.info(f"Generated next URL: {generated_url}, part number: {next_part_num}")
                                    current_url = generated_url
                                    part_count += 1
                                    time.sleep(1)
                                else:
                                    logger.info(f"Generated URL already processed: {generated_url}")
                                    current_url = None
                            else:
                                logger.info("Could not generate next URL")
                                current_url = None
                        else:
                            logger.info("URL pattern not suitable for generation")
                            current_url = None
                    else:
                        logger.info("Stopping: reached maximum parts or invalid part number")
                        current_url = None
                else:
                    current_url = next_url
                    part_count += 1
                    last_part_number = max(last_part_number, next_part_number)  # Track highest part seen
                    logger.info(f"Found next part: {current_url} (part {part_count})")
                    # Add delay between parts
                    time.sleep(1)
            else:
                if next_url:
                    if part_count >= max_allowed_parts:
                        logger.info(f"Stopping: reached part limit ({part_count}/{expected_total_parts} expected parts)")
                    else:
                        logger.info(f"No valid next part found")
                else:
                    logger.info(f"No next part link found - chapter complete ({part_count}/{expected_total_parts} parts processed)")
                current_url = None
        
        # Final validation and summary
        logger.info(f"Chapter processing completed:")
        logger.info(f"  - Expected parts: {expected_total_parts}")
        logger.info(f"  - Processed parts: {part_count}")
        logger.info(f"  - Total images collected: {len(all_images)}")
        logger.info(f"  - Images processed: {processed_images}")
        if part_count > 0:
            logger.info(f"  - Average images per part: {len(all_images)/part_count:.1f}")
        
        # Warn if we processed significantly different number of parts than expected
        if abs(part_count - expected_total_parts) > 1:
            logger.warning(f"Part count mismatch: expected {expected_total_parts}, processed {part_count}")
        
        # Warn if we got unusually few images (less than 5 per part on average)
        if part_count > 0:
            avg_images_per_part = len(all_images) / part_count
            if avg_images_per_part < 5:
                logger.warning(f"Low image count: {avg_images_per_part:.1f} images per part, possible collection issues")
        
        return all_images, real_url
        
    except Exception as e:
        logger.error(f"Chapter processing failed: {e}")
        return [], real_url

# 4. Stitch images vertically with memory optimization
def stitch_images(images, max_height=12000):
    if not images:
        return []
    
    logger.info(f"Stitching {len(images)} images using SmartStitch")
    
    try:
        from core.detectors import select_detector
        from core.services import ImageManipulator
        
        # Initialize SmartStitch components
        img_manipulator = ImageManipulator()
        detector = select_detector(detection_type='pixel')
        
        # Resize images to consistent width (SmartStitch requirement)
        widths = [img.width for img in images]
        target_width = 800  # Fixed width of 800px
        
        resized_images = []
        for img in images:
            if img.width != target_width:
                ratio = target_width / img.width
                new_height = int(img.height * ratio)
                resized_img = img.resize((target_width, new_height), Image.LANCZOS)
                resized_images.append(resized_img)
            else:
                resized_images.append(img)
        
        # Combine all images into one long strip
        logger.info("Combining images into single strip")
        combined_img = img_manipulator.combine(resized_images)
        
        # Use SmartStitch's intelligent detection to find optimal slice points
        logger.info("Detecting optimal slice points")
        slice_points = detector.run(
            combined_img,
            split_height=max_height,
            sensitivity=90,  # 90% sensitivity (10% tolerance)
            ignorable_pixels=5,  # Ignore 5px border
            scan_step=5  # 5px scan step
        )
        
        # Slice the combined image at detected points
        logger.info(f"Slicing image at {len(slice_points)} points")
        sections = img_manipulator.slice(combined_img, slice_points)
        
        # Clean up
        combined_img.close()
        for img in resized_images:
            img.close()
        gc.collect()
        
        logger.info(f"Created {len(sections)} intelligently stitched images")
        return sections
    
    except Exception as e:
        logger.error(f"SmartStitch stitching failed: {e}")
        # Fallback to simple stitching if SmartStitch fails
        logger.info("Falling back to simple stitching")
        return stitch_images_fallback(images, max_height)

def stitch_images_fallback(images, max_height=15000):
    """Fallback stitching method in case SmartStitch fails"""
    if not images:
        return []
    
    try:
        # Set fixed width to 800px
        max_width = 800
        
        sections = []
        current_section = []
        current_height = 0
        
        for img in images:
            # Resize if needed to match max width
            if img.width != max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.LANCZOS)
            
            if current_height + img.height > max_height:
                # Create new section
                if current_section:
                    section_img = Image.new('RGB', (max_width, current_height))
                    y_offset = 0
                    for section_img_part in current_section:
                        section_img.paste(section_img_part, (0, y_offset))
                        y_offset += section_img_part.height
                    sections.append(section_img)
                
                # Reset
                current_section = [img]
                current_height = img.height
            else:
                current_section.append(img)
                current_height += img.height
        
        # Final section
        if current_section:
            section_img = Image.new('RGB', (max_width, current_height))
            y_offset = 0
            for img_part in current_section:
                section_img.paste(img_part, (0, y_offset))
                y_offset += img_part.height
            sections.append(section_img)
        
        return sections
    
    except Exception as e:
        logger.error(f"Fallback stitching failed: {e}")
        return []

# 5. Upload to Google Drive
def upload_to_drive(service, images, series, chapter_number, max_retries=3):
    if not service:
        logger.error("No Google Drive service available")
        return None, False
        
    if not images:
        return None, False
    
    logger.info("Uploading to Google Drive...")
    
    # Retry logic for network issues
    for attempt in range(max_retries):
        try:
            return _upload_to_drive_internal(service, images, series, chapter_number)
        except Exception as e:
            if "10053" in str(e) or "connection" in str(e).lower() or "network" in str(e).lower():
                if attempt < max_retries - 1:
                    logger.warning(f"Upload attempt {attempt + 1} failed due to network issue: {e}. Retrying in 10 seconds...")
                    time.sleep(10)
                    continue
                else:
                    logger.error(f"Upload failed after {max_retries} attempts: {e}")
                    return None, False
            else:
                # Non-network error, don't retry
                logger.error(f"Upload failed with non-network error: {e}")
                return None, False
    
    return None, False

def _upload_to_drive_internal(service, images, series, chapter_number):
    global settings, config
    # Get or create root comics folder
    root_folder_id = settings.get('root_drive_folder_id')
    if not root_folder_id:
        folder_metadata = {
            'name': "Comics Collection",
            'mimeType': 'application/vnd.google-apps.folder'
        }
        
        folder = service.files().create(
            body=folder_metadata,
            fields='id'
        ).execute()
        root_folder_id = folder['id']
        settings['root_drive_folder_id'] = root_folder_id
        
        # Update settings file
        with open('settings.json', 'w') as f:
            json.dump(settings, f, indent=2)
        
        # Reload settings to ensure in-memory variable reflects the changes
        settings = load_settings()
        
        logger.info(f"Created root comics folder ID: {root_folder_id}")
    
    # Get or create series folder
    series_folder_id = series.get('drive_folder_id')
    if not series_folder_id:
        folder_metadata = {
            'name': series['name'],
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [root_folder_id]
        }
        
        folder = service.files().create(
            body=folder_metadata,
            fields='id'
        ).execute()
        series_folder_id = folder['id']
        
        # Update series config
        for s in config['series']:
            if s['id'] == series['id']:
                s['drive_folder_id'] = series_folder_id
                break
        
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=2)
        
        # Reload config to ensure in-memory variable reflects the changes
        config = load_config()
        
        logger.info(f"Created series folder for {series['name']}: {series_folder_id}")
    
    # Check if chapter folder already exists
    chapter_folder_name = f"Chapter {chapter_number}"
    chapter_folder_id = None
    
    # Search for existing chapter folder
    query = f"name='{chapter_folder_name}' and '{series_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    existing_folders = service.files().list(q=query, fields='files(id, name)').execute()
    
    if existing_folders.get('files'):
        # Use existing folder
        chapter_folder_id = existing_folders['files'][0]['id']
        logger.info(f"Using existing chapter folder: {chapter_folder_name}")
    else:
        # Create new chapter folder
        chapter_folder_metadata = {
            'name': chapter_folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [series_folder_id]
        }
        
        chapter_folder = service.files().create(
            body=chapter_folder_metadata,
            fields='id,webViewLink'
        ).execute()
        chapter_folder_id = chapter_folder['id']
        
        # Set permissions
        service.permissions().create(
            fileId=chapter_folder_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        
        logger.info(f"Created new chapter folder: {chapter_folder_name}")
    
    # Upload images
    folder_url = f"https://drive.google.com/drive/folders/{chapter_folder_id}"
    upload_count = 0
    
    for idx, img in enumerate(images):
        try:
            # Memory-efficient processing
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=100, optimize=True)
            buffer.seek(0)
            del img
            gc.collect()
            
            # Upload
            file_name = f"{idx+1}.jpg"
            file_metadata = {
                'name': file_name,
                'parents': [chapter_folder_id]
            }
            media = MediaIoBaseUpload(buffer, mimetype='image/jpeg')
            
            service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            upload_count += 1
            logger.info(f"Uploaded {file_name}")
            
            # Clean up
            buffer.close()
            time.sleep(1)  # Reduced delay
            
        except Exception as e:
            logger.error(f"Upload failed for part {idx+1}: {e}")
            # Don't raise here, continue with other images
    
    logger.info(f"Uploaded {upload_count}/{len(images)} images")
    return folder_url, upload_count > 0

# Helper function to format chapter title with Arabic numerals only
def format_chapter_title_arabic(chapter_title, chapter_number):
    """Format chapter title to show only Arabic numerals without Chinese text"""
    # Return only the chapter number without any subtitle or Chinese text
    return f"Chapter {chapter_number}"

# 6. Discord notification
def send_notification(folder_url, chapter_url, series, chapter_number, chapter_title, processing_success, upload_success):
    webhook_url = series.get('discord_webhook') or settings.get('discord_webhook')
    if not webhook_url:
        logger.warning("No Discord webhook configured")
        return

    webhook = DiscordWebhook(url=webhook_url, rate_limit_retry=True)

    # Build embed only on full success
    if processing_success and upload_success:
        embed = DiscordEmbed(title="🎉 New Chapter Alert! 🎉", color="03b2f8")
        embed.add_embed_field(name="Manga:", value=f"**{series.get('name', 'Unknown')}**", inline=False)
        embed.add_embed_field(name="New Chapter:", value=f"**Chapter {chapter_number}**", inline=False)
        embed.add_embed_field(name="**Read it here**", value=f"[Click to Read]({chapter_url})", inline=False)
        if folder_url:
            embed.add_embed_field(name="**Google Drive**", value=f"[View on Drive]({folder_url})", inline=False)

    else:
        # Fallback plain-text embed for failures
        status = "⚠️ PROCESSING FAILED" if not processing_success else "⚠️ UPLOAD FAILED"
        embed = DiscordEmbed(title=status, color="ff0000")
        embed.add_embed_field(name=series.get('name', 'Unknown'), value=f"Chapter {chapter_number}", inline=False)

    # Footer with timestamp
    now = datetime.now().strftime("%I:%M %p")
    embed.set_footer(text=f"Baozimh Chapter Notifier • Today at {now}")

    webhook.add_embed(embed)
    response = webhook.execute()
    if response.status_code == 200:
        logger.info("Discord notification sent")
    else:
        logger.error(f"Discord error: {response.status_code}")

# Get all new chapters for a series
def get_new_chapters(series):
    """Get all new chapters that need to be processed"""
    logger.info(f"Checking: {series['manga_url']}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9'
    }
    
    try:
        response = requests.get(series['manga_url'], headers=headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find chapters
        chapters = soup.select('.comics-chapters__item')
        if not chapters:
            logger.info(f"No chapters found for {series['name']}")
            return []
        
        # Get current state
        series_state = get_series_state(series['id'])
        last_processed = series_state.get('last_processed_chapter', 0)
        
        # Collect all chapters with their numbers
        all_chapters = []
        for chapter in chapters:
            chapter_url = chapter['href']
            chapter_title = chapter.find('span').get_text().strip()
            chapter_number = extract_chapter_number(chapter_title)
            
            if chapter_number > last_processed:
                all_chapters.append({
                    'url': chapter_url,
                    'title': chapter_title,
                    'number': chapter_number
                })
        
        # Sort chapters by number to process in order
        all_chapters.sort(key=lambda x: x['number'])
        
        if all_chapters:
            logger.info(f"Found {len(all_chapters)} new chapters for {series['name']} (last processed: {last_processed})")
            for ch in all_chapters:
                logger.info(f"  - Chapter {ch['number']}: {ch['title']}")
        else:
            logger.info(f"No new chapters found for {series['name']} (last processed: {last_processed})")
        
        return all_chapters
        
    except Exception as e:
        logger.error(f"Error checking chapters for {series['name']}: {e}")
        return []

# Process a single chapter
def process_single_chapter(chapter_info, series, drive_service):
    """Process a single chapter"""
    chapter_url = chapter_info['url']
    chapter_number = chapter_info['number']
    chapter_title = chapter_info['title']
    
    # Handle relative URLs
    if chapter_url.startswith('/'):
        chapter_url = 'https://www.baozimh.com' + chapter_url
    
    logger.info(f"Processing Chapter {chapter_number}: {chapter_title}")
    
    # Process chapter
    images, source_url = process_chapter(chapter_url, series['manga_url'], chapter_title)
    processing_success = bool(images)
    
    # Stitch images
    stitched = []
    if processing_success:
        stitched = stitch_images(images)
        # Clear original images to save memory
        del images
        gc.collect()
    
    # Upload to Drive
    folder_url = None
    upload_success = False
    
    if stitched:
        folder_url, upload_success = upload_to_drive(
            drive_service, 
            stitched, 
            series,
            chapter_number
        )
        # Clear stitched images
        del stitched
        gc.collect()
    
    # Send notification
    send_notification(
        folder_url, 
        source_url, 
        series, 
        chapter_number, 
        chapter_title,
        processing_success, 
        upload_success
    )
    
    # Update state if processing was successful, regardless of upload status
    # This prevents retrying chapters that were successfully processed but failed to upload
    if processing_success:
        state_data = {
            'last_processed_chapter': chapter_number,
            'last_processed': time.strftime("%Y-%m-%d %H:%M:%S"),
            'chapter_title': chapter_title,
            'upload_success': upload_success  # Track upload status for reference
        }
        if save_series_state(series['id'], state_data):
            logger.info(f"State updated for {series['name']} - Chapter {chapter_number}")
        
        if not upload_success:
            logger.warning(f"Chapter {chapter_number} processed successfully but upload failed - marked as processed to avoid retry")
        
        return True
    else:
        logger.error(f"Failed to process Chapter {chapter_number} for {series['name']}")
        return False

# Process a single series
def process_series(series, drive_service):
    logger.info(f"\n{'='*40}")
    logger.info(f"Processing Series: {series['name']}")
    logger.info(f"{'='*40}")
    
    # Get all new chapters
    new_chapters = get_new_chapters(series)
    if not new_chapters:
        return
    
    # Safety limit: don't process more than 5 chapters per run to prevent overwhelming the system
    MAX_CHAPTERS_PER_RUN = 1
    if len(new_chapters) > MAX_CHAPTERS_PER_RUN:
        logger.warning(f"Found {len(new_chapters)} new chapters for {series['name']}, but limiting to {MAX_CHAPTERS_PER_RUN} per run for safety")
        new_chapters = new_chapters[:MAX_CHAPTERS_PER_RUN]
    
    # Process each chapter in order
    processed_count = 0
    failed_count = 0
    for chapter_info in new_chapters:
        try:
            success = process_single_chapter(chapter_info, series, drive_service)
            if success:
                processed_count += 1
            else:
                failed_count += 1
                # Only stop if we have multiple consecutive failures (indicates a serious issue)
                if failed_count >= 2:
                    logger.warning(f"Stopping processing for {series['name']} due to {failed_count} consecutive failures")
                    break
                else:
                    logger.warning(f"Chapter {chapter_info['number']} failed, but continuing with next chapter")
            
            # Add delay between chapters
            if len(new_chapters) > 1:
                time.sleep(3)
                
        except Exception as e:
            logger.error(f"Error processing Chapter {chapter_info['number']} for {series['name']}: {e}")
            failed_count += 1
            # Only stop if we have multiple consecutive failures
            if failed_count >= 2:
                logger.warning(f"Stopping processing for {series['name']} due to {failed_count} consecutive failures")
                break
            else:
                logger.warning(f"Exception occurred but continuing with next chapter")
    
    # Show remaining chapters if any
    remaining_chapters = len(get_new_chapters(series))
    if remaining_chapters > 0:
        logger.info(f"Finished processing: {series['name']} - {processed_count}/{len(new_chapters)} chapters processed, {remaining_chapters} chapters remaining for next run\n")
    else:
        logger.info(f"Finished processing: {series['name']} - {processed_count}/{len(new_chapters)} chapters processed, all caught up!\n")

# Main function
def main():
    logger.info(f"\n{'='*40}")
    logger.info("MangaBot Started")
    logger.info(f"{'='*40}")
    
    # Initialize Google Drive
    drive_service = get_drive_service()
    if drive_service:
        logger.info("Google Drive authenticated")
    
    # Process each series
    for series in config['series']:
        try:
            process_series(series, drive_service)
        except Exception as e:
            logger.error(f"Error processing {series['name']}: {e}")
        finally:
            # Clear memory between series
            gc.collect()
            time.sleep(2)
    
    logger.info(f"\n{'='*40}")
    logger.info("Processing Complete")
    logger.info(f"{'='*40}")

if __name__ == "__main__":
    main()
