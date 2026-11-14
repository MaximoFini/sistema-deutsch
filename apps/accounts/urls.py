from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("recuperar/", views.PasswordResetView.as_view(), name="password_reset"),
    path("recuperar/enviado/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path(
        "recuperar/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"
    ),
    path("recuperar/listo/", views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("usuarios/", views.UserListView.as_view(), name="user_list"),
    path("usuarios/nuevo/", views.UserFormView.as_view(), name="user_create"),
    path("usuarios/<int:pk>/", views.UserFormView.as_view(), name="user_edit"),
    path("usuarios/<int:pk>/activo/", views.UserToggleActiveView.as_view(), name="user_toggle_active"),
]
