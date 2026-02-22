# YouTube Studio URLs
UPLOAD_URL = "https://www.youtube.com/upload"
STUDIO_EDIT_URL = "https://studio.youtube.com/video/{video_id}/edit"

# File input selector
FILE_INPUT = 'input[type="file"]'

# Form field selectors
TITLE_INPUT = "#title-textarea #textbox"
NOT_MADE_FOR_KIDS = 'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]'

# Navigation selectors
NEXT_BUTTON = "#next-button"
PRIVATE_RADIO = 'tp-yt-paper-radio-button[name="PRIVATE"]'
DONE_BUTTON = "#done-button"

# Video URL extraction
VIDEO_URL_ELEMENT = "span.video-url-fadeable a"

# Upload progress tracking
UPLOAD_PROGRESS = "ytcp-video-upload-progress"

# Bot detection indicators
CAPTCHA_INDICATOR = "iframe[src*='recaptcha'], div#captcha-container"

# Default upload timeout (30 minutes)
UPLOAD_TIMEOUT_SECONDS = 30 * 60

# Playlist assignment selectors
PLAYLIST_DROPDOWN = 'tp-yt-paper-button[aria-label*="Playlist"]'
PLAYLIST_OPTION_TEMPLATE = "tp-yt-paper-item:has-text('{name}')"
PLAYLIST_SAVE = "tp-yt-button-shape[aria-label='Save']"
