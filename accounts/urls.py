from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

app_name = 'accounts'

urlpatterns = [
    # Authentication
    path('auth/register/', views.RegisterView.as_view(), name='register'),
    path('auth/login/', views.CustomLoginView.as_view(), name='login'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

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
    path('auth/users/search/', views.UserSearchView.as_view(), name='user-search'),
    
    # Current User (me endpoint)
    path('auth/users/me/', views.current_user, name='current-user'),
    
    # Current User Profile (me endpoint)
    path('auth/users/profile/', views.CurrentUserProfileView.as_view(), name='current-user-profile'),
    
    # User Profile
    path('auth/users/<str:username>/', views.UserProfileDetailView.as_view(), name='user-profile-detail'),
    
    # User Avatar
    path('auth/users/avatar/', views.UserAvatarView.as_view(), name='user-avatar'),
]