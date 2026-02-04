from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    # List and stats
    path('notifications/', views.NotificationListView.as_view(), name='notification-list'),
    path('notifications/stats/', views.notification_stats, name='notification-stats'),
    path('notifications/recent/', views.recent_notifications, name='recent-notifications'),
    path('notifications/unread-count/', views.UnreadCountView.as_view(), name='unread-count'),
    
    # Individual notification
    path('notifications/<uuid:pk>/', views.NotificationDetailView.as_view(), name='notification-detail'),
    path('notifications/<uuid:pk>/read/', views.MarkNotificationReadView.as_view(), name='mark-read'),
    path('notifications/<uuid:pk>/delete/', views.DeleteNotificationView.as_view(), name='delete-notification'),
    
    # Bulk actions
    path('notifications/mark-all-read/', views.MarkAllNotificationsReadView.as_view(), name='mark-all-read'),
    path('notifications/conversation/<uuid:conversation_id>/mark-read/', 
         views.MarkConversationNotificationsReadView.as_view(), 
         name='mark-conversation-read'),
    path('notifications/clear-all/', views.ClearAllNotificationsView.as_view(), name='clear-all'),
    path('notifications/clear-read/', views.ClearReadNotificationsView.as_view(), name='clear-read'),
    
    # Grouped notifications
    path('notifications/groups/', views.NotificationGroupListView.as_view(), name='notification-groups'),
    
    # Preferences
    path('notifications/preferences/', views.NotificationPreferenceView.as_view(), name='preferences'),
    path('notifications/mute/', views.MuteNotificationsView.as_view(), name='mute'),
    path('notifications/unmute/', views.UnmuteNotificationsView.as_view(), name='unmute'),
    
    # Testing
    path('notifications/test/', views.test_notification, name='test-notification'),
]
