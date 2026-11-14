from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import FormView, ListView

from . import services
from .forms import UserForm
from .mixins import PanelPermissionRequiredMixin
from .models import User

# ── Login y recuperación de contraseña (públicas) ─────────────────────────────


class LoginView(auth_views.LoginView):
    panel_access = "public"
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    panel_access = "public"


class PasswordResetView(auth_views.PasswordResetView):
    panel_access = "public"
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/email/password_reset.txt"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    panel_access = "public"
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    panel_access = "public"
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    panel_access = "public"
    template_name = "accounts/password_reset_complete.html"


# ── Administración de usuarios ────────────────────────────────────────────────


class UserListView(PanelPermissionRequiredMixin, ListView):
    permission_required = "accounts.manage_users"
    template_name = "accounts/user_list.html"
    queryset = User.objects.prefetch_related("groups").order_by("-is_active", "full_name")
    context_object_name = "users"


class UserFormView(PanelPermissionRequiredMixin, FormView):
    permission_required = "accounts.manage_users"
    template_name = "accounts/user_form.html"
    form_class = UserForm
    success_url = reverse_lazy("accounts:user_list")

    def get_object(self):
        pk = self.kwargs.get("pk")
        return get_object_or_404(User, pk=pk) if pk else None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.get_object()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["object"] = self.get_object()
        return ctx

    def form_valid(self, form):
        data = form.cleaned_data
        common = {
            "actor": self.request.user,
            "request": self.request,
            "full_name": data["full_name"],
            "email": data["email"],
            "role": data["role"],
            "extra": data["extra_permissions"],
            "denied": data["denied_permissions"],
        }
        user = self.get_object()
        if user:
            services.update_user(user=user, **common)
            messages.success(self.request, f"Usuario {user} actualizado.")
        else:
            user = services.create_user(**common)
            messages.success(
                self.request, f"Usuario {user} creado. Le enviamos un email para elegir su contraseña."
            )
        return super().form_valid(form)


class UserToggleActiveView(PanelPermissionRequiredMixin, View):
    permission_required = "accounts.manage_users"
    http_method_names = ["post"]

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if user == request.user:
            messages.error(request, "No podés desactivar tu propio usuario.")
        else:
            services.set_active(actor=request.user, request=request, user=user, active=not user.is_active)
            messages.success(request, f"Usuario {user} {'reactivado' if user.is_active else 'desactivado'}.")
        return redirect("accounts:user_list")
