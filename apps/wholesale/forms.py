from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.urls import reverse
from django.utils.html import format_html

from apps.fulfillment.models import Carrier

from . import accounts
from .checkout import DELIVERY_CARRIER, DELIVERY_PICKUP
from .models import EmailTemplate, StoreSettings


class StoreFormMixin:
    """Clases de marca en los widgets y `aria-invalid` en los campos con error."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "st-check"
            elif isinstance(widget, forms.RadioSelect | forms.CheckboxSelectMultiple):
                css = ""
            elif isinstance(widget, forms.Select):
                css = "st-select"
            elif isinstance(widget, forms.Textarea):
                css = "st-textarea"
            else:
                css = "st-input"
            if css:
                widget.attrs["class"] = (widget.attrs.get("class", "") + " " + css).strip()

    def is_valid(self):
        valid = super().is_valid()
        for name in self.errors:
            if name in self.fields:
                self.fields[name].widget.attrs["aria-invalid"] = "true"
        return valid


class StoreLoginForm(StoreFormMixin, AuthenticationForm):
    error_messages = {
        "invalid_login": "El email o la contraseña no son correctos. Revisalos y probá de nuevo.",
        "inactive": "Tu usuario está desactivado. Escribinos para resolverlo.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].widget.attrs.update({"autocomplete": "email", "inputmode": "email"})


class StorePasswordResetForm(StoreFormMixin, PasswordResetForm):
    pass


class StoreSetPasswordForm(StoreFormMixin, SetPasswordForm):
    pass


class RegistrationForm(StoreFormMixin, forms.Form):
    cuit = forms.CharField(
        label="CUIT",
        max_length=13,
        help_text="Los 11 números, con o sin guiones.",
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "autocomplete": "off", "placeholder": "30-12345678-9"}
        ),
    )
    legal_name = forms.CharField(label="Razón social", max_length=255)
    trade_name = forms.CharField(label="Nombre de fantasía", max_length=255, required=False)
    vat_condition = forms.ChoiceField(label="Condición de IVA", choices=accounts.VAT_CHOICES)
    street = forms.CharField(label="Calle", max_length=200)
    number = forms.CharField(label="Número", max_length=20)
    city = forms.CharField(label="Localidad", max_length=100)
    province = forms.ChoiceField(
        label="Provincia", choices=[("", "Elegí la provincia")] + [(p, p) for p in accounts.PROVINCES]
    )
    postal_code = forms.CharField(label="Código postal", max_length=10)
    phone = forms.CharField(
        label="Teléfono",
        max_length=50,
        widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel"}),
    )
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password1 = forms.CharField(
        label="Contraseña",
        strip=False,
        help_text="Al menos 10 caracteres. Que no sea solo números ni algo fácil de adivinar.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Repetí la contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    accept_terms = forms.BooleanField(
        label="Leí y acepto los términos de venta mayorista y la política de privacidad",
        error_messages={"required": "Para registrarte tenés que aceptar los términos."},
    )
    # Campo trampa: invisible para las personas; los bots lo completan.
    website = forms.CharField(
        required=False,
        label="Sitio web",
        widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}),
    )

    def clean_cuit(self):
        try:
            cuit = accounts.validate_cuit(self.cleaned_data["cuit"])
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc
        if accounts.cuit_has_account(cuit):
            raise forms.ValidationError(
                format_html(
                    'Ese CUIT ya tiene una cuenta. <a class="st-link" href="{}">Ingresá</a> o '
                    '<a class="st-link" href="{}">recuperá tu contraseña</a>.',
                    reverse("store:login"),
                    reverse("store:password_reset"),
                )
            )
        return cuit

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                format_html(
                    'Ese email ya está registrado. <a class="st-link" href="{}">Ingresá</a> o '
                    '<a class="st-link" href="{}">recuperá tu contraseña</a>.',
                    reverse("store:login"),
                    reverse("store:password_reset"),
                )
            )
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        elif p1:
            try:
                password_validation.validate_password(p1)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return data

    @property
    def is_bot(self) -> bool:
        return bool(self.data.get("website"))


class InvitationAcceptForm(StoreFormMixin, forms.Form):
    """El cliente invitado elige su contraseña y acepta los términos."""

    password1 = forms.CharField(
        label="Contraseña",
        strip=False,
        help_text="Al menos 10 caracteres. Que no sea solo números ni algo fácil de adivinar.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Repetí la contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    accept_terms = forms.BooleanField(
        label="Leí y acepto los términos de venta mayorista y la política de privacidad",
        error_messages={"required": "Para continuar tenés que aceptar los términos."},
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        elif p1:
            try:
                password_validation.validate_password(p1, self.user)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return data


class InvitationRequestForm(StoreFormMixin, forms.Form):
    """«Pedir otra invitación» con CUIT y email. Los errores no revelan si la cuenta existe."""

    cuit = forms.CharField(
        label="CUIT",
        max_length=13,
        help_text="Los 11 números, con o sin guiones.",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
        help_text="El mismo con el que te invitamos.",
    )
    # Campo trampa: invisible para las personas; los bots lo completan.
    website = forms.CharField(
        required=False,
        label="Sitio web",
        widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}),
    )

    @property
    def is_bot(self) -> bool:
        return bool(self.data.get("website"))


class InvitationEmailForm(forms.Form):
    """Panel: corregir el email de un cliente antes de mandarle la invitación."""

    email = forms.EmailField(label="Email")


class AccountDataForm(forms.Form):
    """Panel: el administrador corrige los datos del registro."""

    cuit = forms.CharField(label="CUIT", max_length=13)
    legal_name = forms.CharField(label="Razón social", max_length=255)
    trade_name = forms.CharField(label="Nombre de fantasía", max_length=255, required=False)
    vat_condition = forms.ChoiceField(label="Condición de IVA", choices=accounts.VAT_CHOICES)
    street = forms.CharField(label="Calle", max_length=200, required=False)
    number = forms.CharField(label="Número", max_length=20, required=False)
    city = forms.CharField(label="Localidad", max_length=100, required=False)
    province = forms.ChoiceField(
        label="Provincia", choices=[("", "—")] + [(p, p) for p in accounts.PROVINCES], required=False
    )
    postal_code = forms.CharField(label="Código postal", max_length=10, required=False)
    phone = forms.CharField(label="Teléfono", max_length=50, required=False)

    def __init__(self, *args, account=None, **kwargs):
        super().__init__(*args, **kwargs)
        if account is not None and account.status != account.Status.PENDING:
            self.fields["cuit"].disabled = True
            self.fields["cuit"].help_text = "El CUIT no se cambia en una cuenta ya revisada."

    def clean_cuit(self):
        try:
            return accounts.validate_cuit(self.cleaned_data["cuit"])
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc


class StoreSettingsForm(forms.ModelForm):
    class Meta:
        model = StoreSettings
        fields = [
            "min_order_amount",
            "min_order_includes_vat",
            "transfer_expiry_days",
            "bank_details",
            "safety_margin_units",
            "terms_text",
            "privacy_text",
        ]
        help_texts = {
            "min_order_amount": "Solo para los pedidos que hace el cliente (no para los cargados en su nombre).",
            "bank_details": "CBU, alias, titular y CUIT. Se muestran tal cual al elegir transferencia.",
            "safety_margin_units": "Unidades que se descuentan del stock de cada variante antes de mostrarla disponible.",
            "transfer_expiry_days": "Si no se confirma el pago en estos días, el pedido se cancela y se libera la reserva.",
        }
        widgets = {
            "bank_details": forms.Textarea(attrs={"rows": 4}),
            "terms_text": forms.Textarea(attrs={"rows": 10}),
            "privacy_text": forms.Textarea(attrs={"rows": 10}),
        }

    def clean_transfer_expiry_days(self):
        days = self.cleaned_data["transfer_expiry_days"]
        if days < 1:
            raise forms.ValidationError("Tiene que ser al menos 1 día.")
        return days


class EmailTemplateForm(forms.ModelForm):
    class Meta:
        model = EmailTemplate
        fields = ["subject", "body"]
        widgets = {"body": forms.Textarea(attrs={"rows": 12})}


class CheckoutForm(StoreFormMixin, forms.Form):
    delivery = forms.ChoiceField(
        label="¿Cómo lo recibís?",
        choices=[
            (DELIVERY_CARRIER, "Envío por expreso (el flete lo pagás vos)"),
            (DELIVERY_PICKUP, "Retiro en el local"),
        ],
        widget=forms.RadioSelect,
        error_messages={"required": "Elegí cómo querés recibir el pedido."},
    )
    carrier = forms.ChoiceField(label="Expreso", required=False)
    payment = forms.ChoiceField(
        label="¿Cómo pagás?", widget=forms.RadioSelect, error_messages={"required": "Elegí cómo vas a pagar."}
    )
    notes = forms.CharField(
        label="Comentarios para Deutsch",
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    snapshot = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, payments=None, **kwargs):
        super().__init__(*args, **kwargs)
        carriers = list(Carrier.objects.filter(is_active=True).values_list("name", flat=True))
        self.fields["carrier"].choices = [("", "Elegí el expreso")] + [(c, c) for c in carriers]
        self.fields["payment"].choices = payments or []
        self.fields["carrier"].conditional = True  # obligatorio solo con envío (no se marca "opcional")
        self.has_carriers = bool(carriers)

    def clean(self):
        data = super().clean()
        if data.get("delivery") == DELIVERY_CARRIER and not data.get("carrier"):
            self.add_error("carrier", "Elegí el expreso que te lleva el pedido.")
        if data.get("payment") == "cash" and data.get("delivery") != DELIVERY_PICKUP:
            self.add_error("payment", "El efectivo es solo para retirar en el local.")
        return data


class ChangeRequestForm(StoreFormMixin, forms.Form):
    text = forms.CharField(
        label="¿Qué dato querés cambiar?",
        max_length=1000,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Por ejemplo: nos mudamos a Av. San Martín 123, Rosario."}
        ),
    )


class ReceiptForm(forms.Form):
    file = forms.FileField(label="Comprobante (foto o PDF, hasta 10 MB)")
