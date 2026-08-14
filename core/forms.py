from django import forms

from .models import MappingProfile, Platform, Product, ProductAlias
from .services.import_pipeline import CANONICAL_FIELDS, REQUIRED_FIELDS


class BootstrapFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, (forms.CheckboxInput, forms.RadioSelect)):
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class PlatformForm(BootstrapFormMixin, forms.Form):
    platform = forms.ModelChoiceField(queryset=Platform.objects.none(), label="Nền tảng")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["platform"].queryset = Platform.objects.filter(is_active=True)


class UploadForm(BootstrapFormMixin, forms.Form):
    data_file = forms.FileField(label="Tệp CSV/XLSX", help_text="Tối đa 25 MB")

    def clean_data_file(self):
        uploaded = self.cleaned_data["data_file"]
        suffix = uploaded.name.lower().rsplit(".", 1)[-1] if "." in uploaded.name else ""
        if suffix not in {"csv", "xlsx"}:
            raise forms.ValidationError("Chỉ chấp nhận tệp CSV hoặc XLSX.")
        if uploaded.size > 25 * 1024 * 1024:
            raise forms.ValidationError("Tệp vượt quá giới hạn 25 MB.")
        return uploaded


class MappingForm(BootstrapFormMixin, forms.Form):
    profile_name = forms.CharField(label="Tên cấu hình mapping", required=False, initial="Mapping import")
    save_profile = forms.BooleanField(label="Lưu làm cấu hình dùng lại", required=False)

    def __init__(self, *args, columns=None, initial_mapping=None, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "— Không ánh xạ —")] + [(column, column) for column in (columns or [])]
        initial_mapping = initial_mapping or {}
        for target, label in CANONICAL_FIELDS.items():
            self.fields[target] = forms.ChoiceField(
                choices=choices,
                label=label + (" *" if target in REQUIRED_FIELDS else ""),
                required=target in REQUIRED_FIELDS,
                initial=initial_mapping.get(target, ""),
            )

    def mapping(self):
        return {key: self.cleaned_data.get(key, "") for key in CANONICAL_FIELDS if self.cleaned_data.get(key)}


class ConfirmImportForm(BootstrapFormMixin, forms.Form):
    duplicate_action = forms.ChoiceField(
        label="Khi đơn hàng đã tồn tại",
        choices=(("SKIP", "Bỏ qua (khuyến nghị)"), ("UPDATE", "Cập nhật từ file")),
        initial="SKIP",
        widget=forms.RadioSelect,
    )


class ProductForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ("internal_sku", "product_name", "variant_name", "default_cost", "is_active")


class ProductAliasForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProductAlias
        fields = ("platform", "external_sku", "external_product_name", "product")

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("external_sku") and not cleaned.get("external_product_name"):
            raise forms.ValidationError("Cần nhập SKU ngoài hoặc tên sản phẩm ngoài.")
        return cleaned


class MappingProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = MappingProfile
        fields = ("platform", "name", "version", "is_default")

