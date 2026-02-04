
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import FileExtensionValidator
import uuid


class Conversation(models.Model):
    CONVERSATION_TYPES = (
        ('direct', 'Direct Message'),
        ('group', 'Group Chat'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=10, choices=CONVERSATION_TYPES, default='direct')
    name = models.CharField(max_length=100, blank=True)
    description = models.TextField(max_length=500, blank=True)  # NEW: Group description
    icon = models.ImageField(upload_to='group_icons/', blank=True, null=True)  # NEW: Group icon
    
    # NEW: Group settings
    only_admins_can_send = models.BooleanField(default=False)  # NEW: Admin-only messages
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_conversations'
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'conversations'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['-updated_at']),
            models.Index(fields=['type', '-updated_at']),
        ]
    
    def __str__(self):
        if self.type == 'group':
            return f"Group: {self.name or f'Conversation {self.id}'}"
        return f"DM {self.id}"
    
    def get_other_user(self, user):
        """For DM, get the other participant"""
        if self.type == 'direct':
            member = self.members.exclude(user=user).first()
            return member.user if member else None
        return None
    
    def get_last_message(self):
        """Get the most recent non-deleted message"""
        return self.messages.filter(is_deleted=False).order_by('-created_at').first()


class ConversationMember(models.Model):
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='members'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversation_memberships'
    )
    
    # Member status
    is_admin = models.BooleanField(default=False)
    is_muted = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)  # NEW: Pin conversation
    is_archived = models.BooleanField(default=False)  # NEW: Archive conversation
    
    # Read tracking
    last_read_at = models.DateTimeField(null=True, blank=True)
    
    # Privacy settings (NEW)
    show_last_seen = models.BooleanField(default=True)  # NEW: Last seen privacy
    show_online_status = models.BooleanField(default=True)  # NEW: Online status privacy
    
    joined_at = models.DateTimeField(default=timezone.now)
    left_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'conversation_members'
        unique_together = ('conversation', 'user')
        ordering = ['joined_at']
        indexes = [
            models.Index(fields=['user', '-joined_at']),
            models.Index(fields=['conversation', 'user']),
            models.Index(fields=['user', 'is_pinned', '-joined_at']),  # NEW: For pinned conversations
        ]
    
    def __str__(self):
        return f"{self.user.username} in conversation {self.conversation.id}"
    
    @property
    def is_active(self):
        return self.left_at is None
    
    def mark_as_read(self):
        """Mark conversation as read"""
        self.last_read_at = timezone.now()
        self.save(update_fields=['last_read_at'])
    
    def get_unread_count(self):
        """Get count of unread messages"""
        if not self.last_read_at:
            return self.conversation.messages.filter(
                is_deleted=False
            ).exclude(sender=self.user).count()
        
        return self.conversation.messages.filter(
            created_at__gt=self.last_read_at,
            is_deleted=False
        ).exclude(sender=self.user).count()


class Message(models.Model):
    MESSAGE_TYPES = (
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('audio', 'Audio'),  # NEW: Voice messages
        ('document', 'Document'),  # NEW: Documents
        ('contact', 'Contact'),  # NEW: Contact card
        ('location', 'Location'),  # NEW: Location
    )
    
    MESSAGE_STATUS = (
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
    )
    
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages'
    )
    
    # Content
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPES, default='text')  # NEW
    body = models.TextField(max_length=5000, blank=True)  # Increased limit
    
    status = models.CharField(max_length=20, choices=MESSAGE_STATUS, default='sent')
    # Media fields
    media = models.FileField(upload_to='messages/media/', blank=True, null=True)
    media_thumbnail = models.ImageField(upload_to='messages/thumbnails/', blank=True, null=True)  # NEW: Thumbnails
    media_duration = models.IntegerField(null=True, blank=True)  # NEW: For audio/video duration in seconds
    media_size = models.BigIntegerField(null=True, blank=True)  # NEW: File size in bytes
    
    # Location data (NEW)
    location_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_name = models.CharField(max_length=255, blank=True)
    
    # Reply to another message
    reply_to = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replies'
    )
    
    # Forwarding (NEW)
    forwarded_from = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='forwards'
    )
    forward_count = models.IntegerField(default=0)  # NEW: Track how many times forwarded
    
    # Message status
    is_edited = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    deleted_for_everyone = models.BooleanField(default=False)  # NEW: Delete for everyone
    is_starred = models.BooleanField(default=False)  # NEW: Starred messages
    
    # Delivery tracking (NEW)
    delivered_to = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='delivered_messages',
        blank=True
    )
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)  # NEW: When deleted
    
    class Meta:
        db_table = 'messages'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['sender', '-created_at']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['conversation', 'is_starred']),  # NEW: For starred messages
        ]
    
    def __str__(self):
        return f"Message {self.id} from {self.sender.username}"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update conversation's updated_at
        self.conversation.updated_at = timezone.now()
        self.conversation.save(update_fields=['updated_at'])


