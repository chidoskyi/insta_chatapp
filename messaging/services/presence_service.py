"""
Redis-based presence service for real-time online/offline status tracking
"""
import redis
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import json


class PresenceService:
    """Manage user online/offline status using Redis"""
    
    def __init__(self):
        # Parse Redis URL from settings
        redis_url = settings.CHANNEL_LAYERS['default']['CONFIG']['hosts'][0]
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        
        # Key prefixes
        self.ONLINE_KEY_PREFIX = "user:online:"
        self.LAST_SEEN_KEY_PREFIX = "user:last_seen:"
        self.TYPING_KEY_PREFIX = "typing:"
        self.ONLINE_USERS_SET = "online_users"
        
        # TTL settings
        self.ONLINE_TTL = 60  # 60 seconds - user considered offline if not refreshed
        self.TYPING_TTL = 5   # 5 seconds - typing indicator expires
    
    # ============ ONLINE/OFFLINE STATUS ============
    
    def set_user_online(self, user_id):
        """Mark user as online"""
        user_key = f"{self.ONLINE_KEY_PREFIX}{user_id}"
        
        # Set online flag with TTL
        self.redis_client.setex(user_key, self.ONLINE_TTL, "1")
        
        # Add to online users set
        self.redis_client.sadd(self.ONLINE_USERS_SET, str(user_id))
        
        # Update last seen
        self.update_last_seen(user_id)
        
        print(f"✅ User {user_id} is now ONLINE")
    
    def set_user_offline(self, user_id):
        """Mark user as offline"""
        user_key = f"{self.ONLINE_KEY_PREFIX}{user_id}"
        
        # Remove online flag
        self.redis_client.delete(user_key)
        
        # Remove from online users set
        self.redis_client.srem(self.ONLINE_USERS_SET, str(user_id))
        
        # Update last seen
        self.update_last_seen(user_id)
        
        print(f"❌ User {user_id} is now OFFLINE")
    
    def is_user_online(self, user_id):
        """Check if user is currently online"""
        user_key = f"{self.ONLINE_KEY_PREFIX}{user_id}"
        return self.redis_client.exists(user_key) > 0
    
    def refresh_user_presence(self, user_id):
        """Refresh user's online status (call this on activity)"""
        user_key = f"{self.ONLINE_KEY_PREFIX}{user_id}"
        
        # Refresh TTL
        if self.redis_client.exists(user_key):
            self.redis_client.expire(user_key, self.ONLINE_TTL)
            self.update_last_seen(user_id)
            return True
        else:
            # If doesn't exist, set as online
            self.set_user_online(user_id)
            return True
    
    def get_online_users(self):
        """Get list of all online user IDs"""
        return list(self.redis_client.smembers(self.ONLINE_USERS_SET))
    
    def get_online_users_in_conversation(self, conversation_id, member_ids):
        """Get which members of a conversation are online"""
        online_members = []
        for user_id in member_ids:
            if self.is_user_online(user_id):
                online_members.append(str(user_id))
        return online_members
    
    # ============ LAST SEEN ============
    
    def update_last_seen(self, user_id):
        """Update user's last seen timestamp"""
        last_seen_key = f"{self.LAST_SEEN_KEY_PREFIX}{user_id}"
        timestamp = timezone.now().isoformat()
        self.redis_client.set(last_seen_key, timestamp)
    
    def get_last_seen(self, user_id):
        """Get user's last seen timestamp"""
        last_seen_key = f"{self.LAST_SEEN_KEY_PREFIX}{user_id}"
        timestamp_str = self.redis_client.get(last_seen_key)
        
        if timestamp_str:
            from dateutil import parser
            return parser.isoparse(timestamp_str)
        return None
    
    def get_last_seen_text(self, user_id):
        """Get human-readable last seen text"""
        if self.is_user_online(user_id):
            return "online"
        
        last_seen = self.get_last_seen(user_id)
        if not last_seen:
            return "offline"
        
        now = timezone.now()
        diff = now - last_seen
        
        if diff < timedelta(minutes=1):
            return "just now"
        elif diff < timedelta(hours=1):
            minutes = int(diff.total_seconds() / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif diff < timedelta(days=1):
            hours = int(diff.total_seconds() / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif diff < timedelta(days=7):
            days = diff.days
            return f"{days} day{'s' if days != 1 else ''} ago"
        else:
            return last_seen.strftime("%b %d, %Y")
    
    # ============ TYPING INDICATORS ============
    
    def set_user_typing(self, conversation_id, user_id, is_typing=True):
        """Set user typing status in a conversation"""
        typing_key = f"{self.TYPING_KEY_PREFIX}{conversation_id}"
        
        if is_typing:
            # Add user to typing set with TTL
            self.redis_client.hset(typing_key, str(user_id), timezone.now().isoformat())
            self.redis_client.expire(typing_key, self.TYPING_TTL)
        else:
            # Remove user from typing set
            self.redis_client.hdel(typing_key, str(user_id))
    
    def get_typing_users(self, conversation_id):
        """Get list of users currently typing in a conversation"""
        typing_key = f"{self.TYPING_KEY_PREFIX}{conversation_id}"
        typing_data = self.redis_client.hgetall(typing_key)
        
        # Filter out expired typing indicators
        now = timezone.now()
        active_typers = []
        
        for user_id, timestamp_str in typing_data.items():
            from dateutil import parser
            timestamp = parser.isoparse(timestamp_str)
            if (now - timestamp).total_seconds() < self.TYPING_TTL:
                active_typers.append(user_id)
        
        return active_typers
    
    def is_user_typing(self, conversation_id, user_id):
        """Check if specific user is typing"""
        typing_key = f"{self.TYPING_KEY_PREFIX}{conversation_id}"
        return self.redis_client.hexists(typing_key, str(user_id))
    
    # ============ BULK OPERATIONS ============
    
    def get_users_status(self, user_ids):
        """Get status for multiple users at once"""
        statuses = {}
        for user_id in user_ids:
            statuses[str(user_id)] = {
                'is_online': self.is_user_online(user_id),
                'last_seen': self.get_last_seen_text(user_id),
                'last_seen_timestamp': self.get_last_seen(user_id)
            }
        return statuses
    
    # ============ CLEANUP ============
    
    def cleanup_stale_users(self):
        """Remove stale online users (called by periodic task)"""
        online_users = self.get_online_users()
        removed = 0
        
        for user_id in online_users:
            if not self.is_user_online(user_id):
                self.redis_client.srem(self.ONLINE_USERS_SET, user_id)
                removed += 1
        
        print(f"🧹 Cleaned up {removed} stale online users")
        return removed


# Singleton instance
presence_service = PresenceService()