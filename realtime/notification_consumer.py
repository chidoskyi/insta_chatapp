import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone



class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time messaging"""
    
    async def connect(self):
        self.user = self.scope['user']
        
        if self.user.is_anonymous:
            await self.close()
            return
        
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.room_group_name = f'chat_{self.conversation_id}'
        
        # Verify user is a member of this conversation
        is_member = await self.check_membership()
        if not is_member:
            await self.close()
            return
        
        # Join conversation group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Send connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'message': f'Connected to conversation {self.conversation_id}'
        }))
        
        # Notify others that user is online
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'user_status',
                'user_id': self.user.id,
                'username': self.user.username,
                'status': 'online'
            }
        )
    
    async def disconnect(self, close_code):
        # Notify others that user is offline
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_status',
                    'user_id': self.user.id,
                    'username': self.user.username,
                    'status': 'offline'
                }
            )
            
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """Handle incoming messages"""
        try:
            data = json.loads(text_data)
            action = data.get('action')
            
            if action == 'send_message':
                message = data.get('message')
                reply_to_id = data.get('reply_to')
                
                # Save message to database
                message_obj = await self.save_message(message, reply_to_id)
                
                # Broadcast message to all members
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'message': await self.serialize_message(message_obj)
                    }
                )
            
            elif action == 'typing':
                # Broadcast typing indicator
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'typing_indicator',
                        'user_id': self.user.id,
                        'username': self.user.username,
                        'is_typing': data.get('is_typing', True)
                    }
                )
            
            elif action == 'mark_read':
                message_id = data.get('message_id')
                await self.mark_message_read(message_id)
                
                # Notify sender
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'message_read',
                        'message_id': message_id,
                        'user_id': self.user.id,
                        'username': self.user.username
                    }
                )
        
        except json.JSONDecodeError:
            pass
    
    async def chat_message(self, event):
        """Handle chat message events"""
        await self.send(text_data=json.dumps({
            'type': 'message',
            'data': event['message']
        }))
    
    async def typing_indicator(self, event):
        """Handle typing indicator events"""
        # Don't send typing indicator back to sender
        if event['user_id'] != self.user.id:
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'user_id': event['user_id'],
                'username': event['username'],
                'is_typing': event['is_typing']
            }))
    
    async def user_status(self, event):
        """Handle user status events"""
        # Don't send own status back
        if event['user_id'] != self.user.id:
            await self.send(text_data=json.dumps({
                'type': 'user_status',
                'user_id': event['user_id'],
                'username': event['username'],
                'status': event['status']
            }))
    
    async def message_read(self, event):
        """Handle message read events"""
        await self.send(text_data=json.dumps({
            'type': 'read_receipt',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'username': event['username']
        }))
    
    @database_sync_to_async
    def check_membership(self):
        """Check if user is a member of the conversation"""
        from messaging.models import ConversationMember
        return ConversationMember.objects.filter(
            conversation_id=self.conversation_id,
            user=self.user,
            left_at__isnull=True
        ).exists()
    
    @database_sync_to_async
    def save_message(self, body, reply_to_id=None):
        """Save message to database"""
        from messaging.models import Message, MessageRead, Conversation
        
        conversation = Conversation.objects.get(id=self.conversation_id)
        
        message = Message.objects.create(
            conversation=conversation,
            sender=self.user,
            body=body,
            reply_to_id=reply_to_id
        )
        
        # Mark as read by sender
        MessageRead.objects.create(message=message, user=self.user)
        
        return message
    
    @database_sync_to_async
    def serialize_message(self, message):
        """Serialize message object"""
        from messaging.serializers import MessageSerializer
        serializer = MessageSerializer(message)
        return serializer.data
    
    @database_sync_to_async
    def mark_message_read(self, message_id):
        """Mark message as read"""
        from messaging.models import Message, MessageRead
        
        try:
            message = Message.objects.get(id=message_id, conversation_id=self.conversation_id)
            MessageRead.objects.get_or_create(message=message, user=self.user)
        except Message.DoesNotExist:
            pass


class PostConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time post updates (likes, comments)"""
    
    async def connect(self):
        self.user = self.scope['user']
        
        if self.user.is_anonymous:
            await self.close()
            return
        
        self.post_id = self.scope['url_route']['kwargs']['post_id']
        self.room_group_name = f'post_{self.post_id}'
        
        # Join post group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
    
    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """Handle incoming events"""
        pass  # Post updates are sent from backend, not from client
    
    async def post_like(self, event):
        """Handle post like events"""
        await self.send(text_data=json.dumps({
            'type': 'like',
            'data': event['data']
        }))
    
    async def post_comment(self, event):
        """Handle new comment events"""
        await self.send(text_data=json.dumps({
            'type': 'comment',
            'data': event['data']
        }))
    
    async def post_update(self, event):
        """Handle post update events"""
        await self.send(text_data=json.dumps({
            'type': 'update',
            'data': event['data']
        }))