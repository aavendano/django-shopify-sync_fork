# Plan de implementación: InventoryItem, InventoryLevel y Location

## Objetivos
- Añadir soporte de **InventoryItem**, **InventoryLevel** y **Location** como modelos de primer nivel en Django, alineados con el Admin GraphQL API de Shopify.
- Sincronizar datos con Shopify (query/refresh) y almacenar estados de inventario por ubicación.
- Preparar la base para futuras mutaciones (activar/desactivar items, crear/editar locations).

## Alcance y decisiones principales
- **Persistencia**: se guardarán IDs GraphQL (`gid://...`) y `legacyResourceId` cuando aplique.
- **Relaciones**: `Variant` seguirá siendo el punto de entrada; se conectará con `InventoryItem` y éste con `InventoryLevel` + `Location`.
- **Sincronización**: se prioriza lectura (queries) antes de escritura (mutaciones), para minimizar riesgos.

---

## Fase 1: Modelos y migraciones
1. **Crear modelo `Location`**
   - Campos sugeridos: `shop` (FK), `gid`, `name`, `is_active`, `activatable`, `deactivatable`, `deletable`,
     `address` (JSON), `fulfills_online_orders`, `has_active_inventory`, `has_unfulfilled_orders`,
     `local_pickup_settings` (JSON), `created_at`, `updated_at`.
2. **Crear modelo `InventoryItem`**
   - Campos sugeridos: `shop`, `gid`, `sku`, `tracked`, `tracked_editable`, `requires_shipping`,
     `country_code_of_origin`, `province_code_of_origin`, `harmonized_system_code`,
     `country_harmonized_system_codes` (JSON), `unit_cost_amount`, `unit_cost_currency`,
     `legacy_resource_id`, `locations_count`.
   - Relación: One-to-One con `Variant` (o FK si existen variantes compartiendo item en el futuro).
3. **Crear modelo `InventoryLevel`**
   - Campos sugeridos: `shop`, `gid`, `inventory_item` (FK), `location` (FK),
     `quantities` (JSON), `can_deactivate`, `deactivation_alert`, `scheduled_changes` (JSON),
     `created_at`, `updated_at`.
4. **Restricciones y unicidad**
   - `InventoryLevel` debe ser único por (`inventory_item`, `location`) para evitar duplicados.
   - Índices por `gid` y por (`shop`, `sku`) cuando aplique.

---

## Fase 2: Queries GraphQL y sincronización
1. **Queries base**
   - `locations(first:, query:)` para cargar ubicaciones.
   - `inventoryItems(first:, query:)` para obtener items (filtrando por `sku` o `updated_at`).
   - `inventoryLevel(id:)` cuando se conozca el GID exacto.
2. **Mapeo de respuestas**
   - Normalizar `MoneyV2` a `unit_cost_amount` + `unit_cost_currency`.
   - Almacenar `quantities(names: [...])` como JSON con clave = `name`.
3. **Servicios de sincronización**
   - Crear funciones en `handlers` o un módulo nuevo `shopify_sync/services/inventory.py`.
   - Flujo recomendado:
     1. Sync `Location` (por shop).
     2. Sync `InventoryItem` (por shop; opcionalmente filtrado por SKU/updated_at).
     3. Sync `InventoryLevel` usando `inventoryItem.inventoryLevels` o `location.inventoryLevel`.
4. **Estrategia incremental**
   - Guardar `updated_at`/`created_at` para paginar y hacer backfill.
   - Permitir “partial sync” por `sku` o `locationId`.
5. **Flujo de trabajo para actualizaciones frecuentes de InventoryLevel**
   - Añadir un campo booleano `sync_pending` en `InventoryLevel` para marcar registros pendientes de sincronización.
     - `sync_pending=true` se encola en la siguiente sincronización.
     - Tras confirmar la sincronización, se actualiza a `sync_pending=false`.
   - Registrar `last_synced_at` y `source_updated_at` en `InventoryLevel` para detectar cambios desde Shopify.
   - Identificar InventoryLevels a actualizar con `sync_pending=true` y/o filtros por `updatedAt`.
   - Diseñar una abstracción de sincronización por `Location` que:
     1. Obtenga los `InventoryLevel` cambiados desde la última ejecución.
     2. Encole lotes por `locationId` para minimizar consultas repetidas.
     3. Limite concurrencia y pagine resultados para respetar rate limits.
   - Priorizar `inventoryLevels` por `Location` para evitar llamadas redundantes por item cuando el volumen es alto.
   - Reintentos con backoff exponencial ante respuestas de throttling y registrar métricas de consumo.
