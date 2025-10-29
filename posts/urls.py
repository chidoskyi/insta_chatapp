from django.urls import path
from . import views

app_name = 'posts'

urlpatterns = [
    # Posts
    path('posts/', views.PostListCreateView.as_view(), name='post_list_create'),
    path('posts/<int:pk>/', views.PostDetailView.as_view(), name='post_detail'),
    path('posts/<int:pk>/like/', views.LikeToggleView.as_view(), name='post_like'),
    path('posts/<int:pk>/save/', views.SavePostToggleView.as_view(), name='post_save'),
    path('posts/saved/', views.SavedPostsView.as_view(), name='saved-posts'),

    # Feed
    path('feed/', views.FeedView.as_view(), name='feed'),
    
    # User posts
    path('users/<str:username>/posts/', views.UserPostsView.as_view(), name='user_posts'),
    
    # Comments
    path('posts/<int:post_id>/comments/', views.CommentListCreateView.as_view(), name='comment_list_create'),
    path('comments/<int:pk>/', views.CommentDetailView.as_view(), name='comment_detail'),
    path('comments/<int:pk>/like/', views.CommentLikeToggleView.as_view(), name='comment_like'),
    path('comments/<int:comment_id>/replies/', views.CommentRepliesView.as_view(), name='comment_replies'),
    
    # Saved posts
    path('saved/', views.SavedPostsView.as_view(), name='saved_posts'),
    
    # Tags
    path('tags/<str:tag_name>/posts/', views.TagPostsView.as_view(), name='tag_posts'),
    path('tags/trending/', views.TrendingTagsView.as_view(), name='trending_tags'),

    # Mention endpoints
    path('mentions/', views.UserMentionsView.as_view(), name='user_mentions'),
    path('mentions/search/', views.search_users_for_mention, name='mention_search'),
    path('posts/<int:post_id>/mentions/', views.PostMentionsView.as_view(), name='post_mentions'),
    path('comments/<int:comment_id>/mentions/', views.CommentMentionsView.as_view(), name='comment_mentions'),
]
