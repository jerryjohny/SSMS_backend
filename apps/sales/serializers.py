from decimal import Decimal

from rest_framework import serializers

from apps.accounts.models import Store
from apps.catalog.models import Product
from apps.customers.models import Customer
from apps.customers.serializers import CustomerSerializer

from .models import CustomerBalanceEntry, Sale, SaleItem
from .services import create_sale_from_payload


class CustomerBalanceEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerBalanceEntry
        fields = ["id", "entry_type", "amount", "status", "note", "created_at"]
        read_only_fields = ["created_at"]


class SaleItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    debt_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    credit_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    balance_entries = CustomerBalanceEntrySerializer(many=True, read_only=True)

    class Meta:
        model = SaleItem
        fields = [
            "id",
            "product",
            "product_name",
            "quantity_units",
            "unit_price",
            "line_total",
            "amount_paid",
            "pickup_status",
            "payment_status",
            "note",
            "voice_note",
            "pending_priority",
            "is_collected",
            "is_settled",
            "debt_amount",
            "credit_amount",
            "balance_entries",
        ]


class SaleSerializer(serializers.ModelSerializer):
    items = SaleItemSerializer(many=True, read_only=True)
    customer = CustomerSerializer(read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    seller_name = serializers.CharField(source="seller.display_name", read_only=True)

    class Meta:
        model = Sale
        fields = [
            "id",
            "order_number",
            "store",
            "store_name",
            "seller",
            "seller_name",
            "customer",
            "status",
            "note",
            "gross_total",
            "paid_total",
            "debt_total",
            "credit_total",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["seller", "created_at", "updated_at"]


class InlineCustomerSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    name = serializers.CharField(required=False)
    reference = serializers.CharField(required=False)
    phone = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs.get("id"):
            return attrs
        if not attrs.get("name") or not attrs.get("reference"):
            raise serializers.ValidationError("New customers require at least a name and memorable reference.")
        return attrs


class SaleItemInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity_units = serializers.IntegerField(min_value=1, default=1)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2, default=0)
    pickup_status = serializers.ChoiceField(choices=SaleItem.PickupStatus.choices, default=SaleItem.PickupStatus.NOW)
    payment_status = serializers.ChoiceField(
        choices=SaleItem.PaymentStatus.choices,
        default=SaleItem.PaymentStatus.NOW,
    )
    note = serializers.CharField(required=False, allow_blank=True)
    voice_note = serializers.FileField(required=False, allow_null=True)


class SaleCreateSerializer(serializers.Serializer):
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())
    customer = InlineCustomerSerializer(required=False)
    note = serializers.CharField(required=False, allow_blank=True)
    items = SaleItemInputSerializer(many=True)

    def validate(self, attrs):
        tenant = self.context["tenant"]
        store = attrs["store"]
        if store.tenant_id != tenant.id:
            raise serializers.ValidationError({"store": "Selected store does not belong to the active tenant."})
        if not attrs["items"]:
            raise serializers.ValidationError({"items": "At least one sale item is required."})
        for item in attrs["items"]:
            if item["product"].tenant_id != tenant.id:
                raise serializers.ValidationError({"items": f"Product {item['product'].name} does not belong to the active tenant."})
        return attrs

    def create(self, validated_data):
        tenant = self.context["tenant"]
        seller = self.context["request"].user
        return create_sale_from_payload(tenant=tenant, seller=seller, validated_data=validated_data)


class PendingSaleItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    customer_name = serializers.CharField(source="sale.customer.name", read_only=True)
    order_number = serializers.CharField(source="sale.order_number", read_only=True)
    store_name = serializers.CharField(source="sale.store.name", read_only=True)
    debt_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    credit_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = SaleItem
        fields = [
            "id",
            "order_number",
            "product_name",
            "customer_name",
            "store_name",
            "quantity_units",
            "line_total",
            "amount_paid",
            "pickup_status",
            "payment_status",
            "pending_priority",
            "note",
            "debt_amount",
            "credit_amount",
            "is_collected",
            "is_settled",
        ]


class PendingRegularizeSerializer(serializers.Serializer):
    mark_collected = serializers.BooleanField(default=False)
    regularize_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
    )

    def validate(self, attrs):
        if not attrs.get("mark_collected") and not attrs.get("regularize_amount"):
            raise serializers.ValidationError("Select at least one regularization action.")
        return attrs
