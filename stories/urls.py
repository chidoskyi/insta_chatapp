from django.urls import path
from . import views

app_name = 'stories'

urlpatterns = [
    # Stories
    path('stories/', views.StoryListCreateView.as_view(), name='story_list_create'),
    path('stories/<int:pk>/', views.StoryDetailView.as_view(), name='story_detail'),
    path('stories/<int:story_id>/viewers/', views.StoryViewersView.as_view(), name='story_viewers'),
    path('stories/feed/', views.FeedStoriesView.as_view(), name='stories_feed'),
    
    # User stories
    path('users/<str:username>/stories/', views.UserStoriesView.as_view(), name='user_stories'),
    
    # Highlights
    path('highlights/', views.StoryHighlightListCreateView.as_view(), name='highlight_list_create'),
    path('highlights/<int:pk>/', views.StoryHighlightDetailView.as_view(), name='highlight_detail'),
    
    # Add/Remove Stories from Highlights
    path('highlights/<int:highlight_id>/stories/<int:story_id>/add/', views.AddStoryToHighlightView.as_view(), name='add_story_to_highlight'),
    path('highlights/<int:highlight_id>/stories/<int:story_id>/remove/', views.RemoveStoryFromHighlightView.as_view(), name='remove_story_from_highlight'),
    
    # Add/Remove Posts from Highlights (NEW)
    path('highlights/<int:highlight_id>/posts/<int:post_id>/add/', views.AddPostToHighlightView.as_view(), name='add_post_to_highlight'),
    path('highlights/<int:highlight_id>/posts/<int:post_id>/remove/', views.RemovePostFromHighlightView.as_view(), name='remove_post_from_highlight'),
    
    # Cleanup (admin only)
    path('stories/cleanup/', views.delete_expired_stories, name='cleanup_expired'),
]