6. **Queries concretas validadas (Admin GraphQL API)**
   - **LocationsPage** (full/incremental):
     ```graphql
     query LocationsPage($first: Int!, $after: String, $query: String) {
       locations(first: $first, after: $after, query: $query) {
         edges {
           cursor
           node {
             id
             legacyResourceId
             name
             isActive
             activatable
             deactivatable
             fulfillsOnlineOrders
             hasActiveInventory
             hasUnfulfilledOrders
             shipsInventory
             address {
               address1
               address2
               city
               country
               countryCode
               province
               provinceCode
               zip
             }
             localPickupSettingsV2 {
               pickupTime
               instructions
             }
             createdAt
             updatedAt
           }
         }
         pageInfo {
           hasNextPage
           endCursor
         }
       }
     }
     ```
     - Incremental: usar `query: "updated_at:>='2025-01-01T00:00:00Z'"`.
   - **InventoryItemsPage** (por SKU o updated_at):
     ```graphql
     query InventoryItemsPage($first: Int!, $after: String, $query: String) {
       inventoryItems(first: $first, after: $after, query: $query) {
         edges {
           cursor
           node {
             id
             legacyResourceId
             sku
             tracked
             requiresShipping
             countryCodeOfOrigin
             provinceCodeOfOrigin
             harmonizedSystemCode
             countryHarmonizedSystemCodes(first: 10) {
               edges {
                 node {
                   harmonizedSystemCode
                   countryCode
                 }
               }
             }
             unitCost {
               amount
               currencyCode
             }
             locationsCount {
               count
             }
             updatedAt
           }
         }
         pageInfo {
           hasNextPage
           endCursor
         }
       }
     }
     ```
     - Ejemplos de `query` (search syntax):
       - `sku:ABC-123`
       - `updated_at:>='2025-01-01T00:00:00Z'`
       - `sku:ABC-123 updated_at:>='2025-01-01T00:00:00Z'`
   - **InventoryItemWithLevelsBySku** (llenado inicial por SKU):
     ```graphql
     query InventoryItemWithLevelsBySku(
       $skuQuery: String!
       $inventoryLevelsFirst: Int!
       $inventoryLevelsAfter: String
     ) {
       inventoryItems(first: 1, query: $skuQuery) {
         nodes {
           id
           legacyResourceId
           sku
           inventoryLevels(first: $inventoryLevelsFirst, after: $inventoryLevelsAfter) {
             edges {
               cursor
               node {
                 id
                 canDeactivate
                 deactivationAlert
                 quantities(names: ["available", "incoming", "on_hand"]) {
                   name
                   quantity
                 }
                 scheduledChanges(first: 10) {
                   edges {
                     node {
                       expectedAt
                       quantity
                     }
                   }
                 }
                 item {
                   id
                   sku
                 }
                 location {
                   id
                   name
                   isActive
                   fulfillsOnlineOrders
                   hasActiveInventory
                   hasUnfulfilledOrders
                 }
                 createdAt
                 updatedAt
               }
             }
             pageInfo {
               hasNextPage
               endCursor
             }
           }
         }
       }
     }
     ```
   - **LocationInventoryLevelsSince** (sincronización incremental por Location):
     ```graphql
     query LocationInventoryLevelsSince(
       $locationId: ID!
       $first: Int!
       $after: String
       $updatedAtQuery: String!
     ) {
       location(id: $locationId) {
         id
         name
         inventoryLevels(first: $first, after: $after, query: $updatedAtQuery) {
           edges {
             cursor
             node {
               id
               quantities(names: ["available", "incoming", "on_hand"]) {
                 name
                 quantity
               }
               item {
                 id
                 sku
               }
               location {
                 id
                 name
               }
               createdAt
               updatedAt
             }
           }
           pageInfo {
             hasNextPage
             endCursor
           }
         }
       }
     }
     ```
     - `updatedAtQuery`: `updated_at:>='2025-01-10T12:00:00Z'`
