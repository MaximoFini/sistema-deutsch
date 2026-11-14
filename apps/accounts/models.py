from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, Permission, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("El email es obligatorio")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)


class User(AbstractBaseUser, PermissionsMixin):
    """Usuario interno. Se crea a mano desde el panel (sin autoregistro)."""

    email = models.EmailField("email", unique=True)
    full_name = models.CharField("nombre completo", max_length=150)
    is_active = models.BooleanField("activo", default=True)
    is_staff = models.BooleanField("acceso a /admin", default=False)
    date_joined = models.DateTimeField("alta", default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["full_name"]
        permissions = [("manage_users", "Puede administrar usuarios, roles y permisos")]

    def __str__(self) -> str:
        return self.full_name or self.email

    @property
    def role(self):
        return self.groups.first()

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name.split(" ")[0] if self.full_name else self.email


class UserPermissionDenial(models.Model):
    """Quita a un usuario un permiso que su rol le da, sin cambiarle el rol."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="permission_denials")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "permiso quitado"
        verbose_name_plural = "permisos quitados"
        constraints = [models.UniqueConstraint(fields=["user", "permission"], name="unique_user_denial")]
