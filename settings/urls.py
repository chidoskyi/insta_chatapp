from django.urls import path
from . import views

app_name = 'user_settings'

urlpatterns = [
    # Privacy Settings
    path('settings/privacy/', views.PrivacySettingsView.as_view(), name='privacy_settings'),
    
    # Blocked Users
    path('settings/blocked/', views.BlockedUsersListView.as_view(), name='blocked_users'),
    path('settings/block/<str:username>/', views.BlockUserView.as_view(), name='block_user'),
    path('settings/unblock/<str:username>/', views.UnblockUserView.as_view(), name='unblock_user'),
    
    # Muted Users
    path('settings/muted/', views.MutedUsersListView.as_view(), name='muted_users'),
    path('settings/mute/<str:username>/', views.MuteUserView.as_view(), name='mute_user'),
    path('settings/unmute/<str:username>/', views.UnmuteUserView.as_view(), name='unmute_user'),
    
    # Restricted Users
    path('settings/restricted/', views.RestrictedUsersListView.as_view(), name='restricted_users'),
    path('settings/restrict/<str:username>/', views.RestrictUserView.as_view(), name='restrict_user'),
    path('settings/unrestrict/<str:username>/', views.UnrestrictUserView.as_view(), name='unrestrict_user'),
    
    # Close Friends
    path('settings/close-friends/', views.CloseFriendsListView.as_view(), name='close_friends'),
    path('settings/close-friends/add/<str:username>/', views.AddCloseFriendView.as_view(), name='add_close_friend'),
    path('settings/close-friends/remove/<str:username>/', views.RemoveCloseFriendView.as_view(), name='remove_close_friend'),
    
    # Activity Log
    path('settings/activity/', views.ActivityLogView.as_view(), name='activity_log'),
    
    # Account Management
    path('settings/delete-account/', views.delete_account, name='delete_account'),
    path('settings/download-data/', views.download_data, name='download_data'),
]