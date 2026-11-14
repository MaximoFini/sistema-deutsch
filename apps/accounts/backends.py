from django.contrib.auth.backends import ModelBackend


class PanelBackend(ModelBackend):
    """ModelBackend + permisos quitados por usuario (UserPermissionDenial).

    Permisos efectivos = permisos del rol + permisos puntuales − permisos quitados.
    """

    def get_all_permissions(self, user_obj, obj=None):
        if not user_obj.is_active or user_obj.is_anonymous or obj is not None:
            return set()
        if not hasattr(user_obj, "_panel_perm_cache"):
            perms = set(super().get_all_permissions(user_obj, obj))
            denied = {
                f"{app}.{codename}"
                for app, codename in user_obj.permission_denials.values_list(
                    "permission__content_type__app_label", "permission__codename"
                )
            }
            user_obj._panel_perm_cache = perms - denied
        return user_obj._panel_perm_cache
