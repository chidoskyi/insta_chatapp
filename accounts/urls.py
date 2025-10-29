from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

app_name = 'accounts'

urlpatterns = [
    # Authentication
    path('auth/register/', views.RegisterView.as_view(), name='register'),
    path('auth/login/', views.CustomLoginView.as_view(), name='login'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/user/', views.current_user, name='current_user'),

    # Password Reset
    path('auth/password-reset/', views.PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('auth/password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('auth/change-password/', views.ChangePasswordView.as_view(), name='change_password'),

    # Google OAuth
    path('auth/google/', views.GoogleLoginView.as_view(), name='google_login'),

    # Email Change
    path('auth/email/change/request/', views.EmailChangeRequestView.as_view(), name='email-change-request'),
    path('auth/email/change/verify/', views.EmailVerificationView.as_view(), name='email-change-verify'),
    path('auth/email/change/resend/', views.ResendVerificationCodeView.as_view(), name='email-change-resend'),

    # User Search - MUST come BEFORE generic user patterns
    path('users/search/', views.UserSearchView.as_view(), name='user-search'),
    path('users/search/suggestions/', views.UserSearchSuggestionsView.as_view(), name='user-search-suggestions'),
    # path('users/search/advanced/', views.AdvancedUserSearchView.as_view(), name='user-search-advanced'),
    
    # Current User Profile (me endpoint)
    path('users/me/', views.CurrentUserProfileView.as_view(), name='current-user-profile'),
    
    # User Profile and Social - Specific patterns first
    path('users/<str:username>/follow/', views.FollowToggleView.as_view(), name='follow_toggle'),
    path('users/<str:username>/followers/', views.FollowersListView.as_view(), name='followers'),
    path('users/<str:username>/following/', views.FollowingListView.as_view(), name='following'),
    
    # View any user's profile by username (READ ONLY for other users)
    path('users/profile/<str:username>/', views.UserProfileByUsernameView.as_view(), name='user-profile-by-username'),
    
    # Update own profile by ID (for backward compatibility)
    path('users/<str:id>/', views.UserProfileByIdView.as_view(), name='user_profile'),
]