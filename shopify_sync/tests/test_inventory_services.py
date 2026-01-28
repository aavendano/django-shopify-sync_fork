from unittest import mock

from django.test import TestCase
from django.utils import timezone

from shopify_sync.graphql import ShopifyGraphQLClient
from shopify_sync.models import InventoryLevel, Location
from shopify_sync.services import inventory as inventory_service
from shopify_sync.models import Session


class GraphQLClientThrottleTests(TestCase):
    def test_throttle_waits_for_capacity(self):
        session = Session.objects.create(site="test.myshopify.com", token="TESTTOKEN")
        client = ShopifyGraphQLClient(session, min_available=50)
        extensions = {
            "cost": {
                "throttleStatus": {
                    "currentlyAvailable": 10,
                    "restoreRate": 5,
                }
            }
        }
        with mock.patch("shopify_sync.graphql.time.sleep") as mocked_sleep:
            client._apply_throttle(extensions)
        mocked_sleep.assert_called_once_with(8.0)


class InventoryServiceTests(TestCase):
    def setUp(self):
        self.session = Session.objects.create(
            site="test.myshopify.com",
            token="TESTTOKEN",
        )

    def test_sync_locations_parses_legacy_id(self):
        response = {
            "locations": {
                "edges": [
                    {
                        "cursor": "cursor",
                        "node": {
                            "id": "gid://shopify/Location/101",
                            "legacyResourceId": None,
                            "name": "Primary",
                            "isActive": True,
                            "activatable": True,
                            "deactivatable": True,
                            "deletable": False,
                            "fulfillsOnlineOrders": True,
                            "hasActiveInventory": True,
                            "hasUnfulfilledOrders": False,
                            "shipsInventory": True,
                            "address": {"city": "NYC"},
                            "localPickupSettingsV2": None,
                            "createdAt": "2025-02-20T00:00:00Z",
                            "updatedAt": "2025-02-20T01:00:00Z",
                        },
                    }
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
        with mock.patch(
            "shopify_sync.services.inventory.ShopifyGraphQLClient.execute",
            return_value=(response, {}),
        ):
            count = inventory_service.sync_locations(self.session)
        self.assertEqual(count, 1)
        location = Location.objects.get(id=101)
        self.assertEqual(location.name, "Primary")
        self.assertTrue(location.is_active)

    def test_sync_location_inventory_levels_creates_records(self):
        location = Location.objects.create(
            id=55,
            session=self.session,
            admin_graphql_api_id="gid://shopify/Location/55",
            name="Warehouse",
        )
        now = timezone.now()
        response = {
            "location": {
                "id": "gid://shopify/Location/55",
                "name": "Warehouse",
                "inventoryLevels": {
                    "edges": [
                        {
                            "cursor": "cursor",
                            "node": {
                                "id": "gid://shopify/InventoryLevel/900?inventory_item_id=77",
                                "quantities": [
                                    {"name": "available", "quantity": 12},
                                    {"name": "on_hand", "quantity": 15},
                                ],
                                "item": {
                                    "id": "gid://shopify/InventoryItem/77",
                                    "sku": "SKU-77",
                                },
                                "location": {
                                    "id": "gid://shopify/Location/55",
                                    "name": "Warehouse",
                                },
                                "createdAt": "2025-02-20T02:00:00Z",
                                "updatedAt": "2025-02-20T03:00:00Z",
                            },
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                },
            }
        }
        with mock.patch(
            "shopify_sync.services.inventory.ShopifyGraphQLClient.execute",
            return_value=(response, {}),
        ):
            count = inventory_service.sync_location_inventory_levels(location)
        self.assertEqual(count, 1)
        level = InventoryLevel.objects.get(location=location, inventory_item_id=77)
        self.assertEqual(level.quantities["available"], 12)
        self.assertFalse(level.sync_pending)
        self.assertEqual(level.source_updated_at.isoformat(), "2025-02-20T03:00:00+00:00")
        self.assertTrue(level.synced_at >= now)
        location.refresh_from_db()
        self.assertIsNotNone(location.last_inventory_sync_at)
