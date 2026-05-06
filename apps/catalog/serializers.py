from rest_framework import serializers

from apps.accounts.models import Store

from .models import Inventory, Product, StockBatch, StockMovement


class StockBatchSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    store_name = serializers.CharField(source="inventory.store.name", read_only=True)

    class Meta:
        model = StockBatch
        fields = [
            "id",
            "product",
            "product_name",
            "store_name",
            "units_received",
            "units_remaining",
            "packages_received",
            "boxes_received",
            "expiry_date",
            "note",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class InventorySerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_barcode = serializers.CharField(source="product.barcode", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    available_units = serializers.IntegerField(read_only=True)

    class Meta:
        model = Inventory
        fields = [
            "id",
            "tenant",
            "product",
            "product_name",
            "product_barcode",
            "store",
            "store_name",
            "stock_units",
            "reserved_units",
            "available_units",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["tenant", "created_at", "updated_at"]


class ProductSerializer(serializers.ModelSerializer):
    total_stock_units = serializers.SerializerMethodField()
    nearest_expiry_date = serializers.SerializerMethodField()
    inventories = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "tenant",
            "name",
            "barcode",
            "sku",
            "description",
            "packaging_details",
            "unit_price",
            "package_price",
            "box_price",
            "units_per_package",
            "units_per_box",
            "image",
            "is_active",
            "total_stock_units",
            "nearest_expiry_date",
            "inventories",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["tenant", "created_at", "updated_at"]

    def _store_scoped_inventories(self, product):
        store_id = self.context.get("store_id")
        inventories = list(product.inventories.all())
        if not store_id:
            return inventories
        return [inventory for inventory in inventories if str(inventory.store_id) == str(store_id)]

    def get_total_stock_units(self, product):
        inventories = self._store_scoped_inventories(product)
        if inventories:
            return sum(inventory.available_units for inventory in inventories if inventory.is_active)
        return 0 if self.context.get("store_id") else product.total_stock_units

    def get_nearest_expiry_date(self, product):
        store_id = self.context.get("store_id")
        relevant_dates = []

        for batch in product.stock_batches.all():
            if batch.units_remaining <= 0 or not batch.expiry_date:
                continue
            if store_id and str(batch.inventory.store_id) != str(store_id):
                continue
            relevant_dates.append(batch.expiry_date)

        if relevant_dates:
            return min(relevant_dates)

        return None if self.context.get("store_id") else product.nearest_expiry_date

    def get_inventories(self, product):
        inventories = self._store_scoped_inventories(product)
        return InventorySerializer(inventories, many=True, context=self.context).data


class ProductRegistrationSerializer(serializers.ModelSerializer):
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())
    initial_units = serializers.IntegerField(min_value=0, default=0)
    initial_packages = serializers.IntegerField(min_value=0, default=0)
    initial_boxes = serializers.IntegerField(min_value=0, default=0)
    initial_expiry_date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "barcode",
            "sku",
            "description",
            "packaging_details",
            "unit_price",
            "package_price",
            "box_price",
            "units_per_package",
            "units_per_box",
            "image",
            "is_active",
            "store",
            "initial_units",
            "initial_packages",
            "initial_boxes",
            "initial_expiry_date",
            "note",
        ]

    def validate(self, attrs):
        if attrs["store"].tenant_id != self.context["tenant"].id:
            raise serializers.ValidationError({"store": "Selected store does not belong to the active tenant."})
        return attrs

    def create(self, validated_data):
        store = validated_data.pop("store")
        initial_units = validated_data.pop("initial_units", 0)
        initial_packages = validated_data.pop("initial_packages", 0)
        initial_boxes = validated_data.pop("initial_boxes", 0)
        initial_expiry_date = validated_data.pop("initial_expiry_date", None)
        note = validated_data.pop("note", "")
        tenant = self.context["tenant"]
        performed_by = getattr(self.context["request"], "user", None)

        product = Product.objects.create(tenant=tenant, **validated_data)
        inventory = Inventory.objects.create(tenant=tenant, product=product, store=store, stock_units=0)
        converted_units = (
            initial_units
            + initial_packages * product.units_per_package
            + initial_boxes * product.units_per_box
        )

        if converted_units:
            inventory.stock_units = converted_units
            inventory.save(update_fields=["stock_units", "updated_at"])
            batch = StockBatch.objects.create(
                tenant=tenant,
                inventory=inventory,
                product=product,
                units_received=converted_units,
                units_remaining=converted_units,
                packages_received=initial_packages,
                boxes_received=initial_boxes,
                expiry_date=initial_expiry_date,
                note=note,
            )
            StockMovement.objects.create(
                tenant=tenant,
                inventory=inventory,
                batch=batch,
                performed_by=performed_by if getattr(performed_by, "is_authenticated", False) else None,
                movement_type=StockMovement.MovementType.REGISTER,
                units_delta=converted_units,
                note=note,
                unit_price_snapshot=product.unit_price,
            )

        return product


class RestockSerializer(serializers.Serializer):
    inventory = serializers.PrimaryKeyRelatedField(queryset=Inventory.objects.select_related("product", "store").all())
    units_added = serializers.IntegerField(min_value=0, default=0)
    packages_added = serializers.IntegerField(min_value=0, default=0)
    boxes_added = serializers.IntegerField(min_value=0, default=0)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["inventory"].tenant_id != self.context["tenant"].id:
            raise serializers.ValidationError({"inventory": "Selected inventory does not belong to the active tenant."})
        total_entries = attrs["units_added"] + attrs["packages_added"] + attrs["boxes_added"]
        if total_entries <= 0:
            raise serializers.ValidationError("At least one stock quantity must be greater than zero.")
        return attrs

    def save(self, **kwargs):
        inventory = self.validated_data["inventory"]
        product = inventory.product
        tenant = self.context["tenant"]
        performed_by = getattr(self.context["request"], "user", None)
        units_added = (
            self.validated_data["units_added"]
            + self.validated_data["packages_added"] * product.units_per_package
            + self.validated_data["boxes_added"] * product.units_per_box
        )

        inventory.stock_units += units_added
        inventory.save(update_fields=["stock_units", "updated_at"])

        batch = StockBatch.objects.create(
            tenant=tenant,
            inventory=inventory,
            product=product,
            units_received=units_added,
            units_remaining=units_added,
            packages_received=self.validated_data["packages_added"],
            boxes_received=self.validated_data["boxes_added"],
            expiry_date=self.validated_data.get("expiry_date"),
            note=self.validated_data.get("note", ""),
        )
        StockMovement.objects.create(
            tenant=tenant,
            inventory=inventory,
            batch=batch,
            performed_by=performed_by if getattr(performed_by, "is_authenticated", False) else None,
            movement_type=StockMovement.MovementType.RESTOCK,
            units_delta=units_added,
            note=self.validated_data.get("note", ""),
            unit_price_snapshot=product.unit_price,
        )
        return inventory
