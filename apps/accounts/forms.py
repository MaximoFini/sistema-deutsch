from django import forms
from django.contrib.auth.models import Group, Permission
from django.db.models import Q

from .models import User
from .roles import PERMISSION_LABELS, ROLE_NAMES, ROLE_PERMISSIONS


def panel_permissions():
    """Permisos que se pueden sumar o quitar desde el panel (los que usa algún rol)."""
    names = sorted({p for perms in ROLE_PERMISSIONS.values() for p in perms})
    query = Q(pk__in=[])
    for name in names:
        app_label, codename = name.split(".")
        query |= Q(content_type__app_label=app_label, codename=codename)
    return Permission.objects.filter(query).select_related("content_type").order_by("name")


class PermissionChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return PERMISSION_LABELS.get(f"{obj.content_type.app_label}.{obj.codename}", obj.name)


class UserForm(forms.ModelForm):
    role = forms.ModelChoiceField(
        label="Rol", queryset=Group.objects.filter(name__in=ROLE_NAMES).order_by("name"), required=True
    )
    extra_permissions = PermissionChoiceField(
        label="Permisos sumados (además del rol)",
        queryset=Permission.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    denied_permissions = PermissionChoiceField(
        label="Permisos quitados (aunque el rol los tenga)",
        queryset=Permission.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = ["full_name", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        perms = panel_permissions()
        self.fields["extra_permissions"].queryset = perms
        self.fields["denied_permissions"].queryset = perms
        if self.instance.pk:
            self.fields["role"].initial = self.instance.groups.first()
            self.fields["extra_permissions"].initial = self.instance.user_permissions.all()
            self.fields["denied_permissions"].initial = Permission.objects.filter(
                userpermissiondenial__user=self.instance
            )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe un usuario con ese email.")
        return email

    def clean(self):
        data = super().clean()
        both = set(data.get("extra_permissions") or []) & set(data.get("denied_permissions") or [])
        if both:
            raise forms.ValidationError("Un permiso no puede estar sumado y quitado a la vez.")
        return data
