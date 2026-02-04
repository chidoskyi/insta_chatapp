from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count
from django.utils import timezone
from datetime import timedelta

from .models import Notification, NotificationPreference, NotificationGroup
from .serializers import (
    NotificationSerializer,
    NotificationGroupSerializer,
    NotificationPreferenceSerializer,
    NotificationStatsSerializer
)
from .utils import mark_conversation_notifications_read


class NotificationListView(generics.ListAPIView):
    """
    List all notifications for current user (WhatsApp style)
    
    Query params:
        - unread: boolean (show only unread)
        - type: notification_type filter
        - limit: number of notifications to return
    """
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        show_unread_only = self.request.query_params.get('unread', 'false').lower() == 'true'
        notification_type = self.request.query_params.get('type')
        
        queryset = Notification.objects.filter(
            recipient=user
        ).select_related('sender')
        
        if show_unread_only:
            queryset = queryset.filter(is_read=False)
        
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)
        
        return queryset[:100]  # Limit to last 100 notifications


class NotificationDetailView(generics.RetrieveDestroyAPIView):
    """Get or delete a specific notification"""
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        
        # Mark as read when retrieved
        if not instance.is_read:
            instance.mark_as_read()
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class MarkNotificationReadView(APIView):
    """Mark a notification as read"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, pk):
        notification = get_object_or_404(
            Notification,
            pk=pk,
            recipient=request.user
        )
        
        notification.mark_as_read()
        
        # Get updated unread count
        unread_count = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()
        
        return Response({
            'message': 'Notification marked as read',
            'id': str(notification.id),
            'is_read': notification.is_read,
            'unread_count': unread_count
        })


class MarkAllNotificationsReadView(APIView):
    """Mark all notifications as read"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        updated = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).update(
            is_read=True,
            read_at=timezone.now()
        )
        
        return Response({
            'message': f'{updated} notifications marked as read',
            'count': updated,
            'unread_count': 0
        })


class MarkConversationNotificationsReadView(APIView):
    """
    Mark all notifications for a specific conversation as read
    WhatsApp does this when you open a chat
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, conversation_id):
        # Verify user is member of conversation
        from messaging.models import ConversationMember
        
        member = ConversationMember.objects.filter(
            conversation_id=conversation_id,
            user=request.user,
            left_at__isnull=True
        ).first()
        
        if not member:
            return Response(
                {'error': 'You are not a member of this conversation'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Mark all notifications for this conversation as read
        updated = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
            payload__conversation_id=str(conversation_id)
        ).update(
            is_read=True,
            read_at=timezone.now()
        )
        
        # Get updated unread count
        unread_count = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()
        
        return Response({
            'message': f'{updated} notifications marked as read',
            'count': updated,
            'conversation_id': str(conversation_id),
            'unread_count': unread_count
        })


class DeleteNotificationView(generics.DestroyAPIView):
    """Delete a specific notification"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        
        # Get updated unread count
        unread_count = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()
        
        return Response({
            'message': 'Notification deleted',
            'unread_count': unread_count
        })


class ClearAllNotificationsView(APIView):
    """Clear all notifications (WhatsApp style)"""
    permission_classes = [permissions.IsAuthenticated]
    
    def delete(self, request):
        # Option 1: Delete all notifications
        deleted = Notification.objects.filter(
            recipient=request.user
        ).delete()[0]
        
        # Option 2: Only delete read notifications (uncomment if preferred)
        # deleted = Notification.objects.filter(
        #     recipient=request.user,
        #     is_read=True
        # ).delete()[0]
        
        return Response({
            'message': f'{deleted} notifications cleared',
            'count': deleted,
            'unread_count': 0
        })


class ClearReadNotificationsView(APIView):
    """Clear only read notifications"""
    permission_classes = [permissions.IsAuthenticated]
    
    def delete(self, request):
        deleted = Notification.objects.filter(
            recipient=request.user,
            is_read=True
        ).delete()[0]
        
        unread_count = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()
        
        return Response({
            'message': f'{deleted} read notifications cleared',
            'count': deleted,
            'unread_count': unread_count
        })


