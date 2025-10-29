from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.db.models import Q
from .models import Notification, NotificationPreference, NotificationGroup
from .serializers import (
    NotificationSerializer,
    NotificationGroupSerializer,
    NotificationPreferenceSerializer
)


class NotificationListView(generics.ListAPIView):
    """List all notifications for current user"""
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        show_unread_only = self.request.query_params.get('unread', 'false').lower() == 'true'
        
        queryset = Notification.objects.filter(
            recipient=user
        ).select_related('sender')
        
        if show_unread_only:
            queryset = queryset.filter(is_read=False)
        
        return queryset


class NotificationDetailView(generics.RetrieveAPIView):
    """Get a specific notification"""
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
        
        return Response({
            'message': 'Notification marked as read',
            'id': notification.id,
            'is_read': notification.is_read
        })


class MarkAllNotificationsReadView(APIView):
    """Mark all notifications as read"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        from django.utils import timezone
        
        updated = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).update(
            is_read=True,
            read_at=timezone.now()
        )
        
        return Response({
            'message': f'{updated} notifications marked as read',
            'count': updated
        })


class DeleteNotificationView(generics.DestroyAPIView):
    """Delete a notification"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)


class ClearAllNotificationsView(APIView):
    """Clear all notifications"""
    permission_classes = [permissions.IsAuthenticated]
    
    def delete(self, request):
        deleted = Notification.objects.filter(
            recipient=request.user
        ).delete()[0]
        
        return Response({
            'message': f'{deleted} notifications cleared',
            'count': deleted
        })


class UnreadCountView(APIView):
    """Get count of unread notifications"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        count = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()
        
        return Response({
            'unread_count': count
        })


class NotificationGroupListView(generics.ListAPIView):
    """List grouped notifications"""
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


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def notification_stats(request):
    """Get notification statistics"""
    user = request.user
    
    total = Notification.objects.filter(recipient=user).count()
    unread = Notification.objects.filter(recipient=user, is_read=False).count()
    
    # Count by type
    type_counts = {}
    for notification_type, _ in Notification.NOTIFICATION_TYPES:
        count = Notification.objects.filter(
            recipient=user,
            notification_type=notification_type
        ).count()
        if count > 0:
            type_counts[notification_type] = count
    
    return Response({
        'total': total,
        'unread': unread,
        'read': total - unread,
        'by_type': type_counts
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def test_notification(request):
    """Create a test notification (for development)"""
    from .utils import create_notification
    
    notification = create_notification(
        recipient=request.user,
        sender=request.user,
        notification_type='follow',
        message='This is a test notification'
    )
    
    serializer = NotificationSerializer(notification)
    return Response(serializer.data, status=status.HTTP_201_CREATED)