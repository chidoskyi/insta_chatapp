from django.urls import path
from . import views

app_name = 'reels'

urlpatterns = [
    # Reels
    path('reels/', views.ReelListCreateView.as_view(), name='reel_list_create'),
    path('reels/<int:pk>/', views.ReelDetailView.as_view(), name='reel_detail'),
    path('reels/<int:pk>/like/', views.ReelLikeToggleView.as_view(), name='reel_like'),
    path('reels/<int:pk>/save/', views.SaveReelToggleView.as_view(), name='reel_save'),
    path('reels/<int:pk>/share/', views.ReelShareView.as_view(), name='reel_share'),
    path('reels/<int:pk>/track-view/', views.track_reel_view, name='track_reel_view'),
    
    # Feeds
    path('reels/feed/', views.ReelFeedView.as_view(), name='reel_feed'),
    path('reels/trending/', views.TrendingReelsView.as_view(), name='trending_reels'),
    
    # User reels
    path('users/<str:username>/reels/', views.UserReelsView.as_view(), name='user_reels'),
    
    # Comments
    path('reels/<int:reel_id>/comments/', views.ReelCommentListCreateView.as_view(), name='reel_comments'),
    path('reels/comments/<int:pk>/', views.ReelCommentDetailView.as_view(), name='reel_comment_detail'),
    path('reels/comments/<int:pk>/like/', views.ReelCommentLikeToggleView.as_view(), name='reel_comment_like'),
    
    # Saved reels
    path('reels/saved/', views.SavedReelsView.as_view(), name='saved_reels'),
]