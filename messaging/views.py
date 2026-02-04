from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import secrets
from mutagen import File as MutagenFile
import tempfile
import os
import requests
import subprocess
from mutagen.mp3 import MP3
from mutagen.wave import WAVE

from .pagination import *
from .models import (
    Call, CallParticipant, Conversation, ConversationMember, Message, MessageRead,
    MessageReaction, StarredMessage, BlockedUser, GroupInviteLink
)
from .serializers import (
    CallAnswerSerializer, CallInitiateSerializer, CallSerializer, CallUpdateSerializer, ConversationSerializer, ConversationListSerializer, ConversationCreateSerializer,
    MessageSerializer, MessageCreateSerializer, MessageReactionSerializer,
    StarredMessageSerializer, BlockedUserSerializer, GroupInviteLinkSerializer
)

User = get_user_model()


class ConversationListCreateView(generics.ListCreateAPIView):   
    """List conversations or create a new conversation"""
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CustomCursorPagination
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ConversationCreateSerializer
        return ConversationListSerializer
    
    def get_queryset(self):
        user = self.request.user
        show_archived = self.request.query_params.get('archived', 'false').lower() == 'true'
        
        # Get conversations where user is an active member
        conversation_ids = ConversationMember.objects.filter(
            user=user,
            left_at__isnull=True,
            is_archived=show_archived
        ).values_list('conversation_id', flat=True)
        
        # Get pinned conversation IDs
        pinned_ids = ConversationMember.objects.filter(
            user=user,
            conversation_id__in=conversation_ids,
            is_pinned=True
        ).values_list('conversation_id', flat=True)
        
        # Use database ordering with Case/When for pinned first
        from django.db.models import Case, When, BooleanField
        
        queryset = Conversation.objects.filter(
            id__in=conversation_ids
        ).prefetch_related('members__user', 'messages').annotate(
            is_pinned=Case(
                When(id__in=pinned_ids, then=True),
                default=False,
                output_field=BooleanField()
            )
        ).order_by('-is_pinned', '-updated_at')  # Pinned first, then by update time
        
        return queryset
    

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        conversation_type = serializer.validated_data['type']
        user_ids = serializer.validated_data['user_ids']
        name = serializer.validated_data.get('name', '')
        description = serializer.validated_data.get('description', '')
        icon = request.FILES.get('icon')
        
        # Check if any user is blocked
        blocked_users = BlockedUser.objects.filter(
            Q(blocker=request.user, blocked_id__in=user_ids) |
            Q(blocked=request.user, blocker_id__in=user_ids)
        )
        if blocked_users.exists():
            return Response(
                {'error': 'Cannot create conversation with blocked users'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # For direct messages, check if conversation already exists
        if conversation_type == 'direct':
            other_user_id = user_ids[0]
            existing = self._find_existing_dm(request.user, other_user_id)
            if existing:
                return Response(
                    ConversationSerializer(existing, context={'request': request}).data,
                    status=status.HTTP_200_OK
                )
        
        # Create new conversation
        conversation = Conversation.objects.create(
            type=conversation_type,
            name=name,
            description=description,
            icon=icon,
            created_by=request.user
        )
        
        # Add creator as member
        ConversationMember.objects.create(
            conversation=conversation,
            user=request.user,
            is_admin=True
        )
        
        # Add other members
        for user_id in user_ids:
            user = User.objects.get(id=user_id)
            ConversationMember.objects.create(
                conversation=conversation,
                user=user,
                is_admin=False
            )
        
        return Response(
            ConversationSerializer(conversation, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )
    
    def _find_existing_dm(self, user1, user2_id):
        """Find existing DM between two users"""
        user2 = User.objects.get(id=user2_id)
        
        user1_conversations = set(
            ConversationMember.objects.filter(user=user1, left_at__isnull=True)
            .values_list('conversation_id', flat=True)
        )
        user2_conversations = set(
            ConversationMember.objects.filter(user=user2, left_at__isnull=True)
            .values_list('conversation_id', flat=True)
        )
        
        common = user1_conversations & user2_conversations
        
        if common:
            for conv_id in common:
                conv = Conversation.objects.get(id=conv_id)
                if conv.type == 'direct':
                    return conv
        
        return None


class ConversationDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update or delete a conversation"""
    serializer_class = ConversationSerializer
    pagination_class = CustomCursorPagination
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_queryset(self):
        user = self.request.user
        conversation_ids = ConversationMember.objects.filter(
            user=user,
            left_at__isnull=True
        ).values_list('conversation_id', flat=True)
        
        return Conversation.objects.filter(id__in=conversation_ids)
    
    def update(self, request, *args, **kwargs):
        conversation = self.get_object()
        
        if conversation.type != 'group':
            return Response(
                {'error': 'Only group chats can be updated'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        member = conversation.members.get(user=request.user)
        if not member.is_admin:
            return Response(
                {'error': 'Only admins can update the conversation'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return super().update(request, *args, **kwargs)
    
    def destroy(self, request, *args, **kwargs):
        conversation = self.get_object()
        member = conversation.members.get(user=request.user)
        
        member.left_at = timezone.now()
        member.save()
        
        return Response({'message': 'Left conversation'})


class ConversationMessagesView(generics.ListCreateAPIView):
    """List messages in a conversation or send a new message"""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = MessageCursorPagination
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return MessageCreateSerializer
        return MessageSerializer
    
    def get_queryset(self):
        conversation_id = self.kwargs.get('conversation_id')
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        
        if not conversation.members.filter(user=self.request.user, left_at__isnull=True).exists():
            return Message.objects.none()
        
        # Filter options
        message_type = self.request.query_params.get('type')
        starred_only = self.request.query_params.get('starred', 'false').lower() == 'true'
        search_query = self.request.query_params.get('search')
        
        queryset = Message.objects.filter(
            conversation=conversation,
            deleted_for_everyone=False
        ).select_related('sender', 'reply_to').prefetch_related('read_by__user', 'reactions__user').order_by('created_at')
        
        if message_type:
            queryset = queryset.filter(message_type=message_type)
        
        if starred_only:
            starred_message_ids = StarredMessage.objects.filter(
                user=self.request.user,
                message__conversation=conversation
            ).values_list('message_id', flat=True)
            queryset = queryset.filter(id__in=starred_message_ids)
        
        if search_query:
            queryset = queryset.filter(body__icontains=search_query)
        
        return queryset
    
    def create(self, request, *args, **kwargs):
        conversation_id = self.kwargs.get('conversation_id')
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        
        member = conversation.members.filter(user=request.user, left_at__isnull=True).first()
        if not member:
            return Response(
                {'error': 'You are not a member of this conversation'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if conversation.only_admins_can_send and not member.is_admin:
            return Response(
                {'error': 'Only admins can send messages in this group'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        media_file = request.FILES.get('media_file')
        message_type = serializer.validated_data.get('message_type', 'text')
        
        # 🔥 AUDIO CONVERSION USING FFMPEG (No pydub needed)
        media_duration = None
        media_size = None
        
        if media_file:
            media_size = media_file.size
            
            # 🔥 Convert audio files to MP3 using ffmpeg
            if message_type == 'audio':
                try:
                    print(f"🎵 Processing audio file: {media_file.name}")
                    
                    # Save uploaded file temporarily
                    suffix = os.path.splitext(media_file.name)[1]
                    
                    # 🔥 FIX: Create input temp file
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_input:
                        for chunk in media_file.chunks():
                            tmp_input.write(chunk)
                        tmp_input_path = tmp_input.name
                    
                    # 🔥 FIX: Create OUTPUT temp file with DIFFERENT name
                    tmp_output = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
                    tmp_output.close()  # Close it so ffmpeg can write to it
                    tmp_output_path = tmp_output.name
                    
                    print(f"📁 Input: {tmp_input_path}")
                    print(f"📁 Output: {tmp_output_path}")
                    
                    try:
                        # Convert to MP3 using ffmpeg
                        command = [
                            'ffmpeg',
                            '-i', tmp_input_path,  # Input file
                            '-acodec', 'libmp3lame',  # MP3 codec
                            '-b:a', '128k',  # Bitrate
                            '-ar', '44100',  # Sample rate
                            '-y',  # Overwrite output file
                            tmp_output_path  # Output file (DIFFERENT from input)
                        ]
                        
                        print(f"🎬 Running: {' '.join(command)}")
                        
                        result = subprocess.run(
                            command,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=30
                        )
                        
                        if result.returncode != 0:
                            error_msg = result.stderr.decode()
                            print(f"❌ FFmpeg error output:\n{error_msg}")
                            raise Exception(f"FFmpeg failed with code {result.returncode}")
                        
                        print("✅ FFmpeg conversion successful")
                        
                        # Get duration using ffprobe
                        duration_command = [
                            'ffprobe',
                            '-v', 'error',
                            '-show_entries', 'format=duration',
                            '-of', 'default=noprint_wrappers=1:nokey=1',
                            tmp_output_path  # Use output file
                        ]
                        
                        duration_result = subprocess.run(
                            duration_command,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=10
                        )
                        
                        if duration_result.returncode == 0:
                            duration_str = duration_result.stdout.decode().strip()
                            media_duration = int(float(duration_str))
                            print(f"✅ Audio converted to MP3, duration: {media_duration}s")
                        else:
                            print(f"⚠️ Could not get duration: {duration_result.stderr.decode()}")
                            media_duration = 10  # Default
                        
                        # Read the converted file
                        with open(tmp_output_path, 'rb') as f:
                            from django.core.files.uploadedfile import InMemoryUploadedFile
                            import io
                            
                            mp3_data = f.read()
                            media_size = len(mp3_data)
                            
                            print(f"📦 Converted file size: {media_size} bytes")
                            
                            # Create new file object
                            converted_file = InMemoryUploadedFile(
                                io.BytesIO(mp3_data),
                                'media',
                                f'voice-note-{int(timezone.now().timestamp())}.mp3',
                                'audio/mpeg',  # 🔥 Use correct MIME type
                                media_size,
                                None
                            )
                        
                        # Clean up temp files
                        try:
                            os.unlink(tmp_input_path)
                            print(f"🧹 Cleaned up input: {tmp_input_path}")
                        except:
                            pass
                        
                        try:
                            os.unlink(tmp_output_path)
                            print(f"🧹 Cleaned up output: {tmp_output_path}")
                        except:
                            pass
                        
                        # Use converted file
                        media_file = converted_file
                        print("✅ Audio conversion complete!")
                        
                    except subprocess.TimeoutExpired:
                        print("⚠️ FFmpeg timeout")
                        # Clean up
                        try:
                            os.unlink(tmp_input_path)
                        except:
                            pass
                        try:
                            os.unlink(tmp_output_path)
                        except:
                            pass
                        media_duration = 15
                        
                    except Exception as e:
                        print(f"⚠️ Audio conversion failed: {e}")
                        import traceback
                        traceback.print_exc()
                        
                        # Clean up
                        try:
                            os.unlink(tmp_input_path)
                        except:
                            pass
                        try:
                            os.unlink(tmp_output_path)
                        except:
                            pass
                        
                        # Fallback: Use original file with duration guess
                        media_file.seek(0)
                        media_duration = 10  # Default guess
                            
                except Exception as e:
                    print(f"❌ Error processing audio: {e}")
                    import traceback
                    traceback.print_exc()
                    media_duration = 15
            
            # Video duration (no conversion)
            elif message_type == 'video':
                try:
                    suffix = os.path.splitext(media_file.name)[1]
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        for chunk in media_file.chunks():
                            tmp.write(chunk)
                        tmp_path = tmp.name
                    
                    media_file.seek(0)
                    
                    # Use ffprobe for video duration
                    duration_command = [
                        'ffprobe',
                        '-v', 'error',
                        '-show_entries', 'format=duration',
                        '-of', 'default=noprint_wrappers=1:nokey=1',
                        tmp_path
                    ]
                    
                    duration_result = subprocess.run(
                        duration_command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=10
                    )
                    
                    if duration_result.returncode == 0:
                        media_duration = int(float(duration_result.stdout.decode().strip()))
                        print(f"✅ Video duration: {media_duration}s")
                    
                    os.unlink(tmp_path)
                except Exception as e:
                    print(f"❌ Error calculating video duration: {e}")
                    media_duration = 0
        
        # Create message
        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            body=serializer.validated_data.get('body', ''),
            message_type=message_type,
            media=media_file,
            media_duration=media_duration,
            media_size=media_size,
            reply_to=serializer.validated_data.get('reply_to'),
            location_latitude=serializer.validated_data.get('location_latitude'),
            location_longitude=serializer.validated_data.get('location_longitude'),
            location_name=serializer.validated_data.get('location_name', '')
        )
        
        # Mark as read by sender
        MessageRead.objects.create(message=message, user=request.user)
        
        # Add sender to delivered_to
        message.delivered_to.add(request.user)
        
        # Mark conversation as read for sender
        member.mark_as_read()
        
        # Broadcast via WebSocket
        channel_layer = get_channel_layer()
        serialized_message = MessageSerializer(message, context={'request': request}).data
        
        # Convert to serializable
        def convert_to_serializable(obj):
            if isinstance(obj, dict):
                return {key: convert_to_serializable(value) for key, value in obj.items()}
            elif isinstance(obj, list):
                return [convert_to_serializable(item) for item in obj]
            elif isinstance(obj, tuple):
                return tuple(convert_to_serializable(item) for item in obj)
            elif hasattr(obj, 'isoformat'):
                return obj.isoformat()
            elif hasattr(obj, '__str__') and hasattr(obj, 'hex'):
                return str(obj)
            elif isinstance(obj, (int, float, bool, str)) or obj is None:
                return obj
            else:
                return str(obj)
        
        safe_serialized_message = convert_to_serializable(serialized_message)
        
        async_to_sync(channel_layer.group_send)(
            f'chat_{conversation_id}',
            {
                'type': 'chat_message',
                'message': safe_serialized_message,
                'conversation_id': str(conversation_id),
                'sender_id': str(request.user.id)
            }
        )
        
        print(f"✅ [API] Media message broadcast to chat_{conversation_id}")
        
        return Response(
            MessageSerializer(message, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )

class MessageDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update or delete a message"""
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Message.objects.filter(sender=self.request.user)
    
    def update(self, request, *args, **kwargs):
        message = self.get_object()
        
        if 'body' in request.data:
            message.body = request.data['body']
            message.is_edited = True
            message.save()
        
        serializer = self.get_serializer(message)
        return Response(serializer.data)
    
    def destroy(self, request, *args, **kwargs):
        message = self.get_object()
        delete_for_everyone = request.query_params.get('for_everyone', 'false').lower() == 'true'
        
        if delete_for_everyone:
            # Check if message is less than 1 hour old (WhatsApp rule)
            from datetime import timedelta
            if timezone.now() - message.created_at > timedelta(hours=1):
                return Response(
                    {'error': 'Can only delete for everyone within 1 hour of sending'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            message.deleted_for_everyone = True
            message.body = "This message was deleted"
        
        message.is_deleted = True
        message.deleted_at = timezone.now()
        message.save()
        
        return Response({'message': 'Message deleted'})


class ForwardMessageView(APIView):
    """Forward a message to other conversations"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, message_id):
        original_message = get_object_or_404(Message, id=message_id)
        conversation_ids = request.data.get('conversation_ids', [])
        
        if not conversation_ids:
            return Response(
                {'error': 'conversation_ids is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify user is member of source conversation
        if not original_message.conversation.members.filter(
            user=request.user, left_at__isnull=True
        ).exists():
            return Response(
                {'error': 'You are not a member of the source conversation'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        forwarded_messages = []
        
        for conv_id in conversation_ids:
            conversation = get_object_or_404(Conversation, id=conv_id)
            
            # Verify user is member
            member = conversation.members.filter(user=request.user, left_at__isnull=True).first()
            if not member:
                continue
            
            # Create forwarded message
            new_message = Message.objects.create(
                conversation=conversation,
                sender=request.user,
                body=original_message.body,
                message_type=original_message.message_type,
                media=original_message.media,
                forwarded_from=original_message,
                location_latitude=original_message.location_latitude,
                location_longitude=original_message.location_longitude,
                location_name=original_message.location_name
            )
            
            # Mark as read and delivered by sender
            MessageRead.objects.create(message=new_message, user=request.user)
            new_message.delivered_to.add(request.user)
            
            # Update forward count
            original_message.forward_count += 1
            
            forwarded_messages.append(new_message)
        
        # Save original message with updated forward count
        original_message.save()
        
        return Response({
            'message': f'Forwarded to {len(forwarded_messages)} conversations',
            'forwarded_count': len(forwarded_messages)
        })


class MarkConversationReadView(APIView):
    """Mark all messages in a conversation as read"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        
        member = conversation.members.filter(user=request.user, left_at__isnull=True).first()
        if not member:
            return Response(
                {'error': 'You are not a member of this conversation'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Mark as read
        member.mark_as_read()
        
        # Mark all unread messages as read and delivered
        unread_messages = conversation.messages.exclude(sender=request.user).filter(
            deleted_for_everyone=False
        )
        if member.last_read_at:
            unread_messages = unread_messages.filter(created_at__gt=member.last_read_at)
        
        for message in unread_messages:
            MessageRead.objects.get_or_create(message=message, user=request.user)
            message.delivered_to.add(request.user)
        
        return Response({'message': 'Conversation marked as read'})

class AddMemberView(APIView):
    """Add a member to a group chat"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        
        if conversation.type != 'group':
            return Response(
                {'error': 'Can only add members to group chats'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        member = conversation.members.filter(user=request.user, is_admin=True, left_at__isnull=True).first()
        if not member:
            return Response(
                {'error': 'Only admins can add members'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user_id = request.data.get('user_id')
        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        new_user = get_object_or_404(User, pk=user_id)
        
        # Check if blocked
        if BlockedUser.objects.filter(
            Q(blocker=request.user, blocked=new_user) |
            Q(blocker=new_user, blocked=request.user)
        ).exists():
            return Response(
                {'error': 'Cannot add blocked user'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if conversation.members.filter(user=new_user, left_at__isnull=True).exists():
            return Response(
                {'error': 'User is already a member'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        ConversationMember.objects.create(
            conversation=conversation,
            user=new_user
        )
        
        return Response({'message': f'{new_user.username} added to conversation'})


class RemoveMemberView(APIView):
    """Remove a member from a group chat"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        
        if conversation.type != 'group':
            return Response(
                {'error': 'Can only remove members from group chats'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        admin_member = conversation.members.filter(user=request.user, is_admin=True, left_at__isnull=True).first()
        if not admin_member:
            return Response(
                {'error': 'Only admins can remove members'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user_id = request.data.get('user_id')
        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        member_to_remove = conversation.members.filter(user_id=user_id, left_at__isnull=True).first()
        if not member_to_remove:
            return Response(
                {'error': 'User is not a member'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        member_to_remove.left_at = timezone.now()
        member_to_remove.save()
        
        return Response({'message': 'Member removed from conversation'})


class PromoteMemberView(APIView):
    """Promote a member to admin"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        
        if conversation.type != 'group':
            return Response(
                {'error': 'Can only promote members in group chats'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        admin_member = conversation.members.filter(user=request.user, is_admin=True, left_at__isnull=True).first()
        if not admin_member:
            return Response(
                {'error': 'Only admins can promote members'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user_id = request.data.get('user_id')
        member_to_promote = conversation.members.filter(user_id=user_id, left_at__isnull=True).first()
        
        if not member_to_promote:
            return Response(
                {'error': 'User is not a member'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        member_to_promote.is_admin = True
        member_to_promote.save()
        
        return Response({'message': 'Member promoted to admin'})


class DemoteMemberView(APIView):
    """Demote an admin to regular member"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        
        if conversation.type != 'group':
            return Response(
                {'error': 'Can only demote members in group chats'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        admin_member = conversation.members.filter(user=request.user, is_admin=True, left_at__isnull=True).first()
        if not admin_member:
            return Response(
                {'error': 'Only admins can demote members'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        user_id = request.data.get('user_id')
        member_to_demote = conversation.members.filter(user_id=user_id, left_at__isnull=True).first()
        
        if not member_to_demote:
            return Response(
                {'error': 'User is not a member'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        member_to_demote.is_admin = False
        member_to_demote.save()
        
        return Response({'message': 'Member demoted to regular user'})

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def unread_conversations_count(request):
    """Get count of conversations with unread messages"""
    user = request.user
    memberships = ConversationMember.objects.filter(
        user=user,
        left_at__isnull=True,
        is_archived=False
    )
    
    unread_count = 0
    for membership in memberships:
        if membership.get_unread_count() > 0:
            unread_count += 1
    
    return Response({'unread_conversations': unread_count})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def search_messages(request):
    """Search messages across all conversations"""
    query = request.query_params.get('q', '')
    
    if not query:
        return Response({'error': 'Search query is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Get user's conversations
    conversation_ids = ConversationMember.objects.filter(
        user=request.user,
        left_at__isnull=True
    ).values_list('conversation_id', flat=True)
    
    # Search messages
    messages = Message.objects.filter(
        conversation_id__in=conversation_ids,
        body__icontains=query,
        deleted_for_everyone=False
    ).select_related('sender', 'conversation').order_by('-created_at')[:50]
    
    serializer = MessageSerializer(messages, many=True, context={'request': request})
    return Response({
        'query': query,
        'results': serializer.data,
        'count': len(serializer.data)
    })

class CreateGroupInviteLinkView(APIView):
    """Create an invite link for a group"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        
        if conversation.type != 'group':
            return Response(
                {'error': 'Can only create invite links for group chats'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        member = conversation.members.filter(user=request.user, is_admin=True, left_at__isnull=True).first()
        if not member:
            return Response(
                {'error': 'Only admins can create invite links'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Generate unique code
        code = secrets.token_urlsafe(16)
        
        invite_link = GroupInviteLink.objects.create(
            conversation=conversation,
            created_by=request.user,
            code=code,
            expires_at=request.data.get('expires_at'),
            max_uses=request.data.get('max_uses')
        )
        
        serializer = GroupInviteLinkSerializer(invite_link, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class RevokeGroupInviteLinkView(APIView):
    """Revoke an invite link"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, conversation_id, link_id):
        conversation = get_object_or_404(Conversation, pk=conversation_id)
        invite_link = get_object_or_404(GroupInviteLink, pk=link_id, conversation=conversation)
        
        member = conversation.members.filter(user=request.user, is_admin=True, left_at__isnull=True).first()
        if not member:
            return Response(
                {'error': 'Only admins can revoke invite links'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        invite_link.is_active = False
        invite_link.save()
        
        return Response({'message': 'Invite link revoked'})

class JoinGroupViaInviteView(APIView):
    """Join a group using invite code"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, invite_code):
        invite_link = get_object_or_404(GroupInviteLink, code=invite_code)
        
        if not invite_link.is_valid():
            return Response(
                {'error': 'Invite link is invalid or expired'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        conversation = invite_link.conversation
        
        # Check if already a member
        if conversation.members.filter(user=request.user, left_at__isnull=True).exists():
            return Response(
                {'error': 'You are already a member of this group'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if blocked
        admin_ids = conversation.members.filter(is_admin=True).values_list('user_id', flat=True)
        if BlockedUser.objects.filter(
            Q(blocker=request.user, blocked_id__in=admin_ids) |
            Q(blocker_id__in=admin_ids, blocked=request.user)
        ).exists():
            return Response(
                {'error': 'Cannot join this group'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Add member
        ConversationMember.objects.create(
            conversation=conversation,
            user=request.user
        )
        
        # Increment use count
        invite_link.use_count += 1
        invite_link.save()
        
        return Response({
            'message': f'Joined {conversation.name}',
            'conversation': ConversationSerializer(conversation, context={'request': request}).data
        })


class MessageReactionView(APIView):
    """Add or remove reaction to a message"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, message_id):
        message = get_object_or_404(Message, id=message_id)
        emoji = request.data.get('emoji')
        
        if not emoji:
            return Response(
                {'error': 'emoji is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify user is member of conversation
        if not message.conversation.members.filter(
            user=request.user, left_at__isnull=True
        ).exists():
            return Response(
                {'error': 'You are not a member of this conversation'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Create or update reaction
        reaction, created = MessageReaction.objects.update_or_create(
            message=message,
            user=request.user,
            defaults={'emoji': emoji}
        )
        
        serializer = MessageReactionSerializer(reaction)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    
    def delete(self, request, message_id):
        message = get_object_or_404(Message, id=message_id)
        
        # Delete reaction
        deleted_count, _ = MessageReaction.objects.filter(
            message=message,
            user=request.user
        ).delete()
        
        if deleted_count > 0:
            return Response({'message': 'Reaction removed'})
        else:
            return Response(
                {'error': 'No reaction found'},
                status=status.HTTP_404_NOT_FOUND
            )


class StarMessageView(APIView):
    """Star or unstar a message"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, message_id):
        message = get_object_or_404(Message, id=message_id)
        
        # Verify user is member of conversation
        if not message.conversation.members.filter(
            user=request.user, left_at__isnull=True
        ).exists():
            return Response(
                {'error': 'You are not a member of this conversation'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        starred, created = StarredMessage.objects.get_or_create(
            user=request.user,
            message=message
        )
        
        if created:
            return Response({'message': 'Message starred'}, status=status.HTTP_201_CREATED)
        else:
            return Response({'message': 'Message already starred'}, status=status.HTTP_200_OK)
    
    def delete(self, request, message_id):
        message = get_object_or_404(Message, id=message_id)
        
        deleted_count, _ = StarredMessage.objects.filter(
            user=request.user,
            message=message
        ).delete()
        
        if deleted_count > 0:
            return Response({'message': 'Message unstarred'})
        else:
            return Response(
                {'error': 'Message not starred'},
                status=status.HTTP_404_NOT_FOUND
            )


class StarredMessagesListView(generics.ListAPIView):
    """List all starred messages for current user"""
    serializer_class = StarredMessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CustomCursorPagination
    
    def get_queryset(self):
        conversation_id = self.request.query_params.get('conversation_id')
        
        queryset = StarredMessage.objects.filter(
            user=self.request.user
        ).select_related('message__sender', 'message__conversation')
        
        if conversation_id:
            queryset = queryset.filter(message__conversation_id=conversation_id)
        
        return queryset


class PinConversationView(APIView):
    """Pin or unpin a conversation"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        member = conversation.members.filter(user=request.user, left_at__isnull=True).first()
        
        if not member:
            return Response(
                {'error': 'You are not a member of this conversation'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check pin limit (WhatsApp allows 3 pinned chats)
        pinned_count = ConversationMember.objects.filter(
            user=request.user,
            is_pinned=True,
            left_at__isnull=True
        ).count()
        
        if not member.is_pinned and pinned_count >= 3:
            return Response(
                {'error': 'You can only pin up to 3 conversations'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        member.is_pinned = not member.is_pinned
        member.save()
        
        return Response({
            'message': 'Conversation pinned' if member.is_pinned else 'Conversation unpinned',
            'is_pinned': member.is_pinned
        })


class ArchiveConversationView(APIView):
    """Archive or unarchive a conversation"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        member = conversation.members.filter(user=request.user, left_at__isnull=True).first()
        
        if not member:
            return Response(
                {'error': 'You are not a member of this conversation'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        member.is_archived = not member.is_archived
        member.save()
        
        return Response({
            'message': 'Conversation archived' if member.is_archived else 'Conversation unarchived',
            'is_archived': member.is_archived
        })


class MuteConversationView(APIView):
    """Mute or unmute a conversation"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        member = conversation.members.filter(user=request.user, left_at__isnull=True).first()
        
        if not member:
            return Response(
                {'error': 'You are not a member of this conversation'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        member.is_muted = not member.is_muted
        member.save()
        
        return Response({
            'message': 'Conversation muted' if member.is_muted else 'Conversation unmuted',
            'is_muted': member.is_muted
        })


class BlockUserView(APIView):
    """Block a user"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        user_id = request.data.get('user_id')
        
        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        blocked_user = get_object_or_404(User, id=user_id)
        
        if blocked_user == request.user:
            return Response(
                {'error': 'You cannot block yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        blocked, created = BlockedUser.objects.get_or_create(
            blocker=request.user,
            blocked=blocked_user
        )
        
        if created:
            return Response({'message': f'Blocked {blocked_user.username}'}, status=status.HTTP_201_CREATED)
        else:
            return Response({'message': 'User already blocked'}, status=status.HTTP_200_OK)


class UnblockUserView(APIView):
    """Unblock a user"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        user_id = request.data.get('user_id')
        
        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        blocked_user = get_object_or_404(User, id=user_id)
        
        deleted_count, _ = BlockedUser.objects.filter(
            blocker=request.user,
            blocked=blocked_user
        ).delete()
        
        if deleted_count > 0:
            return Response({'message': f'Unblocked {blocked_user.username}'})
        else:
            return Response(
                {'error': 'User is not blocked'},
                status=status.HTTP_404_NOT_FOUND
            )


class BlockedUsersListView(generics.ListAPIView):
    """List all blocked users"""
    serializer_class = BlockedUserSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return BlockedUser.objects.filter(
            blocker=self.request.user
        ).select_related('blocked')



class InitiateCallView(APIView):
    """Initiate an audio or video call"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        
        serializer = CallInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        conversation_id = serializer.validated_data['conversation_id']
        call_type = serializer.validated_data['call_type']
        offer_sdp = serializer.validated_data.get('offer_sdp', '')
        
        conversation = get_object_or_404(Conversation, id=conversation_id)
        
        # Verify user is member
        member = conversation.members.filter(
            user=request.user,
            left_at__isnull=True
        ).first()
        
        if not member:
            return Response(
                {'error': 'You are not a member of this conversation'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if there's already an active call
        active_call = Call.objects.filter(
            conversation=conversation,
            status__in=['initiated', 'ringing', 'answered']
        ).first()
        
        if active_call:
            return Response(
                {'error': 'There is already an active call in this conversation'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create call
        call = Call.objects.create(
            conversation=conversation,
            caller=request.user,
            call_type=call_type,
            status='initiated',
            offer_sdp=offer_sdp
        )
        
        # Add caller as participant
        CallParticipant.objects.create(
            call=call,
            user=request.user,
            status='joined',
            joined_at=timezone.now()
        )
        
        # Add other members as invited participants
        other_members = conversation.members.filter(
            left_at__isnull=True
        ).exclude(user=request.user)
        
        for member in other_members:
            CallParticipant.objects.create(
                call=call,
                user=member.user,
                status='invited'
            )
        
        return Response(
            CallSerializer(call, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )


class CallDetailView(generics.RetrieveUpdateAPIView):
    """Get or update call details"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method == 'PATCH':
            return CallUpdateSerializer
        return CallSerializer
    
    def get_queryset(self):
        # User must be a participant
        return Call.objects.filter(
            participants=self.request.user
        ).prefetch_related('call_participants__user')
    
    def update(self, request, *args, **kwargs):
        
        call = self.get_object()
        update_serializer = CallUpdateSerializer(data=request.data)
        update_serializer.is_valid(raise_exception=True)
        
        new_status = update_serializer.validated_data.get('status')
        ice_candidates = update_serializer.validated_data.get('ice_candidates')
        
        # Update call status
        if new_status:
            if new_status == 'answered' and call.status in ['initiated', 'ringing']:
                call.status = 'answered'
                call.answered_at = timezone.now()
                
                # Update participant status
                participant = call.call_participants.get(user=request.user)
                participant.status = 'joined'
                participant.joined_at = timezone.now()
                participant.save()
                
            elif new_status == 'rejected':
                call.status = 'rejected'
                
                participant = call.call_participants.get(user=request.user)
                participant.status = 'rejected'
                participant.save()
                
            elif new_status == 'ended':
                call.status = 'ended'
                call.ended_at = timezone.now()
                call.calculate_duration()
                
                participant = call.call_participants.get(user=request.user)
                participant.status = 'left'
                participant.left_at = timezone.now()
                participant.save()
            
            call.save()
        
        # Add ICE candidates
        if ice_candidates:
            participant = call.call_participants.get(user=request.user)
            participant.ice_candidates.extend(ice_candidates)
            participant.save()
        
        serializer = CallSerializer(call, context={'request': request})
        return Response(serializer.data)


class AnswerCallView(APIView):
    """Answer an incoming call"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, call_id):
        
        call = get_object_or_404(Call, id=call_id)
        
        # Verify user is a participant
        participant = call.call_participants.filter(user=request.user).first()
        if not participant:
            return Response(
                {'error': 'You are not a participant in this call'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if call is still active
        if call.status not in ['initiated', 'ringing']:
            return Response(
                {'error': 'Call is no longer active'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = CallAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Update call
        call.answer_sdp = serializer.validated_data['answer_sdp']
        call.status = 'answered'
        call.answered_at = timezone.now()
        call.save()
        
        # Update participant
        participant.status = 'joined'
        participant.joined_at = timezone.now()
        participant.save()
        
        return Response(CallSerializer(call, context={'request': request}).data)


class EndCallView(APIView):
    """End a call"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, call_id):
        call = get_object_or_404(Call, id=call_id)
        
        # Verify user is a participant
        participant = call.call_participants.filter(user=request.user).first()
        if not participant:
            return Response(
                {'error': 'You are not a participant in this call'},
                status=status.HTTP_403_FORBIDDEN
            )
        
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
        
        return Response({
            'message': 'Call ended',
            'duration': duration,
            'call_id': str(call.id)
        })


class CallHistoryView(generics.ListAPIView):
    """Get call history for a conversation"""
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CustomCursorPagination
    
    def get_serializer_class(self):
        return CallSerializer
    
    def get_queryset(self):
        conversation_id = self.kwargs.get('conversation_id')
        
        # Verify user is member
        conversation = get_object_or_404(Conversation, id=conversation_id)
        if not conversation.members.filter(
            user=self.request.user,
            left_at__isnull=True
        ).exists():
            return Call.objects.none()
        
        return Call.objects.filter(
            conversation_id=conversation_id
        ).prefetch_related('call_participants__user').order_by('-initiated_at')


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def my_calls(request):
    """Get all calls for current user"""
    
    calls = Call.objects.filter(
        participants=request.user
    ).prefetch_related('call_participants__user').order_by('-initiated_at')[:50]
    
    serializer = CallSerializer(calls, many=True, context={'request': request})
    return Response({
        'results': serializer.data,
        'count': len(serializer.data)
    })


import logging
logger = logging.getLogger(__name__)

class TurnCredentialsView(APIView):
    """Fetch TURN/STUN credentials from Metered — keeps the API key server-side"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        logger.info(f"TurnCredentialsView called by user: {request.user}")
        
        # Best practice: Move this to settings.py or environment variables later
        api_key = "624b16c68369c38ac31fa3b7a0af1ae1dc22"
        target_url = f'https://net-hiss.metered.live/api/v1/turn/credentials'

        try:
            logger.info(f"Requesting TURN credentials from Metered...")
            
            # Perform the actual network request
            # We store the result in 'res', which is a Response object
            res = requests.get(
                target_url,
                params={'apiKey': api_key},
                timeout=5
            )

            # Now we can check status_code and text on 'res'
            logger.info(f"Metered API response status: {res.status_code}")
            
            if not res.ok:
                logger.error(f"Metered API failed with body: {res.text}")
                return Response(
                    {'error': 'Failed to fetch TURN credentials'},
                    status=res.status_code
                )

            data = res.json()
            logger.info("Successfully fetched TURN credentials")
            return Response(data)

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error contacting Metered: {str(e)}")
            return Response(
                {'error': 'Communication with TURN provider failed'},
                status=status.HTTP_502_BAD_GATEWAY
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Internal server error'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )