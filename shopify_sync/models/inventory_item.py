from decimal import Decimal

from django.db import models
from jsonfield import JSONField

from ..encoders import ShopifyDjangoJSONEncoder
from .base import ShopifyDatedResourceModel


class InventoryItem(ShopifyDatedResourceModel):
    objects = models.Manager()

    sku = models.CharField(max_length=255, null=True)
    tracked = models.BooleanField(default=False)
    requires_shipping = models.BooleanField(default=False)
    country_code_of_origin = models.CharField(max_length=2, null=True)
    province_code_of_origin = models.CharField(max_length=255, null=True)
    harmonized_system_code = models.CharField(max_length=255, null=True)
    country_harmonized_system_codes = JSONField(
        dump_kwargs={"cls": ShopifyDjangoJSONEncoder},
        null=True,
    )
    unit_cost_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True
    )
    unit_cost_currency = models.CharField(max_length=3, null=True)
    locations_count = models.IntegerField(null=True)
    variant = models.OneToOneField(
        "shopify_sync.Variant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_item",
    )

    class Meta:
        app_label = "shopify_sync"

    @classmethod
    def normalize_unit_cost(cls, unit_cost):
        if not unit_cost:
            return None, None
        amount = unit_cost.get("amount")
        currency = unit_cost.get("currencyCode")
        if amount is None:
            return None, currency
        return Decimal(str(amount)), currency
