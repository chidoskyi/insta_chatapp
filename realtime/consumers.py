import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken
from asgiref.sync import async_to_sync
from urllib.parse import parse_qs
from django.utils import timezone

from messaging.services.presence_service import presence_service

User = get_user_model()


# ============ CHAT OPERATIONS ============

class ChatConsumer(AsyncWebsocketConsumer): 
    """
    WebSocket consumer for WhatsApp-like real-time chat
    
    IMPORTANT: This consumer now properly integrates with the notification system.
    Notifications are created via signals (post_save) but we ensure proper
    activity tracking so users don't get notified when actively in a conversation.
    """
    
    async def connect(self):
        print(f"🔍 Chat WebSocket connection attempt")
        
        # Get token from query string
        query_string = self.scope.get('query_string', b'').decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]
        
        if not token:
            print("❌ No token provided")
            await self.close(code=4001)
            return
        
        try:
            # Verify token and get user
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            self.user = await self.get_user(user_id)
            self.scope['user'] = self.user
            print(f"✅ Token verified for user: {self.user.username}")
        except Exception as e:
            print(f"❌ Token verification failed: {str(e)}")
            await self.close(code=4003)
            return
        
        # User-wide connection room (for direct notifications to this user)
        self.user_room_name = f'chat_user_{self.user.id}'
        
        # Join user's personal room
        await self.channel_layer.group_add(
            self.user_room_name,
            self.channel_name
        )
        
        # Join all conversations the user is member of
        await self.join_user_conversations()
        
        await self.accept()
        
        # Mark user as online in Redis
        await self.set_user_online(str(self.user.id))
        
        # Send connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'message': 'Connected to chat',
            'user_id': str(self.user.id),
            'username': self.user.username,
            'timestamp': str(timezone.now())
        }))
        
        print(f"✅ User {self.user.username} connected successfully to chat")
        print(f"📋 Joined {len(getattr(self, 'conversation_ids', []))} conversations")

    async def disconnect(self, close_code):
        print(f"🔌 User {getattr(self, 'user', 'Unknown')} disconnecting from chat...")
        
        # Mark user as offline
        if hasattr(self, 'user'):
            await self.set_user_offline(str(self.user.id))
            
            # Notify all conversations that user is offline
            if hasattr(self, 'conversation_ids'):
                for conversation_id in self.conversation_ids:
                    await self.channel_layer.group_send(
                        f'chat_{conversation_id}',
                        {
                            'type': 'user_status',
                            'user_id': str(self.user.id),
                            'username': self.user.username,
                            'status': 'offline',
                            'conversation_id': conversation_id
                        }
                    )
                    
                    # Leave conversation groups
                    await self.channel_layer.group_discard(
                        f'chat_{conversation_id}',
                        self.channel_name
                    )
        
        # Leave user room
        if hasattr(self, 'user_room_name'):
            await self.channel_layer.group_discard(
                self.user_room_name,
                self.channel_name
            )
        
        print(f"✅ User disconnected from chat")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages for chat only"""
        try:
            data = json.loads(text_data)
            action = data.get('action')
            conversation_id = data.get('conversation_id')
            
            print(f"📨 Received chat action: {action} for conversation {conversation_id}")
            
            # Route chat actions only
            if action == 'ping':
                await self.handle_ping()
                
            elif action == 'send_message' and conversation_id:
                await self.handle_send_message(data, str(conversation_id))
                
            elif action == 'typing' and conversation_id:
                await self.handle_typing_indicator(data, str(conversation_id))
                
            elif action == 'mark_read' and conversation_id:
                await self.handle_mark_read(data, str(conversation_id))
                
            elif action == 'mark_all_read' and conversation_id:
                await self.handle_mark_all_read(str(conversation_id))
                
            elif action == 'mark_delivered' and conversation_id:
                await self.handle_mark_delivered(data, str(conversation_id))
                
            elif action == 'react_to_message':
                await self.handle_react_to_message(data)
                
            elif action == 'remove_reaction':
                await self.handle_remove_reaction(data)
                
            elif action == 'delete_message':
                await self.handle_delete_message(data)
                
            elif action == 'edit_message':
                await self.handle_edit_message(data)
                
            elif action == 'join_conversation' and conversation_id:
                await self.handle_join_conversation(str(conversation_id))
                
            elif action == 'leave_conversation' and conversation_id:
                await self.handle_leave_conversation(str(conversation_id))
                
            elif action == 'get_online_status' and conversation_id:
                await self.handle_get_online_status(str(conversation_id))
                
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'error': f'Unknown or invalid action: {action}',
                    'action': action
                }))
                
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Invalid JSON format'
            }))
        except Exception as e:
            print(f"❌ Error in receive: {str(e)}")
            import traceback
            traceback.print_exc()
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Internal server error'
            }))


    # ============ CHAT ACTION HANDLERS ============
    
    async def handle_ping(self):
        """Handle ping/pong for connection keepalive"""
        # Refresh user presence
        await self.refresh_user_presence(str(self.user.id))
        
        await self.send(text_data=json.dumps({
            'type': 'pong',
            'timestamp': str(timezone.now())
        }))
    
    async def handle_send_message(self, data, conversation_id):
        """
        Handle sending a message
        
        NOTIFICATION INTEGRATION:
        - Message is saved via save_message()
        - post_save signal fires automatically
        - Signal checks if recipients are active in conversation
        - If not active → notification created
        - No manual notification creation needed here
        """
        message_content = data.get('message', '').strip()
        message_type = data.get('message_type', 'text')
        reply_to_id = data.get('reply_to')
        
        print(f"📤 User {self.user.username} sending message to conversation {conversation_id}")
        
        # Verify user is member
        is_member = await self.check_conversation_membership(conversation_id)
        if not is_member:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Not a member of this conversation',
                'conversation_id': conversation_id
            }))
            return
        
        # Validate message
        if message_type == 'text' and not message_content:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Message cannot be empty'
            }))
            return
        
        # Check if only admins can send
        can_send = await self.check_can_send_message(conversation_id)
        if not can_send:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Only admins can send messages in this group',
                'conversation_id': conversation_id
            }))
            return
        
        # Validate reply_to if provided
        if reply_to_id:
            reply_exists = await self.validate_reply_message(conversation_id, reply_to_id)
            if not reply_exists:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'error': 'Reply message not found'
                }))
                return
        
        # Save message
        # IMPORTANT: This triggers the post_save signal which creates notifications
        message_obj = await self.save_message(conversation_id, message_content, message_type, reply_to_id)
        
        if message_obj:
            # Serialize the message
            serialized_message = await self.serialize_message(message_obj)
            
            # Broadcast to conversation group
            await self.channel_layer.group_send(
                f'chat_{conversation_id}',
                {
                    'type': 'chat_message',
                    'message': serialized_message,
                    'conversation_id': str(conversation_id),
                    'sender_id': str(self.user.id)
                }
            )
            
            # Send confirmation to sender
            await self.send(text_data=json.dumps({
                'type': 'message_sent',
                'message_id': str(message_obj.id),
                'conversation_id': str(conversation_id),
                'timestamp': str(timezone.now())
            }))
            
            print(f"✅ Message sent to conversation {conversation_id}")

    async def handle_typing_indicator(self, data, conversation_id):
        """Handle typing indicators"""
        is_typing = data.get('is_typing', True)
        
        is_member = await self.check_conversation_membership(conversation_id)
        if not is_member:
            return
        
        # Update Redis typing status
        await self.set_user_typing(conversation_id, str(self.user.id), is_typing)
        
        # Broadcast to conversation (excluding sender)
        await self.channel_layer.group_send(
            f'chat_{conversation_id}',
            {
                'type': 'typing_indicator',
                'user_id': str(self.user.id),
                'username': self.user.username,
                'is_typing': is_typing,
                'conversation_id': str(conversation_id)
            }
        )

    async def handle_mark_read(self, data, conversation_id):
        """
        Mark specific message as read
        
        NOTIFICATION INTEGRATION:
        - Updates last_read_at for ConversationMember
        - This affects notification creation (users active in conversation don't get notified)
        """
        message_id = data.get('message_id')
        
        if not message_id:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'message_id is required'
            }))
            return
        
        is_member = await self.check_conversation_membership(conversation_id)
        if not is_member:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Not a member of this conversation'
            }))
            return
        
        success = await self.mark_message_read(conversation_id, message_id)
        
        if success:
            # Broadcast read receipt to conversation
            await self.channel_layer.group_send(
                f'chat_{conversation_id}',
                {
                    'type': 'message_read',
                    'message_id': str(message_id),
                    'user_id': str(self.user.id),
                    'username': self.user.username,
                    'conversation_id': str(conversation_id)
                }
            )
            
            # Send updated unread count to user
            unread_count = await self.get_user_unread_count(conversation_id)
            await self.send(text_data=json.dumps({
                'type': 'unread_count_update',
                'conversation_id': str(conversation_id),
                'count': unread_count
            }))

    async def handle_mark_all_read(self, conversation_id):
        """Mark all messages as read in conversation"""
        print(f"📖 User {self.user.username} marking all as read in {conversation_id}")
        
        is_member = await self.check_conversation_membership(conversation_id)
        if not is_member:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Not a member of this conversation'
            }))
            return
        
        marked_message_ids = await self.mark_all_messages_read(conversation_id)
        
        if marked_message_ids is not None:
            print(f"✅ Marked {len(marked_message_ids)} messages as read")
            
            # ✅ ONLY broadcast if we actually marked messages
            if len(marked_message_ids) > 0:  # ← ADD THIS CHECK
                # Broadcast to conversation
                await self.channel_layer.group_send(
                    f'chat_{conversation_id}',
                    {
                        'type': 'all_messages_read',
                        'user_id': str(self.user.id),
                        'username': self.user.username,
                        'conversation_id': str(conversation_id),
                        'marked_count': len(marked_message_ids)
                    }
                )
            
            # Always send confirmation to sender
            await self.send(text_data=json.dumps({
                'type': 'all_messages_read_confirm',
                'conversation_id': str(conversation_id),
                'marked_count': len(marked_message_ids)
            }))
            
            print(f"✅ Broadcast all_messages_read event (count: {len(marked_message_ids)})")
        else:
            print(f"❌ mark_all_messages_read returned None")
    
    async def handle_mark_delivered(self, data, conversation_id):
        """Mark message as delivered"""
        message_id = data.get('message_id')
        
        if not message_id:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'message_id is required'
            }))
            return
        
        print(f"📬 [Delivery] User {self.user.username} marking message {message_id} as delivered")
        
        success = await self.mark_message_delivered(conversation_id, message_id)
        
        if success:
            print(f"✅ [Delivery] Broadcasting delivery receipt for message {message_id}")
            # Broadcast delivery receipt to ALL members
            await self.channel_layer.group_send(
                f'chat_{conversation_id}',
                {
                    'type': 'message_delivered',
                    'message_id': message_id,
                    'user_id': str(self.user.id),
                    'conversation_id': str(conversation_id)
                }
            )
        else:
            print(f"❌ [Delivery] Failed to mark message {message_id} as delivered")
    
    async def handle_react_to_message(self, data):
        """
        Add reaction to message
        
        NOTIFICATION INTEGRATION:
        - Reaction is saved via add_reaction()
        - post_save signal on MessageReaction fires
        - Signal creates notification for message author
        """
        message_id = data.get('message_id')
        emoji = data.get('emoji')
        
        if not message_id or not emoji:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'message_id and emoji are required'
            }))
            return
        
        # Save reaction (this triggers the signal)
        reaction = await self.add_reaction(message_id, emoji)
        
        if reaction:
            conversation_id = reaction['conversation_id']
            
            # Broadcast reaction to conversation
            await self.channel_layer.group_send(
                f'chat_{conversation_id}',
                {
                    'type': 'message_reaction',
                    'message_id': message_id,
                    'user_id': str(self.user.id),
                    'username': self.user.username,
                    'emoji': emoji,
                    'conversation_id': str(conversation_id)
                }
            )
            # Note: Notification is automatically created by signal handler
    
    async def handle_remove_reaction(self, data):
        """
        Remove reaction from message
        
        NOTIFICATION INTEGRATION:
        - Reaction is deleted via remove_reaction()
        - post_delete signal on MessageReaction fires
        - Signal deletes the notification
        """
        message_id = data.get('message_id')
        
        if not message_id:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'message_id is required'
            }))
            return
        
        result = await self.remove_reaction(message_id)
        
        if result:
            conversation_id = result['conversation_id']
            
            # Broadcast reaction removal
            await self.channel_layer.group_send(
                f'chat_{conversation_id}',
                {
                    'type': 'reaction_removed',
                    'message_id': message_id,
                    'user_id': str(self.user.id),
                    'conversation_id': str(conversation_id)
                }
            )
            # Note: Notification is automatically deleted by signal handler
    
    async def handle_delete_message(self, data):
        """
        Delete message
        
        NOTIFICATION INTEGRATION:
        - If deleted_for_everyone=True, post_save signal updates notification
        - Notification is deleted via signal handler
        """
        message_id = data.get('message_id')
        delete_for_everyone = data.get('delete_for_everyone', False)
        
        if not message_id:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'message_id is required'
            }))
            return
        
        result = await self.delete_message(message_id, delete_for_everyone)
        
        if result:
            conversation_id = result['conversation_id']
            
            # Broadcast deletion
            await self.channel_layer.group_send(
                f'chat_{conversation_id}',
                {
                    'type': 'message_deleted',
                    'message_id': message_id,
                    'user_id': str(self.user.id),
                    'delete_for_everyone': delete_for_everyone,
                    'conversation_id': str(conversation_id)
                }
            )
            # Note: Notification is automatically handled by signal
    
    async def handle_edit_message(self, data):
        """Edit message - does NOT affect notifications"""
        message_id = data.get('message_id')
        new_body = data.get('body', '').strip()
        
        if not message_id or not new_body:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'message_id and body are required'
            }))
            return
        
        result = await self.edit_message(message_id, new_body)
        
        if result:
            conversation_id = result['conversation_id']
            
            # Broadcast edit
            await self.channel_layer.group_send(
                f'chat_{conversation_id}',
                {
                    'type': 'message_edited',
                    'message_id': message_id,
                    'body': new_body,
                    'conversation_id': str(conversation_id)
                }
            )
    
    async def handle_join_conversation(self, conversation_id):
        """
        Join a specific conversation group
        
        NOTIFICATION INTEGRATION:
        - Marks user as active in conversation
        - Updates last_read_at
        - Prevents future notifications while active
        """
        is_member = await self.check_conversation_membership(conversation_id)
        if not is_member:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Not a member of this conversation',
                'conversation_id': conversation_id
            }))
            return
        
        # Join conversation group
        await self.channel_layer.group_add(
            f'chat_{conversation_id}',
            self.channel_name
        )
        
        # IMPORTANT: Mark conversation as read
        # This updates last_read_at which is used by notification system
        await self.mark_conversation_as_active(conversation_id)
        
        # Mark user as online in this conversation
        await self.channel_layer.group_send(
            f'chat_{conversation_id}',
            {
                'type': 'user_status',
                'user_id': str(self.user.id),
                'username': self.user.username,
                'status': 'online',
                'conversation_id': str(conversation_id)
            }
        )
        
        # Get unread status
        has_unread = await self.has_unread_messages_from_others(conversation_id)
        
        # Get online users in this conversation
        online_users = await self.get_online_users_in_conversation(conversation_id)
        
        await self.send(text_data=json.dumps({
            'type': 'conversation_joined',
            'conversation_id': str(conversation_id),
            'has_unread': has_unread,
            'online_users': online_users,
            'timestamp': str(timezone.now())
        }))
        
        print(f"✅ User {self.user.username} joined conversation {conversation_id} (marked as active)")
    
    async def handle_leave_conversation(self, conversation_id):
        """
        Leave a specific conversation group
        
        NOTIFICATION INTEGRATION:
        - User is no longer "active" in conversation
        - Will receive notifications for new messages
        """
        # Notify others
        await self.channel_layer.group_send(
            f'chat_{conversation_id}',
            {
                'type': 'user_status',
                'user_id': str(self.user.id),
                'username': self.user.username,
                'status': 'offline',
                'conversation_id': str(conversation_id)
            }
        )
        
        await self.channel_layer.group_discard(
            f'chat_{conversation_id}',
            self.channel_name
        )
        
        await self.send(text_data=json.dumps({
            'type': 'conversation_left',
            'conversation_id': str(conversation_id),
            'timestamp': str(timezone.now())
        }))
        
        print(f"✅ User {self.user.username} left conversation {conversation_id} (no longer active)")
    
    async def handle_get_online_status(self, conversation_id):
        """Get online users in conversation"""
        online_users = await self.get_online_users_in_conversation(conversation_id)
        
        await self.send(text_data=json.dumps({
            'type': 'online_status',
            'conversation_id': str(conversation_id),
            'online_users': online_users,
            'timestamp': str(timezone.now())
        }))

    # ============ CHANNEL LAYER EVENT HANDLERS ============
    
    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'data': event['message'],
            'conversation_id': event['conversation_id'],
            'timestamp': str(timezone.now())
        }))
    
    async def typing_indicator(self, event):
        """Receive typing indicators"""
        # Don't send back to sender
        if str(event['user_id']) != str(self.user.id):
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'user_id': event['user_id'],
                'username': event['username'],
                'is_typing': event['is_typing'],
                'conversation_id': event['conversation_id']
            }))
    
    async def message_read(self, event):
        """Receive read receipts"""
        await self.send(text_data=json.dumps({
            'type': 'read_receipt',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'username': event['username'],
            'conversation_id': event['conversation_id']
        }))
    
    async def all_messages_read(self, event):
        """Receive all messages read event"""
        # Don't echo own read receipts
        if str(event['user_id']) != str(self.user.id):
            await self.send(text_data=json.dumps({
                'type': 'all_read_receipt',
                'user_id': event['user_id'],
                'username': event['username'],
                'conversation_id': event['conversation_id'],
                'marked_count': event.get('marked_count', 0)
            }))
    
    async def message_delivered(self, event):
        """Receive delivery receipts - send to EVERYONE including sender"""
        await self.send(text_data=json.dumps({
            'type': 'delivery_receipt',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'conversation_id': event['conversation_id'],
            'timestamp': str(timezone.now())
        }))
    
    async def message_reaction(self, event):
        """Receive message reactions"""
        await self.send(text_data=json.dumps({
            'type': 'reaction',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'username': event['username'],
            'emoji': event['emoji'],
            'conversation_id': event['conversation_id']
        }))
    
    async def reaction_removed(self, event):
        """Receive reaction removal"""
        await self.send(text_data=json.dumps({
            'type': 'reaction_removed',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'conversation_id': event['conversation_id']
        }))
    
    async def message_deleted(self, event):
        """Receive message deletion"""
        await self.send(text_data=json.dumps({
            'type': 'message_deleted',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'delete_for_everyone': event['delete_for_everyone'],
            'conversation_id': event['conversation_id']
        }))
    
    async def message_edited(self, event):
        """Receive message edit"""
        await self.send(text_data=json.dumps({
            'type': 'message_edited',
            'message_id': event['message_id'],
            'body': event['body'],
            'conversation_id': event['conversation_id']
        }))
    
    async def user_status(self, event):
        """Receive user online/offline status"""
        # Don't send own status back
        if str(event['user_id']) != str(self.user.id):
            await self.send(text_data=json.dumps({
                'type': 'user_status',
                'user_id': event['user_id'],
                'username': event['username'],
                'status': event['status'],
                'conversation_id': event.get('conversation_id'),
                'timestamp': str(timezone.now())
            }))
    
    async def conversation_updated(self, event):
        """Receive conversation updates (members added, name changed, etc.)"""
        await self.send(text_data=json.dumps({
            'type': 'conversation_updated',
            'conversation_id': event['conversation_id'],
            'data': event.get('data', {}),
            'timestamp': str(timezone.now())
        }))


    # ============ DATABASE OPERATIONS ============
    
    @database_sync_to_async
    def get_user(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return AnonymousUser()
    
    @database_sync_to_async
    def join_user_conversations(self):
        """Get list of conversation IDs user is member of and join their groups"""
        from messaging.models import ConversationMember
        
        memberships = ConversationMember.objects.filter(
            user=self.user,
            left_at__isnull=True
        ).select_related('conversation')
        
        self.conversation_ids = []
        for membership in memberships:
            conversation_id = str(membership.conversation_id)
            self.conversation_ids.append(conversation_id)
            
            # Join conversation group in channel layer
            async_to_sync(self.channel_layer.group_add)(
                f'chat_{conversation_id}',
                self.channel_name
            )
        
        print(f"📋 User {self.user.username} is member of {len(self.conversation_ids)} conversations")
    
    @database_sync_to_async
    def check_conversation_membership(self, conversation_id):
        from messaging.models import ConversationMember
        return ConversationMember.objects.filter(
            conversation_id=conversation_id,
            user=self.user,
            left_at__isnull=True
        ).exists()
    
    @database_sync_to_async
    def check_can_send_message(self, conversation_id):
        """Check if user can send messages (for groups with only_admins_can_send)"""
        from messaging.models import Conversation, ConversationMember
        
        conversation = Conversation.objects.get(id=conversation_id)
        
        if not conversation.only_admins_can_send:
            return True
        
        # Check if user is admin
        return ConversationMember.objects.filter(
            conversation_id=conversation_id,
            user=self.user,
            is_admin=True,
            left_at__isnull=True
        ).exists()
    
    @database_sync_to_async
    def save_message(self, conversation_id, body, message_type, reply_to_id=None):
        """
        Save message to database
        
        CRITICAL: This triggers post_save signal which creates notifications
        """
        from messaging.models import Message, Conversation, MessageRead, ConversationMember
        
        try:
            conversation = Conversation.objects.get(id=conversation_id)
            
            message = Message.objects.create(
                conversation=conversation,
                sender=self.user,
                body=body,
                message_type=message_type,
                reply_to_id=reply_to_id,
                created_at=timezone.now()
            )
            
            # Mark as read and delivered by sender
            MessageRead.objects.create(message=message, user=self.user)
            message.delivered_to.add(self.user)
            
            # IMPORTANT: Update sender's last_read_at
            # This marks them as "active" in the conversation
            member = ConversationMember.objects.get(
                conversation=conversation,
                user=self.user
            )
            member.last_read_at = timezone.now()
            member.save(update_fields=['last_read_at'])
            
            # Update conversation timestamp
            conversation.updated_at = timezone.now()
            conversation.save(update_fields=['updated_at'])
            
            print(f"✅ Message saved - post_save signal will handle notifications")
            return message
        except Exception as e:
            print(f"❌ Failed to save message: {str(e)}")
            return None
    
    @database_sync_to_async
    def mark_conversation_as_active(self, conversation_id):
        """
        Mark user as active in conversation
        
        CRITICAL FOR NOTIFICATIONS:
        This updates last_read_at which prevents notifications from being created
        """
        from messaging.models import ConversationMember
        
        try:
            member = ConversationMember.objects.get(
                conversation_id=conversation_id,
                user=self.user
            )
            member.last_read_at = timezone.now()
            member.save(update_fields=['last_read_at'])
            print(f"✅ Marked user as active in conversation {conversation_id}")
            return True
        except Exception as e:
            print(f"❌ Failed to mark as active: {str(e)}")
            return False
    
    @database_sync_to_async
    def serialize_message(self, message):
        """Serialize message for WebSocket transmission"""
        from messaging.serializers import MessageSerializer
        
        # ✅ CRITICAL: Create a fake request object with the current user
        class FakeRequest:
            def __init__(self, user, scheme='http', host='localhost:8000'):
                self.user = user
                self.scheme = scheme
                self.META = {'HTTP_HOST': host}
            
            def build_absolute_uri(self, path):
                """Build absolute URL for media files"""
                return f"{self.scheme}://{self.META['HTTP_HOST']}{path}"
        
        # ✅ FIX: Use proper scheme and host
        fake_request = FakeRequest(
            self.user,
            scheme='http',  # or 'https' in production
            host='localhost:8000'  # or your actual domain
        )
        
        serializer = MessageSerializer(message, context={'request': fake_request})
        data = serializer.data
        
        # ✅ CRITICAL: Ensure media_url is included
        print(f"📸 Serialized message: type={data.get('message_type')}, media_url={data.get('media_url')}")
        
        # Ensure all UUIDs are strings
        def ensure_serializable(obj):
            if isinstance(obj, dict):
                return {k: ensure_serializable(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [ensure_serializable(item) for item in obj]
            elif hasattr(obj, '__str__') and type(obj).__name__ == 'UUID':
                return str(obj)
            return obj
        
        return ensure_serializable(data)
    
    @database_sync_to_async
    def mark_message_read(self, conversation_id, message_id):
        from messaging.models import Message, MessageRead, ConversationMember
        
        try:
            message = Message.objects.get(id=message_id, conversation_id=conversation_id)
            
            if message.sender == self.user:
                return False
            
            MessageRead.objects.get_or_create(
                message=message,
                user=self.user,
                defaults={'read_at': timezone.now()}
            )
            
            # Also mark as delivered
            message.delivered_to.add(self.user)
            
            # Update last_read_at
            member = ConversationMember.objects.get(
                conversation_id=conversation_id,
                user=self.user
            )
            member.last_read_at = timezone.now()
            member.save(update_fields=['last_read_at'])
            
            return True
        except Exception as e:
            print(f"❌ Error marking message as read: {str(e)}")
            return False
    
    @database_sync_to_async
    def mark_all_messages_read(self, conversation_id):
        from messaging.models import Message, MessageRead, ConversationMember
        from django.db.models import Q
        
        try:
            unread_messages = Message.objects.filter(
                conversation_id=conversation_id,
                deleted_for_everyone=False
            ).exclude(
                Q(sender=self.user) | Q(read_by__user=self.user)
            ).order_by('created_at')
            
            message_ids = list(unread_messages.values_list('id', flat=True))
            
            # Bulk create read receipts
            read_receipts = [
                MessageRead(message_id=msg_id, user=self.user, read_at=timezone.now())
                for msg_id in message_ids
            ]
            
            if read_receipts:
                MessageRead.objects.bulk_create(read_receipts, ignore_conflicts=True)
            
            # Mark all as delivered
            for message in unread_messages:
                message.delivered_to.add(self.user)
            
            # Update last_read_at
            member = ConversationMember.objects.get(
                conversation_id=conversation_id,
                user=self.user
            )
            member.last_read_at = timezone.now()
            member.save(update_fields=['last_read_at'])
            
            return [str(mid) for mid in message_ids]
        except Exception as e:
            print(f"❌ Error marking all as read: {str(e)}")
            return []
    
    @database_sync_to_async
    def mark_message_delivered(self, conversation_id, message_id):
        from messaging.models import Message
        
        try:
            message = Message.objects.get(id=message_id, conversation_id=conversation_id)
            
            # Don't mark own messages
            if message.sender == self.user:
                return False
            
            # Add to delivered_to
            message.delivered_to.add(self.user)
            
            # Get delivery count for status update
            delivery_count = message.delivered_to.count()
            total_recipients = message.conversation.members.filter(
                left_at__isnull=True
            ).exclude(user=message.sender).count()
            
            print(f"✅ Message {message_id} delivered to {delivery_count}/{total_recipients} recipients")
            
            return True
        except Exception as e:
            print(f"❌ Error marking as delivered: {str(e)}")
            return False
        
    @database_sync_to_async
    def add_reaction(self, message_id, emoji):
        """
        Add reaction - triggers post_save signal
        """
        from messaging.models import Message, MessageReaction
        
        try:
            message = Message.objects.get(id=message_id)
            
            # Verify membership
            if not message.conversation.members.filter(
                user=self.user, left_at__isnull=True
            ).exists():
                return None
            
            reaction, created = MessageReaction.objects.update_or_create(
                message=message,
                user=self.user,
                defaults={'emoji': emoji, 'created_at': timezone.now()}
            )
            
            print(f"✅ Reaction added - post_save signal will handle notification")
            return {
                'conversation_id': str(message.conversation_id),
                'created': created
            }
        except Exception as e:
            print(f"❌ Error adding reaction: {str(e)}")
            return None
    
    @database_sync_to_async
    def remove_reaction(self, message_id):
        """
        Remove reaction - triggers post_delete signal
        """
        from messaging.models import Message, MessageReaction
        
        try:
            message = Message.objects.get(id=message_id)
            
            deleted_count, _ = MessageReaction.objects.filter(
                message=message,
                user=self.user
            ).delete()
            
            if deleted_count > 0:
                print(f"✅ Reaction removed - post_delete signal will handle notification")
                return {'conversation_id': str(message.conversation_id)}
            return None
        except Exception as e:
            print(f"❌ Error removing reaction: {str(e)}")
            return None
    
    @database_sync_to_async
    def delete_message(self, message_id, delete_for_everyone):
        from messaging.models import Message
        from datetime import timedelta
        
        try:
            message = Message.objects.get(id=message_id, sender=self.user)
            
            # Check time limit for delete for everyone (1 hour)
            if delete_for_everyone:
                if timezone.now() - message.created_at > timedelta(hours=1):
                    return None
                message.deleted_for_everyone = True
                message.body = "This message was deleted"
            
            message.is_deleted = True
            message.deleted_at = timezone.now()
            message.save()
            
            print(f"✅ Message deleted - signal will handle notification cleanup")
            return {'conversation_id': str(message.conversation_id)}
        except Exception as e:
            print(f"❌ Error deleting message: {str(e)}")
            return None
    
    @database_sync_to_async
    def edit_message(self, message_id, new_body):
        from messaging.models import Message
        
        try:
            message = Message.objects.get(id=message_id, sender=self.user)
            
            message.body = new_body
            message.is_edited = True
            message.save()
            
            return {'conversation_id': str(message.conversation_id)}
        except Exception as e:
            print(f"❌ Error editing message: {str(e)}")
            return None
    
    @database_sync_to_async
    def validate_reply_message(self, conversation_id, reply_to_id):
        from messaging.models import Message
        return Message.objects.filter(
            id=reply_to_id,
            conversation_id=conversation_id
        ).exists()
    
    @database_sync_to_async
    def has_unread_messages_from_others(self, conversation_id):
        from messaging.models import Message
        from django.db.models import Q
        
        try:
            unread_count = Message.objects.filter(
                conversation_id=conversation_id,
                deleted_for_everyone=False
            ).exclude(
                Q(sender=self.user) | Q(read_by__user=self.user)
            ).count()
            
            return unread_count > 0
        except Exception as e:
            print(f"❌ Error checking unread: {str(e)}")
            return False
    
    @database_sync_to_async
    def get_user_unread_count(self, conversation_id):
        from messaging.models import Message
        from django.db.models import Q
        
        try:
            return Message.objects.filter(
                conversation_id=conversation_id,
                deleted_for_everyone=False
            ).exclude(
                Q(sender=self.user) | Q(read_by__user=self.user)
            ).count()
        except Exception as e:
            return 0
    
    @database_sync_to_async
    def get_online_users_in_conversation(self, conversation_id):
        """Get list of online users in a conversation"""
        from messaging.models import ConversationMember
        
        try:
            # Get all members
            members = ConversationMember.objects.filter(
                conversation_id=conversation_id,
                left_at__isnull=True
            ).select_related('user')
            
            # Check online status from Redis
            online_users = []
            for member in members:
                if member.user != self.user:
                    is_online = presence_service.is_user_online(str(member.user.id))
                    if is_online:
                        online_users.append({
                            'user_id': str(member.user.id),
                            'username': member.user.username
                        })
            
            return online_users
        except Exception as e:
            print(f"❌ Error getting online users: {str(e)}")
            return []
    
    # ============ REDIS PRESENCE OPERATIONS ============
    
    async def set_user_online(self, user_id):
        """Mark user as online in Redis"""
        await database_sync_to_async(presence_service.set_user_online)(user_id)
    
    async def set_user_offline(self, user_id):
        """Mark user as offline in Redis"""
        await database_sync_to_async(presence_service.set_user_offline)(user_id)
    
    async def refresh_user_presence(self, user_id):
        """Refresh user's online status"""
        await database_sync_to_async(presence_service.refresh_user_presence)(user_id)
    
    async def set_user_typing(self, conversation_id, user_id, is_typing):
        """Set typing status in Redis"""
        await database_sync_to_async(presence_service.set_user_typing)(
            conversation_id, user_id, is_typing
        )
    
    
        
# ============ CALL OPERATIONS ============
    
class CallConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for WebRTC calls
    
    NOTIFICATION INTEGRATION:
    - Missed calls trigger notifications via signals
    - CallParticipant status changes create notifications
    """
    
    _ice_candidate_buffer = {}
    async def connect(self):
        print(f"🔍 Call WebSocket connection attempt")
        
        # Get token from query string
        query_string = self.scope.get('query_string', b'').decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]
        
        if not token:
            print("❌ No token provided for call connection")
            await self.close(code=4001)
            return
        
        try:
            # Verify token and get user
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            self.user = await self.get_user(user_id)
            self.scope['user'] = self.user
            print(f"✅ Call token verified for user: {self.user.username}")
        except Exception as e:
            print(f"❌ Call token verification failed: {str(e)}")
            await self.close(code=4003)
            return
        
        # User room for call signaling
        self.user_room_name = f'calls_user_{self.user.id}'
        
        await self.channel_layer.group_add(
            self.user_room_name,
            self.channel_name
        )
        
        await self.accept()
        
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'message': 'Connected to call service',
            'user_id': str(self.user.id)
        }))
        
        print(f"✅ User {self.user.username} connected to call service")
    
    async def disconnect(self, close_code):
        print(f"🔌 User {getattr(self, 'user', 'Unknown')} disconnecting from calls...")
        
        # Leave user room
        if hasattr(self, 'user_room_name'):
            await self.channel_layer.group_discard(
                self.user_room_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """Handle call signaling messages"""
        try:
            data = json.loads(text_data)
            action = data.get('action')
            call_id = data.get('call_id')
            
            print(f"📞 Call action: {action} for call {call_id}")
            
            if action == 'initiate_call':
                await self.handle_initiate_call(data)
                
            elif action == 'answer_call':
                await self.handle_answer_call(data)
            
            elif action == 'join_call':
                await self.handle_join_call(data)
                
            elif action == 'reject_call':
                await self.handle_reject_call(data)
                
            elif action == 'end_call':
                await self.handle_end_call(data)
                
            elif action == 'call_signal':
                await self.handle_call_signal(data)
                
            elif action == 'ice_candidate':
                await self.handle_ice_candidate(data)
                
            elif action == 'join_call_room':
                await self.handle_join_call_room(data)
                
            elif action == 'leave_call_room':
                await self.handle_leave_call_room(data)
                
            elif action == 'ping':
                await self.handle_ping()
                
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'error': f'Unknown call action: {action}'
                }))
                
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Invalid JSON format'
            }))
    

    
    # ============ ACTION HANDLERS ============
    
    async def handle_initiate_call(self, data):
        """
        Handle call initiation - FIXED with proper error handling
        """
        try:
            conversation_id = data.get('conversation_id')
            call_type = data.get('call_type')
            offer_sdp = data.get('offer_sdp', '')
            
            print(f"📞 [Call] Initiating call:")
            print(f"  - Conversation: {conversation_id}")
            print(f"  - Type: {call_type}")
            print(f"  - User: {self.user.username}")
            print(f"  - Offer SDP length: {len(offer_sdp)}")
            
            # Verify user is member
            is_member = await self.check_conversation_membership(conversation_id)
            if not is_member:
                print(f"❌ [Call] User {self.user.username} is not a member")
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'error': 'Not a member of this conversation'
                }))
                return
            
            # Create call in database
            print(f"💾 [Call] Creating call in database...")
            call = await self.create_call(conversation_id, call_type, offer_sdp)
            
            if not call:
                print(f"❌ [Call] Failed to create call in database")
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'error': 'Failed to create call'
                }))
                return
            
            call_id = str(call['id'])
            print(f"✅ [Call] Call created with ID: {call_id}")
            
            # Create call room
            self.call_room_name = f'call_{call_id}'
            await self.channel_layer.group_add(
                self.call_room_name,
                self.channel_name
            )
            print(f"📡 [Call] Joined call room: {self.call_room_name}")
            
            # ✅ FIX: Get all conversation members
            print(f"👥 [Call] Getting conversation members...")
            members = await self.get_conversation_members(conversation_id)
            print(f"👥 [Call] Found {len(members)} members: {[m['username'] for m in members]}")
            
            # ✅ FIX: Notify ALL participants with is_caller flag
            for member in members:
                is_caller = member["user_id"] == str(self.user.id)
                
                print(f"📤 [Call] Sending call_initiated to {member['username']} (is_caller={is_caller})")
                
                await self.channel_layer.group_send(
                    f'calls_user_{member["user_id"]}',
                    {
                        'type': 'call_initiated',
                        'call_id': call_id,
                        'caller_id': str(self.user.id),
                        'caller_username': self.user.username,
                        'call_type': call_type,
                        'conversation_id': conversation_id,
                        'offer_sdp': offer_sdp,
                        'is_caller': is_caller,  # ✅ CRITICAL FLAG
                    }
                )
            
            print(f"✅ [Call] All participants notified")
            
            # Send confirmation to caller
            await self.send(text_data=json.dumps({
                'type': 'call_created',
                'call_id': call_id,
                'call_type': call_type,
                'status': 'invited'
            }))
            
            print(f"✅ [Call] Initiation complete")
            
        except Exception as e:
            print(f"❌ [Call] Exception in handle_initiate_call: {str(e)}")
            print(f"❌ [Call] Exception type: {type(e).__name__}")
            import traceback
            print(f"❌ [Call] Traceback: {traceback.format_exc()}")
            
            # Send error to client
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': f'Failed to initiate call: {str(e)}'
            }))
    
    async def handle_answer_call(self, data):
        """
        Handle when user answers a call - FIXED
        """
        try:
            call_id = data.get('call_id')
            answer_sdp = data.get('answer_sdp', '')
            
            if not call_id:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'error': 'call_id is required'
                }))
                return
            
            print(f"========================================")
            print(f"✅ ANSWER CALL RECEIVED")
            print(f"========================================")
            print(f"User: {self.user.username}")
            print(f"Call ID: {call_id}")
            print(f"Answer SDP length: {len(answer_sdp)}")
            print(f"========================================")
            
            # Update database
            result = await self.answer_call(call_id, answer_sdp)
            
            if not result:
                print(f"❌ Failed to update call in database")
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'error': 'Failed to answer call'
                }))
                return
            
            # Join call room if not already joined
            if not hasattr(self, 'call_room_name'):
                self.call_room_name = f'call_{call_id}'
                await self.channel_layer.group_add(
                    self.call_room_name,
                    self.channel_name
                )
                print(f"📡 Joined call room: {self.call_room_name}")
            
            # ✅ CRITICAL: Notify ALL participants in call room
            print(f"📤 Sending call_answered to all participants in room")
            await self.channel_layer.group_send(
                self.call_room_name,
                {
                    'type': 'call_answered',  # ← This calls the method below
                    'call_id': call_id,
                    'user_id': str(self.user.id),
                    'username': self.user.username,
                    'answer_sdp': answer_sdp,  # ✅ MUST include this
                }
            )
            
            print(f"✅ All participants notified")
            print(f"========================================")
            
        except Exception as e:
            print(f"❌ Exception in handle_answer_call: {str(e)}")
            import traceback
            print(traceback.format_exc())
            
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': f'Failed to answer call: {str(e)}'
            }))
    
    async def handle_join_call(self, data):
        """
        Receiver joins the call room early so it receives ICE candidates.
        
        ✅ After joining, replays any candidates that were sent BEFORE
           this user was in the room (the race-condition fix).
        """
        call_id = data.get('call_id')
        if not call_id:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'call_id is required'
            }))
            return

        call_room = f'call_{call_id}'

        # Join the room first
        self.call_room_name = call_room
        await self.channel_layer.group_add(call_room, self.channel_name)
        print(f"📡 [join_call] {self.user.username} joined call room: {call_room}")

        # ✅ Replay any buffered candidates directly to THIS user's WebSocket.
        #    These are candidates the caller sent before we were in the room.
        buffered = self._ice_candidate_buffer.pop(call_room, [])
        if buffered:
            print(f"📦 [join_call] Replaying {len(buffered)} buffered ICE candidates to {self.user.username}")
            current_user_id = str(self.user.id)

            for event in buffered:
                # Same filter as ice_candidate() — skip ones from ourselves
                if event['from_user_id'] != current_user_id:
                    await self.send(text_data=json.dumps({
                        'type': 'ice_candidate',
                        'call_id': event['call_id'],
                        'from_user_id': event['from_user_id'],
                        'from_username': event['from_username'],
                        'candidate': event['candidate'],
                    }))
                    print(f"  ↳ Replayed candidate from {event['from_username']}")
            print(f"✅ [join_call] Replay complete")
        else:
            print(f"📦 [join_call] No buffered candidates to replay")
    
    async def handle_reject_call(self, data):
        """
        Reject a call
        
        NOTIFICATION INTEGRATION:
        - Call.status = 'rejected' triggers signal
        - Signal creates notification for caller
        """
        call_id = data.get('call_id')
        call_room = f'call_{data.get("call_id", "")}'
        self._ice_candidate_buffer.pop(call_room, None)
        
        if not call_id:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'call_id is required'
            }))
            return
        
        # Update database
        result = await self.reject_call(call_id)
        
        if result:
            # Notify participants
            await self.channel_layer.group_send(
                f'call_{call_id}',
                {
                    'type': 'call_rejected',
                    'call_id': call_id,
                    'user_id': str(self.user.id),
                    'username': self.user.username
                }
            )
            
            print(f"✅ Call rejected - signal will create notification")

    
    async def handle_end_call(self, data):
        """End a call"""
        call_id = data.get('call_id')
        
        if not call_id:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'call_id is required'
            }))
            return
        
        # Update database
        result = await self.end_call(call_id)
        
        if result:
            # Leave call room
            if hasattr(self, 'call_room_name'):
                await self.channel_layer.group_discard(
                    self.call_room_name,
                    self.channel_name
                )
            
            # Notify participants
            await self.channel_layer.group_send(
                f'call_{call_id}',
                {
                    'type': 'call_ended',
                    'call_id': call_id,
                    'user_id': str(self.user.id),
                    'username': self.user.username,
                    'duration': result.get('duration', 0)
                }
            )
    
    async def handle_call_signal(self, data):
        """Handle WebRTC signaling"""
        call_id = data.get('call_id')
        signal = data.get('signal')
        target_user_id = data.get('target_user_id')
        
        if not call_id or not signal:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'call_id and signal are required'
            }))
            return
        
        # Forward to specific user or broadcast
        if target_user_id:
            await self.channel_layer.group_send(
                f'calls_user_{target_user_id}',
                {
                    'type': 'call_signal',
                    'call_id': call_id,
                    'from_user_id': str(self.user.id),
                    'signal': signal
                }
            )
        else:
            if hasattr(self, 'call_room_name'):
                await self.channel_layer.group_send(
                    self.call_room_name,
                    {
                        'type': 'call_signal',
                        'call_id': call_id,
                        'from_user_id': str(self.user.id),
                        'signal': signal
                    }
                )
    
    async def handle_ice_candidate(self, data):
        """
        Handle ICE candidate exchange.
        
        If the receiver hasn't joined the call room yet, candidates
        are buffered and replayed when they do (handle_join_call).
        """
        try:
            call_id = data.get('call_id')
            candidate = data.get('candidate')

            if not call_id or not candidate:
                print(f"❌ [ICE] Missing data: call_id={call_id}, candidate={'present' if candidate else 'missing'}")
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'error': 'call_id and candidate are required'
                }))
                return

            print(f"========================================")
            print(f"🧊 [ICE] RECEIVED FROM {self.user.username}")
            print(f"========================================")
            print(f"Call ID: {call_id}")
            print(f"Candidate: {candidate.get('candidate', 'N/A')[:60]}...")
            print(f"Type: {candidate.get('type', 'unknown')}")
            print(f"========================================")

            call_room = f'call_{call_id}'

            # ✅ Build the event once — used for both buffer and broadcast
            event = {
                'type': 'ice_candidate',
                'call_id': call_id,
                'from_user_id': str(self.user.id),
                'from_username': self.user.username,
                'candidate': candidate,
            }

            # ✅ Always buffer it. If the receiver is already in the room
            #    the broadcast below delivers it instantly AND it sits in the
            #    buffer harmlessly (join_call already ran, so it won't replay).
            if call_room not in self._ice_candidate_buffer:
                self._ice_candidate_buffer[call_room] = []
            self._ice_candidate_buffer[call_room].append(event)
            print(f"📦 [ICE] Buffered (total in buffer: {len(self._ice_candidate_buffer[call_room])})")

            # Broadcast to whoever IS in the room right now
            print(f"📤 [ICE] Forwarding to room: {call_room}")
            await self.channel_layer.group_send(call_room, event)
            print(f"✅ [ICE] Sent to channel layer")
            print(f"========================================")

        except Exception as e:
            print(f"❌ [ICE] Exception in handle_ice_candidate: {str(e)}")
            import traceback
            print(traceback.format_exc())

            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': f'Failed to handle ICE candidate: {str(e)}'
            }))
    
    async def handle_join_call_room(self, data):
        """Join a specific call room"""
        call_id = data.get('call_id')
        
        if not call_id:
            return
        
        self.call_room_name = f'call_{call_id}'
        await self.channel_layer.group_add(
            self.call_room_name,
            self.channel_name
        )
        
        await self.send(text_data=json.dumps({
            'type': 'call_room_joined',
            'call_id': call_id
        }))
    
    async def handle_leave_call_room(self, data):
        """Leave call room"""
        if hasattr(self, 'call_room_name'):
            await self.channel_layer.group_discard(
                self.call_room_name,
                self.channel_name
            )
            await self.send(text_data=json.dumps({
                'type': 'call_room_left'
            }))
    
    async def incoming_call(self, event):
       await self.call_initiated(event)
    
    async def handle_ping(self):
        """Handle ping for connection keepalive"""
        await self.send(text_data=json.dumps({
            'type': 'pong',
            'timestamp': str(timezone.now())
        }))
    
    # ============ EVENT HANDLERS ============
    
    async def call_initiated(self, event):
        """
        Receive call initiation - FIXED
        
        This is called when channel_layer.group_send sends 'call_initiated'
        """
        try:
            print(f"📨 [Call] Received call_initiated event:")
            print(f"  - Call ID: {event['call_id']}")
            print(f"  - From: {event['caller_username']}")
            print(f"  - Is Caller: {event.get('is_caller', False)}")
            print(f"  - Current User: {self.user.username}")
            
            await self.send(text_data=json.dumps({
                'type': 'incoming_call',  # ✅ Change to match frontend expectation
                'call_id': event['call_id'],
                'caller_id': event['caller_id'],
                'caller_username': event['caller_username'],
                'call_type': event['call_type'],
                'conversation_id': event['conversation_id'],
                'offer_sdp': event.get('offer_sdp', ''),
                'is_caller': event.get('is_caller', False),  # ✅ Include flag
            }))
            
            print(f"✅ [Call] Sent incoming_call to {self.user.username}")
            
        except Exception as e:
            print(f"❌ [Call] Error in call_initiated handler: {str(e)}")
    
    async def call_answered(self, event):
        """
        Receive call_answered from channel layer and send to WebSocket client
        
        CRITICAL: This is called when channel_layer.group_send sends 'call_answered'
        It must forward the answer_sdp to the CALLER (not the answerer)
        """
        try:
            print(f"📨 Received call_answered event for user {self.user.username}")
            print(f"  - Call ID: {event['call_id']}")
            print(f"  - Answerer: {event['username']} ({event['user_id']})")
            print(f"  - Current user: {self.user.username} ({self.user.id})")
            print(f"  - Answer SDP: {'Present' if event.get('answer_sdp') else 'Missing'}")
            
            # ✅ CRITICAL: Only send to users who are NOT the answerer
            if event['user_id'] != str(self.user.id):
                await self.send(text_data=json.dumps({
                    'type': 'call_answered',
                    'call_id': event['call_id'],
                    'user_id': event['user_id'],
                    'username': event['username'],
                    'answer_sdp': event.get('answer_sdp', ''),  # ✅ MUST include
                }))
                print(f"✅ Sent call_answered to {self.user.username} (caller)")
            else:
                print(f"⏭️ Skipping - this user is the answerer")
                
        except Exception as e:
            print(f"❌ Error in call_answered handler: {str(e)}")
            import traceback
            print(traceback.format_exc())

    async def call_rejected(self, event):
        """Receive call rejection"""
        if event['user_id'] != str(self.user.id):
            await self.send(text_data=json.dumps({
                'type': 'call_rejected',
                'call_id': event['call_id'],
                'user_id': event['user_id'],
                'username': event['username']
            }))
    
    async def call_ended(self, event):
        """Receive call end"""
        await self.send(text_data=json.dumps({
            'type': 'call_ended',
            'call_id': event['call_id'],
            'user_id': event['user_id'],
            'username': event['username'],
            'duration': event.get('duration', 0)
        }))
    
    async def call_signal(self, event):
        """Receive WebRTC signal"""
        if event['from_user_id'] != str(self.user.id):
            await self.send(text_data=json.dumps({
                'type': 'call_signal',
                'call_id': event['call_id'],
                'from_user_id': event['from_user_id'],
                'signal': event['signal']
            }))
    
    async def ice_candidate(self, event):
        """
        Receive ICE candidate from channel layer and send to WebSocket client
        
        ✅ CRITICAL: Only send to OTHER users (not the sender)
        """
        try:
            from_user_id = event['from_user_id']
            current_user_id = str(self.user.id)
            
            print(f"📨 [ICE] Received for user: {self.user.username}")
            print(f"  - From: {event['from_username']} ({from_user_id})")
            print(f"  - Current: {self.user.username} ({current_user_id})")
            print(f"  - Candidate: {event['candidate'].get('candidate', 'N/A')[:60]}...")
            
            # ✅ Don't send ICE candidate back to sender
            if from_user_id != current_user_id:
                print(f"✅ [ICE] Forwarding to {self.user.username}")
                
                await self.send(text_data=json.dumps({
                    'type': 'ice_candidate',
                    'call_id': event['call_id'],
                    'from_user_id': from_user_id,
                    'from_username': event['from_username'],
                    'candidate': event['candidate'],
                }))
                
                print(f"✅ [ICE] Sent to {self.user.username}'s WebSocket")
            else:
                print(f"⏭️ [ICE] Skipping - this user is the sender")
                
        except Exception as e:
            print(f"❌ [ICE] Exception in ice_candidate: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    # ============ DATABASE OPERATIONS ============
    
    @database_sync_to_async
    def get_user(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            from django.contrib.auth.models import AnonymousUser
            return AnonymousUser()
    
    @database_sync_to_async
    def check_conversation_membership(self, conversation_id):
        from messaging.models import ConversationMember
        return ConversationMember.objects.filter(
            conversation_id=conversation_id,
            user=self.user,
            left_at__isnull=True
        ).exists()
    
    @database_sync_to_async
    def create_call(self, conversation_id, call_type, offer_sdp):
        """Create a new call in database - FIXED with better error handling"""
        from messaging.models import Call, CallParticipant, Conversation
        
        try:
            print(f"💾 [DB] Getting conversation {conversation_id}...")
            conversation = Conversation.objects.get(id=conversation_id)
            print(f"✅ [DB] Found conversation: {conversation.name}")
            
            # Check for active calls
            active_call = Call.objects.filter(
                conversation=conversation,
                status__in=['invited', 'ringing', 'answered']
            ).first()
            
            if active_call:
                print(f"⚠️ [DB] Active call already exists: {active_call.id}")
                return None
            
            # Create call
            print(f"💾 [DB] Creating call record...")
            call = Call.objects.create(
                conversation=conversation,
                caller=self.user,
                call_type=call_type,
                status='invited',
                offer_sdp=offer_sdp
            )
            print(f"✅ [DB] Call created: {call.id}")
            
            # Add participants
            print(f"💾 [DB] Adding participants...")
            members = conversation.members.filter(left_at__isnull=True)
            
            for member in members:
                is_caller = member.user == self.user
                participant = CallParticipant.objects.create(
                    call=call,
                    user=member.user,
                    status='joined' if is_caller else 'invited',
                    joined_at=timezone.now() if is_caller else None
                )
                print(f"✅ [DB] Added participant: {member.user.username} (status={participant.status})")
            
            print(f"✅ [DB] Call fully created")
            return {
                'id': call.id,
                'conversation_id': conversation_id,
                'call_type': call_type,
            }
            
        except Conversation.DoesNotExist:
            print(f"❌ [DB] Conversation not found: {conversation_id}")
            return None
        except Exception as e:
            print(f"❌ [DB] Error creating call: {str(e)}")
            import traceback
            print(f"❌ [DB] Traceback: {traceback.format_exc()}")
            return None
    
    @database_sync_to_async
    def answer_call(self, call_id, answer_sdp):
        """Update call in database when answered - FIXED"""
        from messaging.models import Call, CallParticipant
        
        try:
            print(f"💾 Updating call {call_id} in database...")
            
            call = Call.objects.get(id=call_id)
            
            # ✅ Update call
            call.answer_sdp = answer_sdp  # ✅ CRITICAL: Store the SDP
            call.status = 'answered'
            call.answered_at = timezone.now()
            call.save()
            
            print(f"✅ Call updated: status={call.status}")
            
            # ✅ Update participant
            participant = CallParticipant.objects.get(call=call, user=self.user)
            participant.status = 'joined'
            participant.joined_at = timezone.now()
            participant.save()
            
            print(f"✅ Participant updated: {self.user.username} -> joined")
            
            return True
            
        except Call.DoesNotExist:
            print(f"❌ Call not found: {call_id}")
            return False
        except Exception as e:
            print(f"❌ Error answering call: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return False
    
    @database_sync_to_async
    def reject_call(self, call_id):
        """
        Reject a call
        
        NOTIFICATION INTEGRATION:
        - Setting status='rejected' triggers post_save signal
        - Signal creates notification for caller
        """
        from messaging.models import Call, CallParticipant
        
        try:
            call = Call.objects.get(id=call_id)
            
            # Update call status
            call.status = 'rejected'
            call.save()
            
            # Update participant
            participant = CallParticipant.objects.get(call=call, user=self.user)
            participant.status = 'rejected'
            participant.save()
            
            print(f"✅ Call rejected - signal will create notification")
            return True
        except Exception as e:
            print(f"❌ Error rejecting call: {str(e)}")
            return False
    
    @database_sync_to_async
    def end_call(self, call_id):
        from messaging.models import Call, CallParticipant
        
        try:
            call = Call.objects.get(id=call_id)
            
            # End call
            call.status = 'ended'
            call.ended_at = timezone.now()
            call.save()
            
            # Calculate duration
            duration = call.calculate_duration()
            
            # Update all active participants
            for p in call.call_participants.filter(status='joined'):
                p.status = 'left'
                p.left_at = timezone.now()
                p.save()
            
            return {'duration': duration}
        except Exception as e:
            print(f"❌ Error ending call: {str(e)}")
            return None
        
    @database_sync_to_async
    def get_conversation_members(self, conversation_id):
        """Get all members of a conversation - FIXED"""
        from messaging.models import ConversationMember
        
        try:
            members = ConversationMember.objects.filter(
                conversation_id=conversation_id,
                left_at__isnull=True
            ).select_related('user')
            
            result = [
                {
                    'user_id': str(member.user.id),
                    'username': member.user.username
                }
                for member in members
            ]
            
            print(f"✅ [DB] Found {len(result)} members")
            return result
            
        except Exception as e:
            print(f"❌ [DB] Error getting members: {str(e)}")
            return []


# ============ NOTIFICATION OPERATIONS ============

class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time notifications
    
    This is the core of the notification delivery system.
    All notifications created via signals are sent through this consumer.
    """
    
    async def connect(self):
        # Get token from query string
        query_string = self.scope.get('query_string', b'').decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]
        
        if not token:
            await self.close(code=4001)
            return
        
        try:
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            self.user = await self.get_user(user_id)
        except Exception as e:
            print(f"❌ Notification token verification failed: {str(e)}")
            await self.close(code=4003)
            return
        
        # Join user's notification group
        self.room_group_name = f'notifications_{self.user.id}'
        
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Send connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'message': 'Connected to notifications',
            'user_id': str(self.user.id)
        }))
        
        print(f"✅ User {self.user.username} connected to notifications")
    
    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
        print(f"🔌 User disconnected from notifications")
    
    async def receive(self, text_data):
        """Handle incoming messages (e.g., mark as read)"""
        try:
            data = json.loads(text_data)
            action = data.get('action')
            
            if action == 'mark_read':
                notification_id = data.get('notification_id')
                await self.mark_notification_read(notification_id)
            
            elif action == 'ping':
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': str(timezone.now())
                }))
        
        except json.JSONDecodeError:
            pass
    
    async def notification_event(self, event):
        """
        Handle notification events from channel layer
        
        This is called when utils.send_realtime_notification() sends a notification
        """
        await self.send(text_data=json.dumps(event['data']))
    
    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        """Mark notification as read"""
        from notifications.models import Notification
        try:
            notification = Notification.objects.get(id=notification_id, recipient=self.user)
            notification.mark_as_read()
            print(f"✅ Notification {notification_id} marked as read")
        except Notification.DoesNotExist:
            pass
    
    @database_sync_to_async
    def get_user(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            from django.contrib.auth.models import AnonymousUser
            return AnonymousUser()
   
   
# ============ TEST OPERATIONS ============
    
class TestConsumer(AsyncWebsocketConsumer):
    """
    Simple WebSocket consumer for testing connectivity
    Useful for debugging WebSocket issues
    
    Usage:
    ws://localhost:8000/ws/test/?token=<jwt_token>
    
    Send: {"action": "ping", "message": "hello"}
    Receive: {"type": "pong", "message": "hello", "timestamp": "..."}
    """
    
    async def connect(self):
        print("🧪 Test WebSocket connection attempt")
        
        # Get token from query string
        query_string = self.scope.get('query_string', b'').decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]
        
        if not token:
            print("❌ No token provided for test connection")
            await self.close(code=4001)
            return
        
        try:
            # Verify token
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            self.user = await self.get_user(user_id)
            print(f"✅ Test connection verified for user: {self.user.username}")
        except Exception as e:
            print(f"❌ Test token verification failed: {str(e)}")
            await self.close(code=4003)
            return
        
        await self.accept()
        
        # Send welcome message
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'message': 'Test WebSocket connected successfully',
            'user_id': str(self.user.id),
            'username': self.user.username,
            'timestamp': str(timezone.now())
        }))
        
        print(f"✅ Test WebSocket connected for {self.user.username}")
    
    async def disconnect(self, close_code):
        print(f"🔌 Test WebSocket disconnected: {close_code}")
    
    async def receive(self, text_data):
        """Echo received messages back with timestamp"""
        try:
            data = json.loads(text_data)
            action = data.get('action', 'unknown')
            
            print(f"📨 Test WebSocket received: {action}")
            
            if action == 'ping':
                # Simple ping-pong
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'message': data.get('message', 'pong'),
                    'original_data': data,
                    'timestamp': str(timezone.now())
                }))
            
            elif action == 'echo':
                # Echo back the message
                await self.send(text_data=json.dumps({
                    'type': 'echo',
                    'data': data,
                    'timestamp': str(timezone.now())
                }))
            
            elif action == 'error_test':
                # Test error handling
                raise ValueError("This is a test error")
            
            else:
                # Unknown action
                await self.send(text_data=json.dumps({
                    'type': 'unknown_action',
                    'action': action,
                    'message': 'Unknown action received',
                    'timestamp': str(timezone.now())
                }))
        
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Invalid JSON format',
                'timestamp': str(timezone.now())
            }))
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': str(e),
                'timestamp': str(timezone.now())
            }))
    
    @database_sync_to_async
    def get_user(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            from django.contrib.auth.models import AnonymousUser
            return AnonymousUser()

 
 
               