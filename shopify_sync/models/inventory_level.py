from django.db import models
from jsonfield import JSONField

from ..encoders import ShopifyDjangoJSONEncoder
from .base import ShopifyDatedResourceModel


class InventoryLevel(ShopifyDatedResourceModel):
    objects = models.Manager()

    inventory_item = models.ForeignKey(
        "shopify_sync.InventoryItem",
        on_delete=models.CASCADE,
        related_name="inventory_levels",
    )
    location = models.ForeignKey(
        "shopify_sync.Location",
        on_delete=models.CASCADE,
        related_name="inventory_levels",
    )
    quantities = JSONField(
        dump_kwargs={"cls": ShopifyDjangoJSONEncoder},
        null=True,
    )
    can_deactivate = models.BooleanField(default=False)
    deactivation_alert = models.TextField(null=True)
    scheduled_changes = JSONField(
        dump_kwargs={"cls": ShopifyDjangoJSONEncoder},
        null=True,
    )
    sync_pending = models.BooleanField(default=False)
    source_updated_at = models.DateTimeField(null=True)
    synced_at = models.DateTimeField(null=True)

    class Meta:
        app_label = "shopify_sync"
        constraints = [
            models.UniqueConstraint(
                fields=["inventory_item", "location"],
                name="inventory_level_unique_item_location",
            )
        ]
