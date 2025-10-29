import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken
from urllib.parse import parse_qs
# Import timezone
from django.utils import timezone

from messaging.services.presence_service import presence_service

User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for WhatsApp-like real-time chat"""
    
    async def connect(self):
        print(f"🔍 WebSocket connection attempt")
        
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
        
        # User-wide connection (no specific conversation)
        self.user_room_name = f'user_{self.user.id}'
        
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
            'username': self.user.username
        }))
        
        print(f"✅ User {self.user.username} connected successfully")

    async def disconnect(self, close_code):
        print(f"🔌 User {getattr(self, 'user', 'Unknown')} disconnecting...")
        
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
        
        print(f"✅ User disconnected")
    
    async def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(text_data)
            action = data.get('action')
            conversation_id = data.get('conversation_id')
            
            print(f"📨 Received: {action} for conversation {conversation_id}")
            
            # Route actions
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
                
            elif action == 'initiate_call' and conversation_id:
                await self.handle_initiate_call(str(conversation_id))
            elif action == 'answer_call' and conversation_id:
                await self.handle_answer_call(str(conversation_id))
            elif action == 'reject_call' and conversation_id:
                await self.handle_reject_call(str(conversation_id))
            elif action == 'end_call' and conversation_id:
                await self.handle_end_call(str(conversation_id))
            elif action == 'call_signal' and conversation_id:
                await self.handle_call_signal(str(conversation_id))
            elif action == 'ice_candidate' and conversation_id:
                await self.handle_ice_candidate(str(conversation_id))

                
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'error': f'Unknown action: {action}'
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
    
    # ============ ACTION HANDLERS ============
    
    async def handle_ping(self):
        """Handle ping/pong for connection keepalive"""
        # Refresh user presence
        await self.refresh_user_presence(str(self.user.id))
        
        await self.send(text_data=json.dumps({
            'type': 'pong',
            'timestamp': str(timezone.now())
        }))
    
    async def handle_send_message(self, data, conversation_id):
        """Handle sending a message"""
        message_content = data.get('message', '').strip()
        message_type = data.get('message_type', 'text')
        reply_to_id = data.get('reply_to')
        
        # Verify user is member
        is_member = await self.check_conversation_membership(conversation_id)
        if not is_member:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Not a member of this conversation'
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
                'error': 'Only admins can send messages in this group'
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
        message_obj = await self.save_message(conversation_id, message_content, message_type, reply_to_id)
        
        if message_obj:
            # Serialize the message - this returns a dict with all UUIDs as strings
            serialized_message = await self.serialize_message(message_obj)
            
            # Broadcast to conversation - MUST convert conversation_id to string
            await self.channel_layer.group_send(
                f'chat_{conversation_id}',
                {
                    'type': 'chat_message',
                    'message': serialized_message,
                    'conversation_id': str(conversation_id),  # ← FIX: Convert UUID to string
                }
            )
            
            # Send confirmation to sender
            await self.send(text_data=json.dumps({
                'type': 'message_sent',
                'message_id': str(message_obj.id),
                'conversation_id': str(conversation_id)  # ← FIX: Convert UUID to string
        }))

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
                'conversation_id': str(conversation_id)  # ← FIX
            }
        )

    async def handle_mark_read(self, data, conversation_id):
        """Mark specific message as read"""
        message_id = data.get('message_id')
        
        if not message_id:
            return
        
        is_member = await self.check_conversation_membership(conversation_id)
        if not is_member:
            return
        
        success = await self.mark_message_read(conversation_id, message_id)
        
        if success:
            # Broadcast read receipt to all members
            await self.channel_layer.group_send(
                f'chat_{conversation_id}',
                {
                    'type': 'message_read',
                    'message_id': str(message_id),  # ← FIX if message_id is UUID
                    'user_id': str(self.user.id),
                    'username': self.user.username,
                    'conversation_id': str(conversation_id)  # ← FIX
                }
            )
            
            # Send updated unread count
            unread_count = await self.get_user_unread_count(conversation_id)
            await self.send(text_data=json.dumps({
                'type': 'unread_count',
                'conversation_id': str(conversation_id),  # ← FIX
                'count': unread_count
            }))


    async def handle_mark_all_read(self, conversation_id):
        """Mark all messages as read"""
        marked_message_ids = await self.mark_all_messages_read(conversation_id)
        
        if marked_message_ids:
            # Broadcast to conversation
            await self.channel_layer.group_send(
                f'chat_{conversation_id}',
                {
                    'type': 'all_messages_read',
                    'user_id': str(self.user.id),
                    'username': self.user.username,
                    'conversation_id': str(conversation_id),
                    'marked_message_ids': marked_message_ids
                }
            )
    
    async def handle_mark_delivered(self, data, conversation_id):
        """Mark message as delivered"""
        message_id = data.get('message_id')
        
        if not message_id:
            return
        
        success = await self.mark_message_delivered(conversation_id, message_id)
        
        if success:
            # Broadcast delivery receipt
            await self.channel_layer.group_send(
                f'chat_{conversation_id}',
                {
                    'type': 'message_delivered',
                    'message_id': message_id,
                    'user_id': str(self.user.id),
                    'conversation_id': str(conversation_id)
                }
            )
    
    async def handle_react_to_message(self, data):
        """Add reaction to message"""
        message_id = data.get('message_id')
        emoji = data.get('emoji')
        
        if not message_id or not emoji:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'message_id and emoji are required'
            }))
            return
        
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
    
    async def handle_remove_reaction(self, data):
        """Remove reaction from message"""
        message_id = data.get('message_id')
        
        if not message_id:
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
    
    async def handle_delete_message(self, data):
        """Delete message"""
        message_id = data.get('message_id')
        delete_for_everyone = data.get('delete_for_everyone', False)
        
        if not message_id:
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
    
    async def handle_edit_message(self, data):
        """Edit message"""
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
        """Join a specific conversation group"""
        is_member = await self.check_conversation_membership(conversation_id)
        if not is_member:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Not a member of this conversation'
            }))
            return
        
        await self.channel_layer.group_add(
            f'chat_{conversation_id}',
            self.channel_name
        )
        
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
        
        await self.send(text_data=json.dumps({
            'type': 'conversation_joined',
            'conversation_id': str(conversation_id),
            'has_unread': has_unread
        }))
    
    async def handle_leave_conversation(self, conversation_id):
        """Leave a specific conversation group"""
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
            'conversation_id': str(conversation_id)
        }))
    
    # ============ CHANNEL LAYER EVENT HANDLERS ============
    
    async def chat_message(self, event):
        """Receive chat messages from group"""
        await self.send(text_data=json.dumps({
            'type': 'message',
            'data': event['message'],
            'conversation_id': event['conversation_id']
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
        await self.send(text_data=json.dumps({
            'type': 'all_read_receipt',
            'user_id': event['user_id'],
            'username': event['username'],
            'conversation_id': event['conversation_id'],
            'marked_message_ids': event.get('marked_message_ids', [])
        }))
    
    async def message_delivered(self, event):
        """Receive delivery receipts"""
        await self.send(text_data=json.dumps({
            'type': 'delivery_receipt',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'conversation_id': event['conversation_id']
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
                'conversation_id': event.get('conversation_id')
            }))
    
    async def conversation_updated(self, event):
        """Receive conversation updates"""
        await self.send(text_data=json.dumps({
            'type': 'conversation_updated',
            'conversation_id': event['conversation_id'],
            'data': event.get('data', {})
        }))

    async def handle_initiate_call(self, data):
        """Handle call initiation"""
        conversation_id = data.get('conversation_id')
        call_type = data.get('call_type')  # 'audio' or 'video'
        offer_sdp = data.get('offer_sdp', '')
        
        if not conversation_id or not call_type:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'conversation_id and call_type are required'
            }))
            return
        
        is_member = await self.check_conversation_membership(conversation_id)
        if not is_member:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Not a member of this conversation'
            }))
            return
        
        # Create call
        call = await self.create_call(conversation_id, call_type, offer_sdp)
        
        if call:
            # Broadcast to conversation members
            await self.channel_layer.group_send(
                f'chat_{conversation_id}',
                {
                    'type': 'call_initiated',
                    'call_id': str(call['id']),
                    'caller_id': str(self.user.id),
                    'caller_username': self.user.username,
                    'call_type': call_type,
                    'offer_sdp': offer_sdp,
                    'conversation_id': conversation_id
                }
            )
            
            await self.send(text_data=json.dumps({
                'type': 'call_created',
                'call_id': str(call['id']),
                'call_type': call_type,
                'status': 'initiated'
            }))
            
            print(f"✅ Call {call['id']} initiated by {self.user.username}")

    async def handle_answer_call(self, data):
        """Handle answering a call"""
        call_id = data.get('call_id')
        answer_sdp = data.get('answer_sdp', '')
        
        if not call_id:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'call_id is required'
            }))
            return
        
        result = await self.answer_call(call_id, answer_sdp)
        
        if result:
            # Notify all participants in the call
            await self.channel_layer.group_send(
                f'call_{call_id}',
                {
                    'type': 'call_answered',
                    'call_id': call_id,
                    'user_id': str(self.user.id),
                    'username': self.user.username,
                    'answer_sdp': answer_sdp
                }
            )
            
            await self.send(text_data=json.dumps({
                'type': 'call_answer_sent',
                'call_id': call_id,
                'status': 'answered'
            }))
            
            print(f"✅ Call {call_id} answered by {self.user.username}")
        else:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'Failed to answer call'
            }))

    async def handle_reject_call(self, data):
        """Handle rejecting a call"""
        call_id = data.get('call_id')
        
        if not call_id:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'call_id is required'
            }))
            return
        
        result = await self.reject_call(call_id)
        
        if result:
            # Notify caller
            await self.channel_layer.group_send(
                f'call_{call_id}',
                {
                    'type': 'call_rejected',
                    'call_id': call_id,
                    'user_id': str(self.user.id),
                    'username': self.user.username
                }
            )
            
            await self.send(text_data=json.dumps({
                'type': 'call_reject_sent',
                'call_id': call_id,
                'status': 'rejected'
            }))
            
            print(f"❌ Call {call_id} rejected by {self.user.username}")

    async def handle_end_call(self, data):
        """Handle ending a call"""
        call_id = data.get('call_id')
        
        if not call_id:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'call_id is required'
            }))
            return
        
        result = await self.end_call(call_id)
        
        if result:
            # Notify all participants
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
            
            await self.send(text_data=json.dumps({
                'type': 'call_end_sent',
                'call_id': call_id,
                'duration': result.get('duration', 0)
            }))
            
            print(f"🔴 Call {call_id} ended by {self.user.username}")

    async def handle_call_signal(self, data):
        """Handle WebRTC signaling (SDP offer/answer)"""
        call_id = data.get('call_id')
        signal_data = data.get('signal')
        target_user_id = data.get('target_user_id')
        
        if not call_id or not signal_data:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'call_id and signal are required'
            }))
            return
        
        # Forward signal to specific user or broadcast to call group
        if target_user_id:
            await self.channel_layer.group_send(
                f'user_{target_user_id}',
                {
                    'type': 'call_signal',
                    'call_id': call_id,
                    'from_user_id': str(self.user.id),
                    'signal': signal_data
                }
            )
        else:
            await self.channel_layer.group_send(
                f'call_{call_id}',
                {
                    'type': 'call_signal',
                    'call_id': call_id,
                    'from_user_id': str(self.user.id),
                    'signal': signal_data
                }
            )
        
        print(f"📡 WebRTC signal sent for call {call_id}")

    async def handle_ice_candidate(self, data):
        """Handle ICE candidate exchange"""
        call_id = data.get('call_id')
        candidate = data.get('candidate')
        target_user_id = data.get('target_user_id')
        
        if not call_id or not candidate:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'error': 'call_id and candidate are required'
            }))
            return
        
        # Save ICE candidate
        await self.save_ice_candidate(call_id, candidate)
        
        # Forward to target user if specified, otherwise broadcast
        if target_user_id:
            await self.channel_layer.group_send(
                f'user_{target_user_id}',
                {
                    'type': 'ice_candidate',
                    'call_id': call_id,
                    'from_user_id': str(self.user.id),
                    'candidate': candidate
                }
            )
        else:
            await self.channel_layer.group_send(
                f'call_{call_id}',
                {
                    'type': 'ice_candidate',
                    'call_id': call_id,
                    'from_user_id': str(self.user.id),
                    'candidate': candidate
                }
            )
        
        print(f"🧊 ICE candidate sent for call {call_id}")



    # ============ DATABASE OPERATIONS ============
    
    @database_sync_to_async
    def get_user(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return AnonymousUser()
    
    @database_sync_to_async
    def join_user_conversations(self):
        """Get list of conversation IDs user is member of"""
        from messaging.models import ConversationMember
        
        memberships = ConversationMember.objects.filter(
            user=self.user,
            left_at__isnull=True
        ).select_related('conversation')
        
        self.conversation_ids = [str(member.conversation_id) for member in memberships]
        
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
        from messaging.models import Message, Conversation, MessageRead
        from django.utils import timezone
        
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
            
            # Update conversation timestamp
            conversation.updated_at = timezone.now()
            conversation.save(update_fields=['updated_at'])
            
            return message
        except Exception as e:
            print(f"❌ Failed to save message: {str(e)}")
            return None
    
    @database_sync_to_async
    def serialize_message(self, message):
        """Serialize message for WebSocket transmission"""
        from messaging.serializers import MessageSerializer
        
        # Create serializer with context (important for URLs)
        serializer = MessageSerializer(message, context={
            'request': None  # No request context in WebSocket
        })
        
        # Get serialized data
        data = serializer.data
        
        # Ensure all UUIDs are strings (DRF should do this, but let's be explicit)
        def ensure_serializable(obj):
            """Recursively convert UUIDs to strings"""
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
        from messaging.models import Message, MessageRead
        from django.utils import timezone
        
        try:
            message = Message.objects.get(id=message_id, conversation_id=conversation_id)
            
            if message.sender == self.user:
                return False
            
            message_read, created = MessageRead.objects.get_or_create(
                message=message,
                user=self.user,
                defaults={'read_at': timezone.now()}
            )
            
            # Also mark as delivered
            message.delivered_to.add(self.user)
            
            return True
        except Exception as e:
            print(f"❌ Error marking message as read: {str(e)}")
            return False
    
    @database_sync_to_async
    def mark_all_messages_read(self, conversation_id):
        from messaging.models import Message, MessageRead
        from django.utils import timezone
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
            
            return [str(mid) for mid in message_ids]
        except Exception as e:
            print(f"❌ Error marking all as read: {str(e)}")
            return []
    
    @database_sync_to_async
    def mark_message_delivered(self, conversation_id, message_id):
        from messaging.models import Message
        
        try:
            message = Message.objects.get(id=message_id, conversation_id=conversation_id)
            
            if message.sender == self.user:
                return False
            
            message.delivered_to.add(self.user)
            return True
        except Exception as e:
            print(f"❌ Error marking as delivered: {str(e)}")
            return False
    
    @database_sync_to_async
    def add_reaction(self, message_id, emoji):
        from messaging.models import Message, MessageReaction
        from django.utils import timezone
        
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
            
            return {
                'conversation_id': str(message.conversation_id),
                'created': created
            }
        except Exception as e:
            print(f"❌ Error adding reaction: {str(e)}")
            return None
    
    @database_sync_to_async
    def remove_reaction(self, message_id):
        from messaging.models import Message, MessageReaction
        
        try:
            message = Message.objects.get(id=message_id)
            
            deleted_count, _ = MessageReaction.objects.filter(
                message=message,
                user=self.user
            ).delete()
            
            if deleted_count > 0:
                return {'conversation_id': str(message.conversation_id)}
            return None
        except Exception as e:
            print(f"❌ Error removing reaction: {str(e)}")
            return None
    
    @database_sync_to_async
    def delete_message(self, message_id, delete_for_everyone):
        from messaging.models import Message
        from django.utils import timezone
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

    
    # ============================================
    # STEP 4: ADD THESE DATABASE OPERATION METHODS
    # ============================================

    @database_sync_to_async
    def create_call(self, conversation_id, call_type, offer_sdp):
        from messaging.models import Call, CallParticipant, Conversation
        
        try:
            conversation = Conversation.objects.get(id=conversation_id)
            
            # Check if there's already an active call
            active_call = Call.objects.filter(
                conversation=conversation,
                status__in=['initiated', 'ringing', 'answered']
            ).first()
            
            if active_call:
                print(f"⚠️ Active call already exists for conversation {conversation_id}")
                return None
            
            # Create call
            call = Call.objects.create(
                conversation=conversation,
                caller=self.user,
                call_type=call_type,
                status='initiated',
                offer_sdp=offer_sdp
            )
            
            # Add caller as participant
            CallParticipant.objects.create(
                call=call,
                user=self.user,
                status='joined',
                joined_at=timezone.now()
            )
            
            # Add other members
            other_members = conversation.members.filter(
                left_at__isnull=True
            ).exclude(user=self.user)
            
            for member in other_members:
                CallParticipant.objects.create(
                    call=call,
                    user=member.user,
                    status='invited'
                )
            
            print(f"✅ Call created: {call.id}")
            
            return {
                'id': call.id,
                'conversation_id': str(conversation_id),
                'call_type': call_type
            }
        except Exception as e:
            print(f"❌ Error creating call: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    @database_sync_to_async
    def answer_call(self, call_id, answer_sdp):
        from messaging.models import Call
        
        try:
            call = Call.objects.get(id=call_id)
            
            # Update call
            call.answer_sdp = answer_sdp
            call.status = 'answered'
            call.answered_at = timezone.now()
            call.save()
            
            # Update participant
            participant = call.call_participants.get(user=self.user)
            participant.status = 'joined'
            participant.joined_at = timezone.now()
            participant.save()
            
            print(f"✅ Call answered: {call_id}")
            return True
        except Exception as e:
            print(f"❌ Error answering call: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    @database_sync_to_async
    def reject_call(self, call_id):
        from messaging.models import Call
        
        try:
            call = Call.objects.get(id=call_id)
            
            # Update call status
            call.status = 'rejected'
            call.save()
            
            # Update participant
            participant = call.call_participants.get(user=self.user)
            participant.status = 'rejected'
            participant.save()
            
            print(f"❌ Call rejected: {call_id}")
            return True
        except Exception as e:
            print(f"❌ Error rejecting call: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    @database_sync_to_async
    def end_call(self, call_id):
        from messaging.models import Call
        
        try:
            call = Call.objects.get(id=call_id)
            
            # End call
            call.status = 'ended'
            call.ended_at = timezone.now()
            duration = call.calculate_duration()
            call.save()
            
            # Update all active participants
            for p in call.call_participants.filter(status='joined'):
                p.status = 'left'
                p.left_at = timezone.now()
                p.save()
            
            print(f"🔴 Call ended: {call_id}, duration: {duration}s")
            return {'duration': duration}
        except Exception as e:
            print(f"❌ Error ending call: {str(e)}")
            import traceback
            traceback.print_exc()
            return None

    @database_sync_to_async
    def save_ice_candidate(self, call_id, candidate):
        from messaging.models import Call
        
        try:
            call = Call.objects.get(id=call_id)
            participant = call.call_participants.get(user=self.user)
            
            # Append ICE candidate
            if not participant.ice_candidates:
                participant.ice_candidates = []
            
            participant.ice_candidates.append(candidate)
            participant.save()
            
            print(f"🧊 ICE candidate saved for call {call_id}")
            return True
        except Exception as e:
            print(f"❌ Error saving ICE candidate: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


 
 
 
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






class NotificationConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time notifications"""
    
    async def connect(self):
        self.user = self.scope['user']
        
        if self.user.is_anonymous:
            await self.close()
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
            'message': 'Connected to notifications'
        }))
    
    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """Handle incoming messages (e.g., mark as read)"""
        try:
            data = json.loads(text_data)
            action = data.get('action')
            
            if action == 'mark_read':
                notification_id = data.get('notification_id')
                await self.mark_notification_read(notification_id)
        
        except json.JSONDecodeError:
            pass
    
    async def notification_event(self, event):
        """Handle notification events from channel layer"""
        await self.send(text_data=json.dumps(event['data']))
    
    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        """Mark notification as read"""
        from notifications.models import Notification
        try:
            notification = Notification.objects.get(id=notification_id, recipient=self.user)
            notification.mark_as_read()
        except Notification.DoesNotExist:
            pass

class TestConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print("🔍 TestConsumer connection attempt")
        await self.accept()
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'message': 'Test connection successful!'
        }))
        print("✅ TestConsumer connection successful")

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



        