class UnreadCountView(APIView):
    """Get count of unread notifications"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        # Total unread count
        total_unread = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()
        
        # Unread count by type (WhatsApp shows separate counters)
        message_unread = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
            notification_type='message'
        ).count()
        
        group_message_unread = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
            notification_type='group_message'
        ).count()
        
        call_unread = Notification.objects.filter(
            recipient=request.user,
            is_read=False,
            notification_type__in=['call_missed', 'call_rejected']
        ).count()
        
        return Response({
            'unread_count': total_unread,
            'message_unread': message_unread,
            'group_message_unread': group_message_unread,
            'call_unread': call_unread,
        })


class NotificationGroupListView(generics.ListAPIView):
    """List grouped notifications (WhatsApp style)"""
    serializer_class = NotificationGroupSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return NotificationGroup.objects.filter(
            recipient=self.request.user
        ).prefetch_related('senders')


class NotificationPreferenceView(APIView):
    """Get or update notification preferences"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        preferences, created = NotificationPreference.objects.get_or_create(
            user=request.user
        )
        serializer = NotificationPreferenceSerializer(preferences)
        return Response(serializer.data)
    
    def put(self, request):
        preferences, created = NotificationPreference.objects.get_or_create(
            user=request.user
        )
        
        serializer = NotificationPreferenceSerializer(
            preferences,
            data=request.data,
            partial=True
        )
        
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def patch(self, request):
        return self.put(request)


class MuteNotificationsView(APIView):
    """
    Mute all notifications temporarily (WhatsApp style)
    
    Body params:
        - duration: 'hour', '8hours', 'week', 'always', or custom datetime
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        preferences, created = NotificationPreference.objects.get_or_create(
            user=request.user
        )
        
        duration = request.data.get('duration', 'always')
        
        if duration == 'always':
            preferences.pause_all = True
            preferences.pause_until = None
            message = 'Notifications muted indefinitely'
        
        elif duration == 'hour':
            preferences.pause_all = False
            preferences.pause_until = timezone.now() + timedelta(hours=1)
            message = 'Notifications muted for 1 hour'
        
        elif duration == '8hours':
            preferences.pause_all = False
            preferences.pause_until = timezone.now() + timedelta(hours=8)
            message = 'Notifications muted for 8 hours'
        
        elif duration == 'week':
            preferences.pause_all = False
            preferences.pause_until = timezone.now() + timedelta(weeks=1)
            message = 'Notifications muted for 1 week'
        
        else:
            # Custom datetime
            from dateutil import parser
            try:
                custom_time = parser.isoparse(duration)
                preferences.pause_all = False
                preferences.pause_until = custom_time
                message = f'Notifications muted until {custom_time}'
            except:
                return Response(
                    {'error': 'Invalid duration format'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        preferences.save()
        
        return Response({
            'message': message,
            'is_muted': preferences.is_currently_muted(),
            'muted_until': preferences.pause_until.isoformat() if preferences.pause_until else None
        })


class UnmuteNotificationsView(APIView):
    """Unmute all notifications"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        preferences, created = NotificationPreference.objects.get_or_create(
            user=request.user
        )
        
        preferences.pause_all = False
        preferences.pause_until = None
        preferences.save()
        
        return Response({
            'message': 'Notifications unmuted',
            'is_muted': False
        })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def notification_stats(request):
    """Get notification statistics (WhatsApp style)"""
    user = request.user
    
    total = Notification.objects.filter(recipient=user).count()
    unread = Notification.objects.filter(recipient=user, is_read=False).count()
    
    # Count from last 24 hours
    yesterday = timezone.now() - timedelta(days=1)
    recent_count = Notification.objects.filter(
        recipient=user,
        created_at__gte=yesterday
    ).count()
    
    # Count by type
    type_counts = {}
    for notification_type, _ in Notification.NOTIFICATION_TYPES:
        count = Notification.objects.filter(
            recipient=user,
            notification_type=notification_type
        ).count()
        if count > 0:
            type_counts[notification_type] = count
    
    serializer = NotificationStatsSerializer(data={
        'total': total,
        'unread': unread,
        'read': total - unread,
        'by_type': type_counts,
        'recent_count': recent_count
    })
    serializer.is_valid()
    
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def test_notification(request):
    """
    Create a test notification (for development/testing)
    
    Body:
        - notification_type: Type of notification to create
        - message: Custom message (optional)
    """
    from .models import Notification
    
    notification_type = request.data.get('notification_type', 'message')
    custom_message = request.data.get('message', 'This is a test notification')
    
    notification = Notification.objects.create(
        recipient=request.user,
        sender=request.user,
        notification_type=notification_type,
        message=custom_message,
        payload={
            'test': True,
            'created_via': 'test_endpoint'
        }
    )
    
    # Send real-time notification
    from .utils import send_realtime_notification
    send_realtime_notification(request.user, notification)
    
    serializer = NotificationSerializer(notification, context={'request': request})
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def recent_notifications(request):
    """Get notifications from last 24 hours (WhatsApp recent view)"""
    yesterday = timezone.now() - timedelta(days=1)
    
    notifications = Notification.objects.filter(
        recipient=request.user,
        created_at__gte=yesterday
    ).select_related('sender').order_by('-created_at')[:50]
    
    serializer = NotificationSerializer(
        notifications, 
        many=True, 
        context={'request': request}
    )
    
    return Response({
        'count': len(serializer.data),
        'notifications': serializer.data
    })