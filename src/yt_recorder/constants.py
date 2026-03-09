# YouTube Studio URLs
UPLOAD_URL = "https://www.youtube.com/upload"
STUDIO_EDIT_URL = "https://studio.youtube.com/video/{video_id}/edit"

# File input selector
FILE_INPUT = 'input[type="file"]'
UPLOAD_FILE_PICKER = "ytcp-uploads-file-picker"
UPLOAD_DIALOG = "ytcp-uploads-dialog"

# Form field selectors
TITLE_INPUT = "#title-textarea #textbox"
DESCRIPTION_TEXTAREA = "#description-textarea #textbox"
NOT_MADE_FOR_KIDS = 'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]'

# Navigation selectors
NEXT_BUTTON = "#next-button"
PRIVATE_RADIO = 'tp-yt-paper-radio-button[name="PRIVATE"]'
DONE_BUTTON = "#done-button"

# Dialog scrim overlay (exclude nav-backdrop which is always visible)
DIALOG_SCRIM = "tp-yt-iron-overlay-backdrop:not(#nav-backdrop)"
WARM_WELCOME_DIALOG = "ytcp-warm-welcome-dialog"
WARM_WELCOME_PRIMARY_BUTTON = "ytcp-warm-welcome-dialog ytcp-button"
CHANNEL_CREATE_BUTTON = "#create-channel-button"
CHANNEL_IDENTITY_DIALOG = "ytcp-identity-config-dialog"
CHANNEL_APPEAR_HEADING = 'text="How you\'ll appear"'
PHONE_VERIFY_MODAL_TITLE = 'text="Unlock more on YouTube"'
PHONE_VERIFY_MODAL_BODY = 'text="verify your phone number"'
PHONE_VERIFY_BUTTON = 'ytcp-button:has-text("Verify")'

# Video URL extraction
VIDEO_URL_ELEMENT = "span.video-url-fadeable a"

# Upload progress tracking
UPLOAD_PROGRESS = "ytcp-video-upload-progress"
VIDEO_TOO_LONG_ERROR = "text=Video is too long"
DAILY_LIMIT_ERROR = "text=upload limit"

# Bot detection indicators
CAPTCHA_INDICATOR = "iframe[src*='recaptcha'], div#captcha-container"

# Unsupported browser detection
UNSUPPORTED_BROWSER_INDICATOR = 'text="Improve your experience"'

# Default upload timeout (30 minutes)
UPLOAD_TIMEOUT_SECONDS = 30 * 60

# Playlist assignment selectors
PLAYLIST_TRIGGER = (
    'ytcp-video-metadata-playlists ytcp-dropdown-trigger[aria-label="Select playlists"]'
)
PLAYLIST_SEARCH_INPUT = "ytcp-playlist-dialog input#search-input"
PLAYLIST_ITEM_TEMPLATE = '#items tp-yt-paper-checkbox:has-text("{name}")'
PLAYLIST_DONE = "ytcp-button.done-button"
PLAYLIST_PAGE_SAVE = "ytcp-button#save"
