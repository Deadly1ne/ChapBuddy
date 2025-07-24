# Manga Bot

An automated manga chapter downloader and processor that monitors manga websites for new chapters, downloads images, stitches them intelligently, and uploads to Google Drive with Discord notifications.

## Features

- **Sequential Chapter Processing**: Processes all new chapters from last processed to latest available
- **Smart Image Stitching**: Uses advanced algorithms to create optimally sized chapter images
- **Google Drive Integration**: Automatically uploads processed chapters to organized folders
- **Discord Notifications**: Sends notifications with download links when new chapters are processed
- **Error Handling**: Robust retry mechanisms for network issues and upload failures
- **Safety Limits**: Processes up to 5 chapters per run to prevent system overload
- **State Management**: Tracks processing progress to avoid reprocessing chapters

## Setup Instructions

### 1. Local Setup

1. Clone this repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/manga-bot.git
   cd manga-bot
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create configuration files:
   - `settings.json`: Discord webhook and Google Drive settings (use settings.example.json as template)
   - `credentials.json`: Google OAuth credentials
   - `service-account.json`: Google Service Account credentials
   - `state.json`: Processing state (auto-generated)
   - `config.json`: Will be automatically created/updated when you add manga series

### 2. Google Drive Setup

1. Create a Google Cloud Project
2. Enable Google Drive API
3. Create OAuth 2.0 credentials and download as `credentials.json`
4. Create a Service Account and download key as `service-account.json`
5. Share your target Google Drive folder with the service account email

### 3. Discord Setup

1. Create a Discord webhook in your target channel
2. Add the webhook URL to your `settings.json`

### 4. Configuration Files

#### settings.json (create from settings.example.json)
```json
{
  "discord_webhook": "YOUR_DISCORD_WEBHOOK_URL",
  "root_drive_folder_id": "YOUR_ROOT_GOOGLE_DRIVE_FOLDER_ID"
}
```

#### config.json (automatically managed)
```json
{
  "series": [
    {
      "id": "series1",
      "name": "Series Name",
      "manga_url": "https://www.baozimh.com/comic/series-url",
      "drive_folder_id": "GOOGLE_DRIVE_FOLDER_ID"
    }
  ]
}
```

**Note**: You can now directly edit and commit `config.json` to add new manga series since sensitive data is separated into `settings.json`.

#### state.json (auto-generated)
```json
{
  "series1": {
    "last_processed_chapter": 0,
    "last_processed": "2024-01-01 00:00:00",
    "chapter_title": "",
    "upload_success": true
  }
}
```

### 5. GitHub Actions Automation

To run the bot automatically every 20 minutes:

1. Push this repository to GitHub
2. Go to your repository Settings → Secrets and variables → Actions
3. Add the following secrets:
   - `CONFIG_JSON`: Content of your config.json file
   - `SETTINGS_JSON`: Content of your settings.json file
   - `CREDENTIALS_JSON`: Content of your credentials.json file
   - `SERVICE_ACCOUNT_JSON`: Content of your service-account.json file
   - `STATE_JSON`: Content of your state.json file (initially `{}`)

4. The workflow will automatically run every 20 minutes
5. You can also trigger it manually from the Actions tab

### 6. Manual Run

```bash
python bot.py
```

## How It Works

1. **Chapter Detection**: Scans manga listing pages for new chapters
2. **Sequential Processing**: Processes chapters in order from last processed to latest
3. **Image Download**: Downloads all images from chapter parts
4. **Smart Stitching**: Combines images into optimally sized files
5. **Google Drive Upload**: Creates organized folder structure and uploads
6. **State Update**: Tracks progress to resume from correct position
7. **Notifications**: Sends Discord notifications with download links

## Safety Features

- **Chapter Limit**: Maximum 5 chapters per run to prevent overload
- **Retry Logic**: Automatic retries for network and upload failures
- **Error Recovery**: Continues processing other chapters if one fails
- **State Persistence**: Remembers progress even after failures

## Logs

The bot creates detailed logs in `manga_bot.log` with:
- Chapter detection and processing status
- Download progress and statistics
- Upload results and folder links
- Error details and retry attempts

## Troubleshooting

- **Upload Failures**: Check Google Drive permissions and service account access
- **Chapter Detection Issues**: Verify manga URLs are accessible
- **Discord Notifications**: Confirm webhook URL is valid
- **State Issues**: Delete state.json to reset processing from beginning

## Contributing

Feel free to submit issues and enhancement requests!

## License

This project is for educational purposes. Please respect manga publishers' rights and terms of service.