7. **Mutaciones clave (Fase 4 futura)**
   - **inventoryActivate**:
     ```graphql
     mutation ActivateInventoryItemAtLocation(
       $inventoryItemId: ID!
       $locationId: ID!
       $available: Int
     ) {
       inventoryActivate(inventoryItemId: $inventoryItemId, locationId: $locationId, available: $available) {
         inventoryLevel {
           id
           canDeactivate
           deactivationAlert
           quantities(names: ["available"]) {
             name
             quantity
           }
           item {
             id
             sku
           }
           location {
             id
             name
           }
           createdAt
           updatedAt
         }
       }
     }
     ```
   - **inventoryBulkToggleActivation**:
     ```graphql
     mutation BulkToggleInventoryActivation(
       $inventoryItemId: ID!
       $inventoryItemUpdates: [InventoryBulkToggleActivationInput!]!
     ) {
       inventoryBulkToggleActivation(
         inventoryItemId: $inventoryItemId
         inventoryItemUpdates: $inventoryItemUpdates
       ) {
         inventoryItem {
           id
         }
         inventoryLevels {
           id
           quantities(names: ["available"]) {
             name
             quantity
           }
           location {
             id
             name
           }
         }
         userErrors {
           field
           message
           code
         }
       }
     }
     ```
   - **inventoryItemUpdate**:
     ```graphql
     mutation UpdateInventoryItem($id: ID!, $input: InventoryItemInput!) {
       inventoryItemUpdate(id: $id, input: $input) {
         inventoryItem {
           id
           sku
           tracked
           requiresShipping
           countryCodeOfOrigin
           provinceCodeOfOrigin
           harmonizedSystemCode
           unitCost {
             amount
             currencyCode
           }
         }
         userErrors {
           field
           message
         }
       }
     }
     ```
   - **locationAdd / locationEdit / locationActivate / locationDeactivate**:
     ```graphql
     mutation AddLocation($input: LocationAddInput!) {
       locationAdd(input: $input) {
         location {
           id
           legacyResourceId
           name
           isActive
           fulfillsOnlineOrders
           hasActiveInventory
           hasUnfulfilledOrders
           address {
             address1
             city
             country
             countryCode
             province
             provinceCode
             zip
           }
           createdAt
           updatedAt
         }
         userErrors {
           field
           message
           code
         }
       }
     }
     mutation EditLocation($id: ID!, $input: LocationEditInput!) {
       locationEdit(id: $id, input: $input) {
         location {
           id
           name
           isActive
           fulfillsOnlineOrders
           hasActiveInventory
           hasUnfulfilledOrders
           address {
             address1
             city
             country
             countryCode
             province
             provinceCode
             zip
           }
           updatedAt
         }
         userErrors {
           field
           message
         }
       }
     }
     mutation ActivateLocation($locationId: ID!) {
       locationActivate(locationId: $locationId) {
         location {
           id
           isActive
         }
         locationActivateUserErrors {
           field
           message
           code
         }
       }
     }
     mutation DeactivateLocation($locationId: ID!) {
       locationDeactivate(locationId: $locationId) {
         location {
           id
           isActive
         }
         locationDeactivateUserErrors {
           field
           message
           code
         }
       }
     }
     ```

---

## Fase 3: Integración con modelos existentes
1. **Variant → InventoryItem**
   - Agregar FK/OneToOne de `Variant` a `InventoryItem`.
   - Población inicial usando el `inventoryItem` del variant en Shopify.
2. **Admin y serializers**
   - Incluir `InventoryItem`, `InventoryLevel`, `Location` en `admin.py`.
   - Añadir serializadores (si aplica en API interna).
3. **Método en `Location` para activar el flujo**
   - Añadir un método en `Location` (ej. `schedule_inventory_level_sync` o `trigger_inventory_sync`) que:
     - Dispare la sincronización para esa ubicación (sin requerir jobs periódicos).
     - Use `sync_pending` y `last_synced_at` para traer solo cambios.
     - Registre el inicio/fin y resultados (items actualizados, throttling, errores).

---

## Fase 4: Mutaciones (opcional, fase posterior)
1. **InventoryItem**
   - `inventoryItemUpdate` para actualizar `sku`, `tracked`, `unitCost`, datos aduanales.
2. **InventoryLevel**
   - `inventoryActivate` para crear niveles por ubicación.
   - `inventoryBulkToggleActivation` para activar/desactivar en lote.
3. **Location**
   - `locationAdd`, `locationEdit`, `locationActivate`, `locationDeactivate`.

---

## Fase 5: Pruebas y validación
1. **Tests unitarios de mapeo**
   - Validar parsing de `MoneyV2`, `quantities`, `address`, y `scheduledChanges`.
2. **Tests de sincronización**
   - Mock de respuestas GraphQL para asegurar insert/update idempotente.
3. **Smoke tests**
   - Sync con 1 shop + 1 sku + 1 location para comprobar integridad.

---

## Entregables
- Modelos + migraciones.
- Servicios de sincronización.
- Documentación de configuración y scopes requeridos (`read_inventory`, `read_products`, `read_locations`).
- Cobertura de tests de mapeo y sync.
