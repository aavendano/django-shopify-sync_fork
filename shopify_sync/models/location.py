from django.db import models
from jsonfield import JSONField

from ..encoders import ShopifyDjangoJSONEncoder
from .base import ShopifyDatedResourceModel


class Location(ShopifyDatedResourceModel):
    objects = models.Manager()

    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=False)
    activatable = models.BooleanField(default=False)
    deactivatable = models.BooleanField(default=False)
    deletable = models.BooleanField(default=False)
    fulfills_online_orders = models.BooleanField(default=False)
    has_active_inventory = models.BooleanField(default=False)
    has_unfulfilled_orders = models.BooleanField(default=False)
    ships_inventory = models.BooleanField(default=False)
    address = JSONField(
        dump_kwargs={"cls": ShopifyDjangoJSONEncoder},
        null=True,
    )
    local_pickup_settings = JSONField(
        dump_kwargs={"cls": ShopifyDjangoJSONEncoder},
        null=True,
    )
    last_inventory_sync_at = models.DateTimeField(null=True)

    class Meta:
        app_label = "shopify_sync"

    def trigger_inventory_sync(
        self,
        *,
        updated_at_query=None,
        page_size=50,
        max_pages=None,
        throttle=True,
        quantity_names=None,
    ):
        from ..services.inventory import sync_location_inventory_levels

        return sync_location_inventory_levels(
            self,
            updated_at_query=updated_at_query,
            page_size=page_size,
            max_pages=max_pages,
            throttle=throttle,
            quantity_names=quantity_names,
        )
