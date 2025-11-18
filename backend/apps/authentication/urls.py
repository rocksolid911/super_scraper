"""
Authentication URLs.
"""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    RegisterView,
    CustomTokenObtainPairView,
    UserDetailView,
    UpdateProfileView,
    ChangePasswordView,
    LogoutView
)

app_name = 'authentication'

urlpatterns = [
    # Authentication
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', CustomTokenObtainPairView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),

    # User profile
    path('me/', UserDetailView.as_view(), name='user-detail'),
    path('me/update/', UpdateProfileView.as_view(), name='update-profile'),
    path('me/change-password/', ChangePasswordView.as_view(), name='change-password'),
]