class MessageRead(models.Model):
    """Track who has read which messages"""
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name='read_by'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='read_messages'
    )
    read_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'message_reads'
        unique_together = ('message', 'user')
        ordering = ['read_at']
        indexes = [
            models.Index(fields=['message', 'read_at']),
            models.Index(fields=['user', 'read_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} read message {self.message.id}"


class MessageReaction(models.Model):
    """NEW: Emoji reactions to messages (WhatsApp style)"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name='reactions'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='message_reactions'
    )
    emoji = models.CharField(max_length=10)  # Stores emoji character
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'message_reactions'
        unique_together = ('message', 'user')  # One reaction per user per message
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['message', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} reacted {self.emoji} to message {self.message.id}"


class StarredMessage(models.Model):
    """NEW: Track starred messages per user"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='starred_messages'
    )
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name='starred_by'
    )
    starred_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'starred_messages'
        unique_together = ('user', 'message')
        ordering = ['-starred_at']
        indexes = [
            models.Index(fields=['user', '-starred_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} starred message {self.message.id}"


class BlockedUser(models.Model):
    """NEW: Block users from messaging"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='blocked_users'
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='messaging_blocked_by'  # Unique related_name
    )
    blocked_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'messaging_blocked_users' 
        unique_together = ('blocker', 'blocked')
        indexes = [
            models.Index(fields=['blocker', 'blocked']),
        ]
    
    def __str__(self):
        return f"{self.blocker.username} blocked {self.blocked.username}"


class GroupInviteLink(models.Model):
    """NEW: Shareable invite links for groups"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='invite_links'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_invite_links'
    )
    code = models.CharField(max_length=32, unique=True, db_index=True)  # Random code
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # Optional expiration
    max_uses = models.IntegerField(null=True, blank=True)  # Optional use limit
    use_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'group_invite_links'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['conversation', 'is_active']),
        ]
    
    def __str__(self):
        return f"Invite link {self.code} for {self.conversation.name}"
    
    def is_valid(self):
        """Check if invite link is still valid"""
        if not self.is_active:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        if self.max_uses and self.use_count >= self.max_uses:
            return False
        return True


class TypingStatus(models.Model):
    """Track typing status (can be moved to Redis in production)"""
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='typing_users'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )
    started_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'typing_status'
        unique_together = ('conversation', 'user')
    
    def __str__(self):
        return f"{self.user.username} typing in {self.conversation.id}"
    
    @property
    def is_active(self):
        """Typing is active if started within last 5 seconds"""
        from datetime import timedelta
        return timezone.now() - self.started_at < timedelta(seconds=5)


class UserPresence(models.Model):
    """NEW: Track user online/offline status and last seen"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='presence',
        primary_key=True
    )
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(default=timezone.now)
    last_activity = models.DateTimeField(default=timezone.now)
    
    # Privacy settings
    show_last_seen_to = models.CharField(
        max_length=20,
        choices=[
            ('everyone', 'Everyone'),
            ('contacts', 'My Contacts'),
            ('nobody', 'Nobody'),
        ],
        default='everyone'
    )
    show_online_status_to = models.CharField(
        max_length=20,
        choices=[
            ('everyone', 'Everyone'),
            ('contacts', 'My Contacts'),
            ('nobody', 'Nobody'),
        ],
        default='everyone'
    )
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_presence'
    
    def __str__(self):
        return f"{self.user.username} - {'Online' if self.is_online else 'Offline'}"


class Call(models.Model):
    """Audio and Video calls (WebRTC)"""
    CALL_TYPES = (
        ('audio', 'Audio Call'),
        ('video', 'Video Call'),
    )
    
    CALL_STATUS = (
        ('initiated', 'Initiated'),
        ('ringing', 'Ringing'),
        ('answered', 'Answered'),
        ('rejected', 'Rejected'),
        ('missed', 'Missed'),
        ('ended', 'Ended'),
        ('failed', 'Failed'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        'Conversation',
        on_delete=models.CASCADE,
        related_name='calls'
    )
    caller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='initiated_calls'
    )
    call_type = models.CharField(max_length=10, choices=CALL_TYPES)
    status = models.CharField(max_length=20, choices=CALL_STATUS, default='initiated')
    
    # WebRTC signaling data
    offer_sdp = models.TextField(blank=True)  # SDP offer from caller
    answer_sdp = models.TextField(blank=True)  # SDP answer from callee
    
    # Call timing
    initiated_at = models.DateTimeField(default=timezone.now)
    answered_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration = models.IntegerField(null=True, blank=True)  # Duration in seconds
    
    # Call participants
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='CallParticipant',
        related_name='participated_calls'
    )
    
    class Meta:
        db_table = 'calls'
        ordering = ['-initiated_at']
        indexes = [
            models.Index(fields=['-initiated_at']),
            models.Index(fields=['conversation', '-initiated_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.call_type.title()} call by {self.caller.username} - {self.status}"
    
    def calculate_duration(self):
        """Calculate call duration"""
        if self.answered_at and self.ended_at:
            delta = self.ended_at - self.answered_at
            self.duration = int(delta.total_seconds())
            return self.duration
        return 0


class CallParticipant(models.Model):
    """Track participants in a call"""
    PARTICIPANT_STATUS = (
        ('invited', 'Invited'),
        ('ringing', 'Ringing'),
        ('joined', 'Joined'),
        ('left', 'Left'),
        ('rejected', 'Rejected'),
        ('missed', 'Missed'),
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call = models.ForeignKey(
        'Call',
        on_delete=models.CASCADE,
        related_name='call_participants'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='call_participations'
    )
    status = models.CharField(max_length=20, choices=PARTICIPANT_STATUS, default='invited')
    
    # WebRTC ICE candidates
    ice_candidates = models.JSONField(default=list, blank=True)
    
    # Timing
    invited_at = models.DateTimeField(default=timezone.now)
    joined_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'call_participants'
        unique_together = ('call', 'user')
        ordering = ['invited_at']
    
    def __str__(self):
        return f"{self.user.username} in call {self.call.id} - {self.status}"
