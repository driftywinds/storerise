#!/usr/bin/env python3
"""
App Store Version Monitor Telegram Bot
Monitors iOS app versions and sends updates via Telegram and Apprise
"""

import os
import json
import logging
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
import apprise
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Data storage files
# Use ./data for local development, /app/data for Docker
DATA_DIR = os.getenv('DATA_DIR', './data')
DATA_FILE = os.path.join(DATA_DIR, 'monitored_apps.json')
CONFIG_FILE = os.path.join(DATA_DIR, 'apprise_config.json')

# Ensure data directory exists
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except PermissionError:
    logger.error(f"Permission denied creating directory: {DATA_DIR}")
    logger.error("Please ensure the directory exists or use a different DATA_DIR")
    raise

class AppStoreMonitor:
    """Handles App Store API interactions"""
    
    BASE_URL = "https://itunes.apple.com/lookup"
    
    # Headers to mimic a browser request
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive'
    }
    
    @staticmethod
    async def fetch_app_info(session: aiohttp.ClientSession, app_id: str) -> Optional[Dict]:
        """Fetch app information from iTunes API"""
        try:
            # Try as numeric ID first
            params = {'id': app_id} if app_id.isdigit() else {'bundleId': app_id}
            
            async with session.get(
                AppStoreMonitor.BASE_URL, 
                params=params,
                headers=AppStoreMonitor.HEADERS
            ) as response:
                if response.status == 200:
                    # Force content type to be treated as JSON
                    text = await response.text()
                    data = json.loads(text)
                    if data.get('resultCount', 0) > 0:
                        return data['results'][0]
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for {app_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching app info for {app_id}: {e}")
            return None
    
    @staticmethod
    def extract_app_id_from_url(url: str) -> Optional[str]:
        """Extract app ID from App Store URL"""
        # URL format: https://apps.apple.com/us/app/app-name/id123456789
        if 'id' in url:
            parts = url.split('id')
            if len(parts) > 1:
                app_id = ''.join(filter(str.isdigit, parts[1].split('?')[0]))
                return app_id if app_id else None
        return None

class DataManager:
    """Manages persistent data storage"""
    
    @staticmethod
    def load_data() -> Dict:
        """Load monitored apps data"""
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading data: {e}")
        return {}
    
    @staticmethod
    def save_data(data: Dict) -> None:
        """Save monitored apps data"""
        try:
            with open(DATA_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving data: {e}")
    
    @staticmethod
    def load_apprise_config() -> Dict:
        """Load Apprise configuration"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading Apprise config: {e}")
        return {}
    
    @staticmethod
    def save_apprise_config(config: Dict) -> None:
        """Save Apprise configuration"""
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving Apprise config: {e}")

class NotificationManager:
    """Manages notifications via Telegram and Apprise"""
    
    @staticmethod
    async def test_apprise_endpoint(endpoint: str) -> tuple[bool, str]:
        """Test a single Apprise endpoint
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            apobj = apprise.Apprise()
            
            # Try to add the endpoint
            if not apobj.add(endpoint):
                return False, "Invalid endpoint URL format"
            
            # Send test notification
            result = await asyncio.to_thread(
                apobj.notify,
                body="This is a test notification from App Store Monitor Bot. If you received this, your endpoint is working correctly!",
                title="🧪 Test Notification"
            )
            
            if result:
                return True, "Test notification sent successfully!"
            else:
                return False, "Failed to send test notification"
                
        except Exception as e:
            logger.error(f"Error testing Apprise endpoint: {e}")
            return False, f"Error: {str(e)}"
    
    @staticmethod
    async def test_all_endpoints(user_id: int) -> Dict[str, tuple[bool, str]]:
        """Test all endpoints for a user
        
        Returns:
            dict: {endpoint: (success, message)}
        """
        config = DataManager.load_apprise_config()
        user_config = config.get(str(user_id), {})
        endpoints = user_config.get('endpoints', [])
        
        results = {}
        for endpoint in endpoints:
            results[endpoint] = await NotificationManager.test_apprise_endpoint(endpoint)
            await asyncio.sleep(0.5)  # Small delay between tests
        
        return results
    
    @staticmethod
    async def send_notification(
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        app_name: str,
        old_version: str,
        new_version: str,
        app_url: str
    ) -> None:
        """Send update notification"""
        message = (
            f"🔔 *App Update Detected*\n\n"
            f"📱 *{app_name}*\n"
            f"📊 Version: `{old_version}` → `{new_version}`\n"
            f"🔗 [View on App Store]({app_url})\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        # Send Telegram notification
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Error sending Telegram notification: {e}")
        
        # Send Apprise notifications
        await NotificationManager.send_apprise_notification(
            user_id, app_name, old_version, new_version, app_url
        )
    
    @staticmethod
    async def send_apprise_notification(
        user_id: int,
        app_name: str,
        old_version: str,
        new_version: str,
        app_url: str
    ) -> None:
        """Send notification via Apprise"""
        config = DataManager.load_apprise_config()
        user_config = config.get(str(user_id), {})
        
        if not user_config.get('enabled', False):
            return
        
        endpoints = user_config.get('endpoints', [])
        if not endpoints:
            return
        
        try:
            apobj = apprise.Apprise()
            for endpoint in endpoints:
                apobj.add(endpoint)
            
            title = f"App Update: {app_name}"
            body = f"{app_name} updated from {old_version} to {new_version}\n{app_url}"
            
            await asyncio.to_thread(apobj.notify, body=body, title=title)
        except Exception as e:
            logger.error(f"Error sending Apprise notification: {e}")

# Bot command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command handler"""
    welcome_message = (
        "👋 *Welcome to App Store Version Monitor!*\n\n"
        "I'll help you monitor iOS app versions and notify you of updates.\n\n"
        "*Commands:*\n"
        "/add - Add an app to monitor (ID, bundle ID, or URL)\n"
        "/list - View all monitored apps\n"
        "/remove - Remove an app from monitoring\n"
        "/apprise - Configure Apprise notifications (auto-tested)\n"
        "/status - Check monitoring status\n"
        "/help - Show this help message\n\n"
        "Apps are checked every hour for updates! 🔄"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help command handler"""
    await start(update, context)

async def add_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add app to monitor"""
    if not context.args:
        await update.message.reply_text(
            "Please provide an App Store URL, App ID, or Bundle ID.\n\n"
            "Examples:\n"
            "`/add https://apps.apple.com/us/app/telegram/id686449807`\n"
            "`/add 686449807`\n"
            "`/add ph.telegra.Telegraph`",
            parse_mode='Markdown'
        )
        return
    
    user_id = update.effective_user.id
    app_identifier = context.args[0]
    
    # Extract app ID from URL if needed
    if app_identifier.startswith('http'):
        extracted_id = AppStoreMonitor.extract_app_id_from_url(app_identifier)
        if extracted_id:
            app_identifier = extracted_id
        else:
            await update.message.reply_text("❌ Could not extract App ID from URL.")
            return
    
    # Fetch app info
    await update.message.reply_text("🔍 Fetching app information...")
    
    async with aiohttp.ClientSession() as session:
        app_info = await AppStoreMonitor.fetch_app_info(session, app_identifier)
    
    if not app_info:
        await update.message.reply_text(
            "❌ Could not find app. Please check the ID/URL and try again."
        )
        return
    
    # Store app data
    data = DataManager.load_data()
    user_key = str(user_id)
    
    if user_key not in data:
        data[user_key] = {}
    
    track_id = str(app_info['trackId'])
    data[user_key][track_id] = {
        'name': app_info['trackName'],
        'version': app_info['version'],
        'bundle_id': app_info['bundleId'],
        'track_id': track_id,
        'url': app_info['trackViewUrl'],
        'added_at': datetime.now().isoformat(),
        'last_checked': datetime.now().isoformat()
    }
    
    DataManager.save_data(data)
    
    await update.message.reply_text(
        f"✅ *Added to monitoring:*\n\n"
        f"📱 {app_info['trackName']}\n"
        f"📊 Current Version: `{app_info['version']}`\n"
        f"🆔 Bundle ID: `{app_info['bundleId']}`\n\n"
        f"You'll be notified of any version updates!",
        parse_mode='Markdown'
    )

async def list_apps(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List monitored apps"""
    user_id = str(update.effective_user.id)
    data = DataManager.load_data()
    
    if user_id not in data or not data[user_id]:
        await update.message.reply_text("You're not monitoring any apps yet. Use /add to start!")
        return
    
    apps = data[user_id]
    message = "📱 *Your Monitored Apps:*\n\n"
    
    for track_id, app_data in apps.items():
        message += (
            f"• *{app_data['name']}*\n"
            f"  Version: `{app_data['version']}`\n"
            f"  ID: `{track_id}`\n\n"
        )
    
    message += f"Total: {len(apps)} app(s)"
    await update.message.reply_text(message, parse_mode='Markdown')

async def remove_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove app from monitoring"""
    user_id = str(update.effective_user.id)
    data = DataManager.load_data()
    
    if user_id not in data or not data[user_id]:
        await update.message.reply_text("You're not monitoring any apps.")
        return
    
    # Create keyboard with app list
    keyboard = []
    for track_id, app_data in data[user_id].items():
        keyboard.append([
            InlineKeyboardButton(
                f"🗑️ {app_data['name']}",
                callback_data=f"remove_{track_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Select an app to remove:",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ Cancelled")
        return
    
    if query.data.startswith("remove_"):
        track_id = query.data.replace("remove_", "")
        user_id = str(query.from_user.id)
        data = DataManager.load_data()
        
        if user_id in data and track_id in data[user_id]:
            app_name = data[user_id][track_id]['name']
            del data[user_id][track_id]
            DataManager.save_data(data)
            await query.edit_message_text(f"✅ Removed *{app_name}* from monitoring", parse_mode='Markdown')
        else:
            await query.edit_message_text("❌ App not found")

async def apprise_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Configure Apprise notifications"""
    if not context.args:
        config = DataManager.load_apprise_config()
        user_id = str(update.effective_user.id)
        user_config = config.get(user_id, {})
        
        status = "✅ Enabled" if user_config.get('enabled', False) else "❌ Disabled"
        endpoints = user_config.get('endpoints', [])
        
        message = (
            f"*Apprise Configuration*\n\n"
            f"Status: {status}\n"
            f"Endpoints: {len(endpoints)}\n\n"
            f"*Commands:*\n"
            f"`/apprise enable` - Enable Apprise\n"
            f"`/apprise disable` - Disable Apprise\n"
            f"`/apprise add <url>` - Add endpoint (with validation)\n"
            f"`/apprise list` - List endpoints\n"
            f"`/apprise remove <index>` - Remove endpoint\n"
            f"`/apprise test` - Test all endpoints\n\n"
            f"*Examples:*\n"
            f"`/apprise add discord://webhook_id/webhook_token`\n"
            f"`/apprise add mailto://user:pass@gmail.com`\n"
            f"`/apprise add slack://token_a/token_b/token_c`"
        )
        await update.message.reply_text(message, parse_mode='Markdown')
        return
    
    user_id = str(update.effective_user.id)
    config = DataManager.load_apprise_config()
    
    if user_id not in config:
        config[user_id] = {'enabled': False, 'endpoints': []}
    
    command = context.args[0].lower()
    
    if command == 'enable':
        config[user_id]['enabled'] = True
        DataManager.save_apprise_config(config)
        await update.message.reply_text("✅ Apprise notifications enabled")
    
    elif command == 'disable':
        config[user_id]['enabled'] = False
        DataManager.save_apprise_config(config)
        await update.message.reply_text("❌ Apprise notifications disabled")
    
    elif command == 'add' and len(context.args) > 1:
        endpoint = context.args[1]
        
        # Send testing message
        test_msg = await update.message.reply_text("🧪 Testing endpoint...")
        
        # Test the endpoint before adding
        success, message = await NotificationManager.test_apprise_endpoint(endpoint)
        
        if success:
            # Add endpoint if test successful
            config[user_id]['endpoints'].append(endpoint)
            DataManager.save_apprise_config(config)
            await test_msg.edit_text(
                f"✅ *Endpoint added successfully!*\n\n"
                f"Endpoint: `{endpoint}`\n"
                f"Status: {message}\n\n"
                f"Check your notification service to confirm you received the test message.",
                parse_mode='Markdown'
            )
        else:
            # Don't add if test failed
            await test_msg.edit_text(
                f"❌ *Failed to add endpoint*\n\n"
                f"Endpoint: `{endpoint}`\n"
                f"Error: {message}\n\n"
                f"Please check your endpoint URL and try again.",
                parse_mode='Markdown'
            )
    
    elif command == 'test':
        endpoints = config[user_id].get('endpoints', [])
        if not endpoints:
            await update.message.reply_text("❌ No endpoints configured. Add one with `/apprise add <url>`", parse_mode='Markdown')
            return
        
        test_msg = await update.message.reply_text(f"🧪 Testing {len(endpoints)} endpoint(s)...")
        
        # Test all endpoints
        results = await NotificationManager.test_all_endpoints(update.effective_user.id)
        
        # Build results message
        message = "*Endpoint Test Results:*\n\n"
        success_count = 0
        
        for i, (endpoint, (success, msg)) in enumerate(results.items(), 1):
            status = "✅" if success else "❌"
            # Truncate endpoint for display
            display_endpoint = endpoint[:50] + "..." if len(endpoint) > 50 else endpoint
            message += f"{i}. {status} `{display_endpoint}`\n"
            message += f"   _{msg}_\n\n"
            if success:
                success_count += 1
        
        message += f"*Summary:* {success_count}/{len(endpoints)} endpoints working"
        
        await test_msg.edit_text(message, parse_mode='Markdown')
    
    elif command == 'list':
        endpoints = config[user_id].get('endpoints', [])
        if not endpoints:
            await update.message.reply_text("No endpoints configured")
        else:
            message = "*Configured Endpoints:*\n\n"
            for i, endpoint in enumerate(endpoints, 1):
                # Truncate long endpoints
                display = endpoint[:60] + "..." if len(endpoint) > 60 else endpoint
                message += f"{i}. `{display}`\n"
            message += f"\n💡 Use `/apprise test` to verify all endpoints"
            await update.message.reply_text(message, parse_mode='Markdown')
    
    elif command == 'remove' and len(context.args) > 1:
        try:
            index = int(context.args[1]) - 1
            endpoints = config[user_id].get('endpoints', [])
            if 0 <= index < len(endpoints):
                removed = endpoints.pop(index)
                DataManager.save_apprise_config(config)
                display = removed[:60] + "..." if len(removed) > 60 else removed
                await update.message.reply_text(f"✅ Removed: `{display}`", parse_mode='Markdown')
            else:
                await update.message.reply_text("❌ Invalid index")
        except ValueError:
            await update.message.reply_text("❌ Please provide a valid number")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show monitoring status"""
    user_id = str(update.effective_user.id)
    data = DataManager.load_data()
    config = DataManager.load_apprise_config()
    
    app_count = len(data.get(user_id, {}))
    user_config = config.get(user_id, {})
    apprise_status = "✅ Enabled" if user_config.get('enabled', False) else "❌ Disabled"
    endpoint_count = len(user_config.get('endpoints', []))
    
    message = (
        f"*Monitoring Status*\n\n"
        f"📱 Monitored Apps: {app_count}\n"
        f"🔔 Apprise: {apprise_status}\n"
        f"📡 Endpoints: {endpoint_count}\n"
        f"⏰ Check Interval: Every hour\n"
        f"🕐 Last Check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def check_updates(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Background job to check for app updates"""
    logger.info("Running scheduled update check...")
    data = DataManager.load_data()
    
    async with aiohttp.ClientSession() as session:
        for user_id, apps in data.items():
            for track_id, app_data in list(apps.items()):
                try:
                    # Fetch current app info
                    current_info = await AppStoreMonitor.fetch_app_info(session, track_id)
                    
                    if current_info:
                        current_version = current_info['version']
                        stored_version = app_data['version']
                        
                        # Check if version changed
                        if current_version != stored_version:
                            logger.info(f"Update detected: {app_data['name']} {stored_version} -> {current_version}")
                            
                            # Send notification
                            await NotificationManager.send_notification(
                                context,
                                int(user_id),
                                app_data['name'],
                                stored_version,
                                current_version,
                                app_data['url']
                            )
                            
                            # Update stored version
                            apps[track_id]['version'] = current_version
                            apps[track_id]['last_checked'] = datetime.now().isoformat()
                        else:
                            apps[track_id]['last_checked'] = datetime.now().isoformat()
                    
                    # Small delay to avoid rate limiting
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Error checking app {track_id}: {e}")
        
        # Save updated data
        DataManager.save_data(data)

def main() -> None:
    """Start the bot"""
    # Get bot token from environment
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment variables!")
        logger.error("Please create a .env file with: TELEGRAM_BOT_TOKEN=your_token_here")
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    
    # Create application
    application = Application.builder().token(token).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add", add_app))
    application.add_handler(CommandHandler("list", list_apps))
    application.add_handler(CommandHandler("remove", remove_app))
    application.add_handler(CommandHandler("apprise", apprise_config))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Schedule hourly checks
    job_queue = application.job_queue
    job_queue.run_repeating(check_updates, interval=3600, first=10)
    
    logger.info("Bot started. Checking for updates every hour.")
    
    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
